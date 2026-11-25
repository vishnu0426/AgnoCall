"""Run-on-call + backfill: selection, idempotency, dry run, locking, permissions."""
import json
from datetime import datetime

import pytest

pytest.importorskip("celery")
pytest.importorskip("strawberry")

from app.api.forms_graphql import GraphQLContext, schema  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.models.models import (  # noqa: E402
    Call, CallStatus, EvaluationForm, EvaluationResponse, FormBuilderUser, Transcript, TranscriptSegment,
)
from app.tasks import pipeline  # noqa: E402
from tests.test_form_eval_stage import FakeLLM, form_content  # noqa: E402


@pytest.fixture(autouse=True)
def _env(db, monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda *_: None)
    monkeypatch.setattr(pipeline, "get_llm_provider", lambda: FakeLLM())
    get_settings.cache_clear()
    db.add(FormBuilderUser(username="admin", role="admin"))
    db.commit()
    yield
    get_settings.cache_clear()


def make_call(db, day, status=CallStatus.processed, with_transcript=True):
    c = Call(original_filename=f"{day}.wav", storage_path=f"x/{day}.wav", status=status,
             call_date=datetime(2026, 3, day))
    db.add(c)
    db.flush()
    if with_transcript:
        t = Transcript(call_id=c.id, pii_masked=True, full_text_masked="x")
        db.add(t)
        db.flush()
        db.add(TranscriptSegment(transcript_id=t.id, speaker_role="agent", sequence=0, start_time=0.0,
                                 end_time=4.0, text_masked="Thank you for calling Acme my name is Priya"))
    db.commit()
    return c


def make_form(db, enabled=True, form_id="qa1"):
    f = EvaluationForm(form_id=form_id, title=form_id, form_content=form_content(), created_by=1,
                       ai_enabled=enabled, version=1)
    db.add(f)
    db.commit()
    return f


# ---- evaluate_existing_call ------------------------------------------------

def test_evaluates_a_processed_call_from_stored_transcript(db):
    make_form(db)
    c = make_call(db, 1)
    assert pipeline.evaluate_existing_call(db, c.id, "qa1") == "ok"
    r = db.query(EvaluationResponse).one()
    assert (r.source, r.call_id, r.form_id) == ("ai", c.id, "qa1")


@pytest.mark.parametrize("status,transcript,expected", [
    (CallStatus.processing, True, "not_processed"),
    (CallStatus.failed, True, "not_processed"),
    (CallStatus.processed, False, "no_transcript"),
])
def test_refuses_calls_that_cannot_be_evaluated(db, status, transcript, expected):
    make_form(db)
    c = make_call(db, 1, status=status, with_transcript=transcript)
    assert pipeline.evaluate_existing_call(db, c.id, "qa1") == expected
    assert db.query(EvaluationResponse).count() == 0


def test_unknown_call_and_disabled_form(db):
    assert pipeline.evaluate_existing_call(db, "nope", "qa1") == "call_not_found"
    make_form(db, enabled=False)
    c = make_call(db, 1)
    pipeline.evaluate_existing_call(db, c.id, "qa1")        # a disabled form is never evaluated
    assert db.query(EvaluationResponse).count() == 0


# ---- selection ---------------------------------------------------------------

def test_selection_skips_done_unprocessed_and_out_of_range(db):
    make_form(db)
    ids = {d: make_call(db, d).id for d in (1, 2, 3, 4, 5)}
    make_call(db, 6, status=CallStatus.failed)
    db.add(EvaluationResponse(form_id="qa1", call_id=ids[2], source="ai", responses={}))     # already done
    db.add(EvaluationResponse(form_id="qa1", call_id=ids[3], source="human", responses={}))  # human != AI
    db.commit()

    sel = pipeline.select_backfill_calls(db, "qa1", datetime(2026, 3, 1), datetime(2026, 3, 4, 23), 100)
    assert sel["call_ids"] == [ids[1], ids[3], ids[4]]       # oldest first; 2 done, 5 out of range
    assert sel["truncated"] is False


def test_selection_respects_limit_and_reports_truncation(db):
    make_form(db)
    for d in range(1, 6):
        make_call(db, d)
    sel = pipeline.select_backfill_calls(db, "qa1", limit=3)
    assert len(sel["call_ids"]) == 3 and sel["truncated"] is True


def test_selection_is_per_form(db):
    make_form(db, form_id="a")
    make_form(db, form_id="b")
    c = make_call(db, 1)
    db.add(EvaluationResponse(form_id="a", call_id=c.id, source="ai", responses={}))
    db.commit()
    assert pipeline.select_backfill_calls(db, "a")["call_ids"] == []
    assert pipeline.select_backfill_calls(db, "b")["call_ids"] == [c.id]


# ---- backfill task: fan-out + lock ------------------------------------------

def test_backfill_task_queues_each_call_once_and_honours_inflight_lock(db, monkeypatch):
    make_form(db)
    ids = [make_call(db, d).id for d in (1, 2, 3)]
    sent, taken = [], {ids[1]}
    monkeypatch.setattr(pipeline, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(pipeline, "claim_eval", lambda cid, fid: cid not in taken)
    monkeypatch.setattr(pipeline.run_form_evaluation, "delay", lambda cid, fid: sent.append(cid))
    out = pipeline.backfill_form_evaluation("qa1")
    assert sent == [ids[0], ids[2]]
    assert out == {"queued": 2, "already_inflight": 1, "truncated": False}


# ---- GraphQL --------------------------------------------------------------------

BACKFILL = """mutation($f: String!, $d1: String, $d2: String, $dry: Boolean) {
  backfillAIFormEvaluation(form_id: $f, date_from: $d1, date_to: $d2, dry_run: $dry) {
    eligible truncated queued max_calls } }"""
RUN = """mutation($c: String!, $f: String!) { runAIFormEvaluation(call_id: $c, form_id: $f) { status message } }"""


def gql(db, q, v, user=None):
    return schema.execute_sync(q, variable_values=v, context_value=GraphQLContext(db=db, user=user))


@pytest.fixture()
def sent_tasks(monkeypatch):
    from app.tasks.celery_app import celery_app
    sent = []
    monkeypatch.setattr(celery_app, "send_task", lambda name, args=None, **kw: sent.append((name, args)))
    monkeypatch.setattr(pipeline, "claim_eval", lambda *a: True)
    return sent


def test_backfill_defaults_to_dry_run_and_queues_only_when_confirmed(db, sent_tasks):
    make_form(db)
    for d in (1, 2, 3):
        make_call(db, d)
    dry = gql(db, BACKFILL, {"f": "qa1"})
    assert dry.errors is None
    assert dry.data["backfillAIFormEvaluation"] == {
        "eligible": 3, "truncated": False, "queued": False, "max_calls": 1000}
    assert sent_tasks == []                                   # dry run spends nothing

    real = gql(db, BACKFILL, {"f": "qa1", "d1": "2026-03-02", "dry": False})
    assert real.data["backfillAIFormEvaluation"]["eligible"] == 2
    assert real.data["backfillAIFormEvaluation"]["queued"] is True
    assert sent_tasks == [("app.tasks.pipeline.backfill_form_evaluation", ["qa1", "2026-03-02", None])]


def test_backfill_validation_and_permissions(db, sent_tasks):
    make_form(db, enabled=False, form_id="off")
    make_form(db)
    assert "not enabled" in gql(db, BACKFILL, {"f": "off"}).errors[0].message
    assert "ISO-8601" in gql(db, BACKFILL, {"f": "qa1", "d1": "yesterday"}).errors[0].message
    assert "must not be after" in gql(db, BACKFILL, {"f": "qa1", "d1": "2026-03-05", "d2": "2026-03-01"}).errors[0].message
    agent = {"id": 9, "username": "bob", "role": "agent"}
    assert "administrators" in gql(db, BACKFILL, {"f": "qa1", "dry": False}, user=agent).errors[0].message
    assert sent_tasks == []


def test_run_mutation_queues_and_dedupes(db, sent_tasks, monkeypatch):
    make_form(db)
    c = make_call(db, 1)
    r = gql(db, RUN, {"c": c.id, "f": "qa1"})
    assert r.data["runAIFormEvaluation"]["status"] == "queued"
    assert sent_tasks == [("app.tasks.pipeline.run_form_evaluation", [c.id, "qa1"])]

    monkeypatch.setattr(pipeline, "claim_eval", lambda *a: False)
    again = gql(db, RUN, {"c": c.id, "f": "qa1"})
    assert again.data["runAIFormEvaluation"]["status"] == "already_queued"
    assert len(sent_tasks) == 1


def test_run_mutation_rejects_bad_targets(db, sent_tasks):
    make_form(db)
    busy = make_call(db, 1, status=CallStatus.processing)
    assert "not finished" in gql(db, RUN, {"c": busy.id, "f": "qa1"}).errors[0].message
    assert "Call not found" in gql(db, RUN, {"c": "missing", "f": "qa1"}).errors[0].message
    assert "not enabled" in gql(db, RUN, {"c": busy.id, "f": "ghost"}).errors[0].message
    assert sent_tasks == []
