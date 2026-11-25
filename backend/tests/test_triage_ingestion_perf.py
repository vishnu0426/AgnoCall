"""Failure triage, retry safety, ingestion health, batched poller, query-count guards."""
import pytest
from sqlalchemy import event, inspect

pytest.importorskip("celery")

from app.api import calls as calls_api  # noqa: E402
from app.api import dashboard, ingestion, triage  # noqa: E402
from app.core import heartbeat  # noqa: E402
from app.core.failures import classify_failure  # noqa: E402
from app.core.indexes import INDEXES, ensure_indexes  # noqa: E402
from app.models.models import (  # noqa: E402
    Call, CallLabel, CallStatus, ComplianceViolation, CustomerAnalytics, QAEvaluation,
)
from app.schemas.schemas import RetryRequest  # noqa: E402
from app.tasks import pipeline, sync  # noqa: E402

NO_SPEECH = "No speech detected in this recording — nothing to transcribe or analyze."
WINERR = "[WinError 2] The system cannot find the file specified\nTraceback..."
TIMEOUT = "Command '['/usr/bin/ffmpeg', '-i', 'pipe:0']' timed out after 120 seconds"
BUG = "unsupported operand type(s) for +: 'int' and 'NoneType'\nTraceback (most recent call last):"
DECODE = "Could not decode this audio file: Invalid data found when processing input"


def add(db, name, status=CallStatus.processed, reason=None, meta=None):
    c = Call(original_filename=name, storage_path=f"x/{name}", status=status,
             failure_reason=reason, call_metadata=meta or {})
    db.add(c)
    db.commit()
    return c


# ---- classification ----------------------------------------------------------

@pytest.mark.parametrize("reason,category,retryable,expected", [
    (NO_SPEECH, "no_speech", False, True),
    (WINERR, "tool_missing", True, False),
    (TIMEOUT, "timeout", True, False),
    (BUG, "unexpected", True, False),
    (DECODE, "bad_audio", False, False),
    ("Stuck in 'processing' with no activity ... giving up automatically.", "worker_crashed", True, False),
    ("openai.RateLimitError: rate limit exceeded", "external_service", True, False),
    (None, "unexpected", True, False),
    ("", "unexpected", True, False),
])
def test_classify_failure(reason, category, retryable, expected):
    info = classify_failure(reason)
    assert (info.category, info.retryable, info.expected) == (category, retryable, expected)


# ---- summary + dashboard ---------------------------------------------------------

def seed_failures(db):
    for i in range(3):
        add(db, f"s{i}", CallStatus.failed, NO_SPEECH)
    for i in range(2):
        add(db, f"w{i}", CallStatus.failed, WINERR)
    add(db, "b", CallStatus.failed, BUG)
    add(db, "d", CallStatus.failed, DECODE)
    add(db, "ok", CallStatus.processed)


def test_failure_summary_and_dashboard_separate_expected_from_actionable(db):
    seed_failures(db)
    fs = triage.summarize_failures(db)
    assert (fs.total_failed, fs.expected, fs.actionable, fs.retryable) == (7, 3, 4, 3)
    assert [g.category for g in fs.groups][0] == "no_speech"          # biggest first
    d = dashboard.dashboard_summary(db)
    assert (d.failed, d.failed_expected, d.failed_actionable, d.failed_retryable) == (7, 3, 4, 3)


# ---- retry safety --------------------------------------------------------------------

@pytest.fixture()
def queued(monkeypatch):
    sent = []
    monkeypatch.setattr(triage.run_pipeline, "delay", lambda cid: sent.append(cid))
    return sent


def test_retry_all_only_requeues_retryable_failures(db, queued):
    seed_failures(db)
    r = triage.retry_failed(RetryRequest(), db)
    assert (r.retried, r.skipped_not_retryable) == (3, 4)            # 2 env + 1 bug; 3 silent + 1 bad audio skipped
    assert len(queued) == 3
    for c in db.query(Call).filter(Call.id.in_(queued)).all():
        assert c.status == CallStatus.validating and c.failure_reason is None
        assert c.call_metadata["manual_retries"] == 1
    # silent recordings were never touched
    assert db.query(Call).filter(Call.failure_reason == NO_SPEECH).count() == 3


def test_retry_by_category_and_by_id(db, queued):
    seed_failures(db)
    r = triage.retry_failed(RetryRequest(category="tool_missing"), db)
    assert r.retried == 2
    bug = db.query(Call).filter(Call.original_filename == "b").one()
    assert triage.retry_failed(RetryRequest(call_ids=[bug.id]), db).retried == 1
    with pytest.raises(Exception):
        triage.retry_failed(RetryRequest(call_ids=["does-not-exist"]), db)


def test_retry_is_not_repeatable_and_is_capped(db, queued):
    c = add(db, "loop", CallStatus.failed, WINERR, meta={"manual_retries": triage.MAX_MANUAL_RETRIES})
    r = triage.retry_failed(RetryRequest(call_ids=[c.id]), db)
    assert (r.retried, r.skipped_retry_cap) == (0, 1) and queued == []
    # a second request right after a successful claim finds nothing failed to claim
    d = add(db, "once", CallStatus.failed, WINERR)
    assert triage.retry_failed(RetryRequest(call_ids=[d.id]), db).retried == 1
    with pytest.raises(Exception):
        triage.retry_failed(RetryRequest(call_ids=[d.id]), db)       # now validating, not failed
    assert queued == [d.id]


# ---- ingestion health ---------------------------------------------------------------------

def test_ingestion_status_reports_backlog_and_flags_missing_trigger(db, monkeypatch):
    monkeypatch.setattr(ingestion, "_minio_reachable", lambda: True)
    monkeypatch.setattr(ingestion, "last_beats", lambda *names: [None] * len(names))
    add(db, "u", CallStatus.uploaded)
    add(db, "p", CallStatus.processing)
    add(db, "done", CallStatus.processed)
    s = ingestion.ingestion_status(db)
    assert (s.pending, s.processing, s.ingested_last_24h) == (1, 1, 3)
    assert s.state == "degraded" and any("poller" in i for i in s.issues)


def test_ingestion_healthy_and_down(db, monkeypatch):
    import time
    monkeypatch.setattr(ingestion, "_minio_reachable", lambda: True)
    monkeypatch.setattr(ingestion, "last_beats", lambda *names: [time.time() - 2] * len(names))
    assert ingestion.ingestion_status(db).state == "healthy"
    monkeypatch.setattr(ingestion, "_minio_reachable", lambda: False)
    s = ingestion.ingestion_status(db)
    assert s.state == "down" and not s.minio_reachable


def test_heartbeat_never_raises_without_redis(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    from app.core.config import get_settings
    get_settings.cache_clear()
    heartbeat._client.cache_clear()           # the client is cached per process
    heartbeat.beat("x")                       # must not raise
    assert heartbeat.last_beat("x") is None
    assert heartbeat.last_beats("x", "y") == [None, None]
    get_settings.cache_clear()
    heartbeat._client.cache_clear()


# ---- batched poller ---------------------------------------------------------------------------

class FakeObj:
    def __init__(self, name):
        self.object_name = name


def test_poller_is_set_based_and_only_touches_new_or_uploaded(db, monkeypatch):
    prefix = sync._recent_date_prefixes()[0]
    ids = [f"0000000{i}-0000-0000-0000-00000000000{i}" for i in range(1, 5)]
    keys = [f"{prefix}{i}-169-call_x.wav" for i in ids]
    # 1: already processed, 2: waiting at uploaded, 3 & 4: not in the DB yet
    for cid, st in ((ids[0], CallStatus.processed), (ids[1], CallStatus.uploaded)):
        db.add(Call(id=cid, original_filename="f", storage_path="k", status=st))
    db.commit()

    monkeypatch.setattr(sync, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(sync, "beat", lambda name: None)
    # Never touch the real Redis: a running poller on the developer's machine holds these locks.
    held = set()
    monkeypatch.setattr(sync.locks, "acquire", lambda name, ttl: held.add(name) or True)
    monkeypatch.setattr(sync.locks, "release", lambda name: held.discard(name))
    listing = {p: ([FakeObj(k) for k in keys] if p == prefix else []) for p in sync._recent_date_prefixes()}
    monkeypatch.setattr(sync.minio_client._internal_client, "list_objects",
                        lambda bucket, prefix, recursive: listing[prefix], raising=False)
    sent = []
    monkeypatch.setattr(sync.run_pipeline, "delay", lambda cid: sent.append(cid))

    out = sync.sync_call_records()
    assert sorted(out) == sorted(ids[1:]) and sorted(sent) == sorted(ids[1:])   # processed one skipped
    assert db.query(Call).filter(Call.id.in_(ids[2:])).count() == 2              # new ones created
    assert sync.sync_call_records() == []                                        # idempotent next tick


def test_poller_query_count_does_not_grow_with_files(db, monkeypatch):
    prefix = sync._recent_date_prefixes()[0]
    ids = [f"{n:08x}-0000-0000-0000-000000000000" for n in range(1, 61)]
    for cid in ids:
        db.add(Call(id=cid, original_filename="f", storage_path="k", status=CallStatus.processed))
    db.commit()
    monkeypatch.setattr(sync, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(sync, "beat", lambda name: None)
    listing = {p: ([FakeObj(f"{prefix}{i}-1-c.wav") for i in ids] if p == prefix else [])
               for p in sync._recent_date_prefixes()}
    monkeypatch.setattr(sync.minio_client._internal_client, "list_objects",
                        lambda bucket, prefix, recursive: listing[prefix], raising=False)
    n = count_queries(db, lambda: sync.sync_call_records())
    assert n <= 3, f"{n} queries for 60 already-processed files"     # was ~60 (one SELECT per file)


# ---- indexes ------------------------------------------------------------------------------------

def test_ensure_indexes_creates_all_and_is_idempotent(db):
    conn = db.connection()
    first = ensure_indexes(conn)
    from app.core.indexes import UNIQUE_INDEXES
    present = set(inspect(conn).get_table_names())
    expected = sum(1 for _, t, _ in INDEXES if t in present) + sum(1 for _, t, _, _ in UNIQUE_INDEXES if t in present)
    assert first == expected and first > 20
    insp = inspect(conn)
    names = {ix["name"] for t in insp.get_table_names() for ix in insp.get_indexes(t)}
    for name, table, _ in INDEXES:
        if table in insp.get_table_names():
            assert name in names, name
    assert ensure_indexes(conn) == first                         # re-running changes nothing, no error


# ---- query-count guards (N+1 protection) ----------------------------------------------------------------

def count_queries(db, fn):
    n = {"v": 0}

    def before(conn, cursor, statement, params, context, executemany):
        n["v"] += 1

    event.listen(db.get_bind(), "before_cursor_execute", before)
    try:
        fn()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", before)
    return n["v"]


def seed_rich_calls(db, n):
    for i in range(n):
        c = add(db, f"c{i}")
        db.add(QAEvaluation(call_id=c.id, overall_score=50 + i))
        db.add(CustomerAnalytics(call_id=c.id, risk_level="low"))
        db.add(CallLabel(call_id=c.id, label="urgent"))
        for k in range(3):
            db.add(ComplianceViolation(call_id=c.id, rule_code=f"R{k}", category="c", severity="low"))
    db.commit()


def test_call_list_query_count_is_constant_in_page_size(db):
    seed_rich_calls(db, 5)
    small = count_queries(db, lambda: calls_api.list_calls(page=1, page_size=5, db=db))
    db.expire_all()
    seed_rich_calls(db, 40)
    db.expire_all()
    big = count_queries(db, lambda: calls_api.list_calls(page=1, page_size=45, db=db))
    assert big == small, f"list issued {small} queries for 5 rows but {big} for 45 -> N+1"
    assert big <= 6


def test_call_list_content_is_correct(db):
    seed_rich_calls(db, 3)
    out = calls_api.list_calls(page=1, page_size=10, db=db)
    assert out.total == 3
    for item in out.items:
        assert item.compliance_violation_count == 3 and item.labels == ["urgent"] and item.risk_level == "low"


def test_page_size_is_bounded(db):
    seed_rich_calls(db, 3)
    assert calls_api.list_calls(page=1, page_size=100000, db=db).page_size == 100
    assert calls_api.list_calls(page=0, page_size=0, db=db).page == 1


def test_dashboard_query_count_is_small_and_constant(db):
    seed_rich_calls(db, 12)
    n = count_queries(db, lambda: dashboard.dashboard_summary(db))
    assert n <= 10, n


# ---- PostgreSQL-specific query shape (SQLite hides these) --------------------------------------------

def test_failure_summary_group_by_has_no_bind_parameters_for_postgres(db):
    """Regression: with bound parameters (substr(col, $1, $2)) PostgreSQL treats the SELECT and
    GROUP BY copies as different expressions and rejects the query, which 500'd the dashboard.
    SQLite accepts it, so assert on the SQL compiled for the PostgreSQL dialect."""
    from sqlalchemy import func, literal_column
    from sqlalchemy.dialects import postgresql

    captured = []

    def grab(conn, cursor, statement, params, context, executemany):
        captured.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", grab)
    try:
        triage.summarize_failures(db)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", grab)
    sql = captured[0]
    assert sql.count("substr(calls.failure_reason, 1, 600)") == 2      # in SELECT and GROUP BY, inlined
    assert "?" not in sql.split("FROM")[0], "substr arguments must not be bound parameters"

    head = literal_column("substr(calls.failure_reason, 1, 600)")
    pg = str(db.query(head, func.count(Call.id)).group_by(head).statement.compile(dialect=postgresql.dialect()))
    assert "%(" not in pg.split("FROM")[0]


# ---- 1-second poller safety ------------------------------------------------------------------------------

def _poller_env(db, monkeypatch, listing_calls):
    monkeypatch.setattr(sync, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(sync, "beat", lambda name: None)

    def fake_list(bucket, prefix, recursive):
        listing_calls.append(prefix)
        return []

    monkeypatch.setattr(sync.minio_client._internal_client, "list_objects", fake_list, raising=False)


def test_poller_tick_is_skipped_while_previous_tick_still_running(db, monkeypatch):
    listed = []
    _poller_env(db, monkeypatch, listed)
    monkeypatch.setattr(sync.locks, "acquire", lambda name, ttl: False)   # lock held by a running tick
    assert sync.sync_call_records() == []
    assert listed == []                                                   # did not even touch MinIO


def test_poller_scans_today_every_tick_but_older_days_rarely(db, monkeypatch):
    listed, released = [], []
    _poller_env(db, monkeypatch, listed)
    older_ok = {"v": True}
    monkeypatch.setattr(sync.locks, "acquire",
                        lambda name, ttl: older_ok["v"] if name.endswith(":older") else True)
    monkeypatch.setattr(sync.locks, "release", lambda name: released.append(name))
    today = sync._recent_date_prefixes()[0]

    sync.sync_call_records()
    assert len(listed) == sync.LOOKBACK_DAYS                     # older window due -> all days scanned
    listed.clear()
    older_ok["v"] = False
    sync.sync_call_records()
    assert listed == [today]                                     # older days scanned recently -> today only
    assert released.count("sync_call_records") == 2              # lock always released


def test_poller_releases_lock_even_if_minio_errors(db, monkeypatch):
    released = []
    monkeypatch.setattr(sync, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(sync, "beat", lambda name: None)
    monkeypatch.setattr(sync.locks, "acquire", lambda name, ttl: True)
    monkeypatch.setattr(sync.locks, "release", lambda name: released.append(name))

    def boom(bucket, prefix, recursive):
        raise RuntimeError("minio down")

    monkeypatch.setattr(sync.minio_client._internal_client, "list_objects", boom, raising=False)
    with pytest.raises(RuntimeError):
        sync.sync_call_records()
    assert "sync_call_records" in released                       # next tick can run


def test_default_poll_is_one_second_with_expiring_ticks():
    from app.core.config import get_settings
    from app.tasks.celery_app import celery_app
    get_settings.cache_clear()
    entry = celery_app.conf.beat_schedule["sync-call-records"]
    assert entry["schedule"] == 1.0
    assert entry["options"]["expires"] >= 5                      # stale queued ticks are dropped


def test_locks_fail_open_without_redis(monkeypatch):
    from app.core import locks
    from app.core.config import get_settings
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    get_settings.cache_clear()
    assert locks.acquire("x", 5) is True                         # runs anyway rather than stalling ingestion
    locks.release("x")                                           # must not raise
    get_settings.cache_clear()


def test_every_failure_category_has_plain_english_advice(db):
    from app.core import failures
    for info in (failures.NO_SPEECH, failures.BAD_AUDIO, failures.TOOL_MISSING, failures.TIMEOUT,
                 failures.EXTERNAL, failures.CRASHED, failures.UNEXPECTED):
        assert info.advice and "Traceback" not in info.advice and len(info.advice) < 140
    seed_failures(db)
    assert all(g.advice for g in triage.summarize_failures(db).groups)
