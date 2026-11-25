"""Calls page: sorting, reviewed filter, severity breakdown, failure advice, CSV export, bulk re-run."""
import csv
import io
from datetime import timedelta

import pytest
from fastapi import HTTPException

pytest.importorskip("celery")

from app.api import calls as calls_api  # noqa: E402
from app.models.models import CallStatus  # noqa: E402
from tests.test_dashboard_calibration_api import NOW, mk, review_call  # noqa: E402


def names(res):
    return [i.original_filename for i in res.items]


def lst(db, **kw):
    return calls_api.list_calls(db=db, **kw)


@pytest.fixture()
def queued(monkeypatch):
    sent = []
    monkeypatch.setattr(calls_api.run_pipeline, "delay", lambda cid: sent.append(cid))
    return sent


def test_sort_by_qa_both_directions_empty_values_last(db):
    mk(db, "low.wav", qa=10)
    mk(db, "high.wav", qa=90)
    mk(db, "none.wav", status=CallStatus.failed)
    assert names(lst(db, sort="qa", order="desc")) == ["high.wav", "low.wav", "none.wav"]
    assert names(lst(db, sort="qa", order="asc")) == ["low.wav", "high.wav", "none.wav"]


def test_sort_by_violations_risk_duration_date(db):
    a = mk(db, "a.wav", qa=50, violations=("high", "low"), risk="low", when=NOW - timedelta(days=2))
    b = mk(db, "b.wav", qa=50, violations=(), risk="high", when=NOW)
    c = mk(db, "c.wav", qa=50, violations=("medium",), risk="medium", when=NOW - timedelta(days=1))
    a.duration_seconds, b.duration_seconds, c.duration_seconds = 300, 10, 60
    db.commit()
    assert names(lst(db, sort="violations")) == ["a.wav", "c.wav", "b.wav"]
    assert names(lst(db, sort="risk")) == ["b.wav", "c.wav", "a.wav"]
    assert names(lst(db, sort="duration", order="asc")) == ["b.wav", "c.wav", "a.wav"]
    assert names(lst(db, sort="date")) == ["b.wav", "c.wav", "a.wav"]


def test_sort_by_risk_with_risk_filter_does_not_join_twice(db):
    mk(db, "a.wav", qa=1, risk="high")
    mk(db, "b.wav", qa=1, risk="high")
    assert len(lst(db, sort="risk", risk_level="high").items) == 2


def test_unknown_sort_falls_back_to_newest_first(db):
    mk(db, "old.wav", when=NOW - timedelta(days=3))
    mk(db, "new.wav", when=NOW)
    assert lst(db, sort="; drop table calls").total == 2


def test_paging_with_sort_is_stable_and_complete(db):
    for i in range(7):
        mk(db, f"c{i}.wav", qa=50)            # all tied: id tiebreak must keep pages disjoint
    seen = []
    for page in (1, 2, 3):
        seen += names(lst(db, sort="qa", page=page, page_size=3))
    assert len(seen) == 7 and len(set(seen)) == 7


def test_reviewed_filter(db):
    done = mk(db, "done.wav", qa=40)
    mk(db, "todo.wav", qa=40)
    review_call(db, done, 40, 70)
    assert names(lst(db, reviewed=True)) == ["done.wav"]
    assert names(lst(db, reviewed=False)) == ["todo.wav"]
    item = lst(db, reviewed=True).items[0]
    assert item.manual_reviewed and item.manual_qa_score == 70


def test_severity_breakdown_and_failure_advice(db):
    mk(db, "v.wav", qa=30, violations=("high", "high", "low"))
    mk(db, "f.wav", status=CallStatus.failed)
    items = {i.original_filename: i for i in lst(db).items}
    assert items["v.wav"].violation_severities == {"high": 2, "low": 1}
    assert items["v.wav"].compliance_violation_count == 3
    failed = items["f.wav"]
    assert failed.failure_label and failed.failure_advice and failed.failure_retryable is not None
    assert items["v.wav"].failure_label is None


def test_export_csv_respects_filters_and_neutralises_formulas(db):
    mk(db, "=HYPERLINK(\"http://evil\").wav", qa=20, violations=("high",))
    mk(db, "safe.wav", qa=80)
    resp = calls_api.export_calls_csv(db=db, has_violations=True)
    assert resp.headers["content-disposition"].startswith("attachment;")
    rows = list(csv.reader(io.StringIO(resp.body.decode("utf-8-sig"))))
    assert rows[0][0] == "File" and len(rows) == 2          # header + the one flagged call
    assert rows[1][0].startswith("'=")                       # formula neutralised
    assert rows[1][6] == "1" and "1 high" in rows[1][7]


def test_bulk_reprocess_counts_each_outcome(db, queued):
    ok1, ok2 = mk(db, "1.wav"), mk(db, "2.wav", status=CallStatus.failed)
    busy = mk(db, "b.wav", status=CallStatus.processing)
    capped = mk(db, "c.wav", meta={"reprocess_count": calls_api.MAX_REPROCESS})
    res = calls_api.reprocess_many(
        calls_api.BulkReprocessIn(call_ids=[ok1.id, ok2.id, busy.id, capped.id, "nope", ok1.id]), db)
    assert res == {"queued": 2, "busy": 1, "cap": 1, "not_found": 1}
    assert sorted(queued) == sorted([ok1.id, ok2.id])


def test_bulk_reprocess_limits(db, queued):
    with pytest.raises(HTTPException) as e:
        calls_api.reprocess_many(calls_api.BulkReprocessIn(call_ids=[]), db)
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        calls_api.reprocess_many(calls_api.BulkReprocessIn(call_ids=[str(i) for i in range(calls_api.MAX_BULK + 1)]), db)
    assert e.value.status_code == 400 and queued == []
