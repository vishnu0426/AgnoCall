"""
Integration tests for pipeline._stage_form_evaluation against an in-memory DB
with a fake LLM — the real stage code, real ORM, no network.
"""
import pytest

pytest.importorskip("celery")

from app.core.config import get_settings  # noqa: E402
from app.models.models import (  # noqa: E402
    Call, EvaluationForm, EvaluationResponse, FormBuilderUser, JobStage, JobStatus, ProcessingJob,
)
from app.tasks import pipeline  # noqa: E402

SEGMENTS = [
    {"speaker_role": "agent", "start_time": 0.0, "end_time": 4.0,
     "text": "Thank you for calling Acme my name is Priya how can I help"},
    {"speaker_role": "customer", "start_time": 4.5, "end_time": 8.0,
     "text": "I want to cancel my subscription please"},
]


def form_content():
    return {"hasScoring": True, "total_score": 100, "fields": [
        {"id": "greet", "type": "yesno", "label": "Greeted the customer", "yes_score": 10,
         "no_score": 0, "max_score": 60, "ai_instruction": "Agent greets and names themselves"},
        {"id": "emp", "type": "rating", "label": "Empathy", "maxStars": 5,
         "star_scores": {"1": 2, "2": 4, "3": 6, "4": 8, "5": 10}, "max_score": 40},
    ]}


class FakeLLM:
    model_name = "fake-llm"

    def __init__(self, behaviour="ok"):
        self.behaviour = behaviour
        self.calls = 0

    def generate_json(self, system, prompt):
        self.calls += 1
        if self.behaviour == "raise":
            raise RuntimeError("provider down")
        if self.behaviour == "garbage":
            return {"nonsense": True}
        return {"answers": [
            {"field_id": "greet", "value": "Yes", "applicable": True,
             "evidence": "Thank you for calling Acme my name is Priya", "timestamp": 0.0, "confidence": 0.95},
            {"field_id": "emp", "value": 4, "applicable": True,
             "evidence": "invented quote that never happened in the call", "timestamp": 5.0, "confidence": 0.6},
        ]}


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(pipeline.time, "sleep", lambda *_: None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def call(db):
    c = Call(original_filename="a.wav", storage_path="x/a.wav")
    db.add(c)
    db.add(FormBuilderUser(username="admin", role="admin"))
    db.commit()
    return c


def add_form(db, form_id, enabled=True, content=None, created_offset=0):
    from datetime import datetime, timedelta
    f = EvaluationForm(
        form_id=form_id, title=f"Form {form_id}", form_content=content or form_content(),
        created_by=1, ai_enabled=enabled, version=3,
        created_at=datetime(2026, 1, 1) + timedelta(minutes=created_offset),
    )
    db.add(f)
    db.commit()
    return f


def use_llm(monkeypatch, llm):
    monkeypatch.setattr(pipeline, "get_llm_provider", lambda: llm)


def job(db, call_id):
    return db.query(ProcessingJob).filter_by(call_id=call_id, stage=JobStage.form_eval).first()


def test_no_enabled_forms_is_a_complete_noop(db, call, monkeypatch):
    llm = FakeLLM()
    use_llm(monkeypatch, llm)
    add_form(db, "off", enabled=False)
    pipeline._stage_form_evaluation(db, call, SEGMENTS)
    assert llm.calls == 0                                   # no LLM spend
    assert job(db, call.id) is None                         # no job row
    assert db.query(EvaluationResponse).count() == 0


def test_enabled_form_is_scored_and_audited(db, call, monkeypatch):
    llm = FakeLLM()
    use_llm(monkeypatch, llm)
    add_form(db, "qa1")
    pipeline._stage_form_evaluation(db, call, SEGMENTS)

    r = db.query(EvaluationResponse).one()
    assert (r.source, r.form_id, r.call_id, r.form_version) == ("ai", "qa1", call.id, 3)
    assert r.responses == {"greet": "Yes", "emp": 4}
    # greet 60/60 + empathy 8/10 * 40 = 92 on a 100 scale
    assert r.score == pytest.approx(92.0)
    meta = r.evidence["_meta"]
    assert meta["model"] == "fake-llm" and meta["coverage"] == 1.0
    assert r.evidence["greet"]["evidence_verified"] is True
    assert r.evidence["emp"]["evidence_verified"] is False   # fabricated quote flagged
    assert meta["unverified_evidence"] == 1
    assert job(db, call.id).status == JobStatus.succeeded


def test_rerun_upserts_one_row_and_keeps_human_rows(db, call, monkeypatch):
    use_llm(monkeypatch, FakeLLM())
    add_form(db, "qa1")
    db.add(EvaluationResponse(form_id="qa1", call_id=call.id, source="human", score=50.0, responses={}))
    db.commit()
    pipeline._stage_form_evaluation(db, call, SEGMENTS)
    pipeline._stage_form_evaluation(db, call, SEGMENTS)
    sources = sorted(r.source for r in db.query(EvaluationResponse).all())
    assert sources == ["ai", "human"]

    pipeline._clear_previous_results(db, call.id)           # what a reprocess does
    assert [r.source for r in db.query(EvaluationResponse).all()] == ["human"]


def test_llm_failure_never_raises_and_is_recorded(db, call, monkeypatch):
    use_llm(monkeypatch, FakeLLM("raise"))
    add_form(db, "qa1")
    pipeline._stage_form_evaluation(db, call, SEGMENTS)     # must not raise
    j = job(db, call.id)
    assert j.status == JobStatus.failed and "provider down" in j.error_message
    assert db.query(EvaluationResponse).count() == 0


def test_llm_is_retried_before_giving_up(db, call, monkeypatch):
    llm = FakeLLM("raise")
    use_llm(monkeypatch, llm)
    add_form(db, "qa1")
    pipeline._stage_form_evaluation(db, call, SEGMENTS)
    assert llm.calls == get_settings().ai_form_eval_llm_attempts


def test_garbage_model_output_is_rejected_not_stored(db, call, monkeypatch):
    use_llm(monkeypatch, FakeLLM("garbage"))
    add_form(db, "qa1")
    pipeline._stage_form_evaluation(db, call, SEGMENTS)
    assert job(db, call.id).status == JobStatus.failed
    assert db.query(EvaluationResponse).count() == 0


def test_one_bad_form_does_not_block_the_others(db, call, monkeypatch):
    use_llm(monkeypatch, FakeLLM())
    add_form(db, "bad", content={"hasScoring": True, "fields": [{"id": "x", "type": "signature"}]},
             created_offset=0)
    add_form(db, "good", created_offset=1)
    pipeline._stage_form_evaluation(db, call, SEGMENTS)
    assert [r.form_id for r in db.query(EvaluationResponse).all()] == ["good"]
    j = job(db, call.id)
    assert j.status == JobStatus.failed and "bad" in j.error_message


def test_cap_limits_llm_calls_oldest_first(db, call, monkeypatch):
    monkeypatch.setenv("AI_FORM_EVAL_MAX_ENABLED_FORMS", "2")
    get_settings.cache_clear()
    llm = FakeLLM()
    use_llm(monkeypatch, llm)
    for i in range(4):
        add_form(db, f"f{i}", created_offset=i)
    pipeline._stage_form_evaluation(db, call, SEGMENTS)
    assert llm.calls == 2
    assert sorted(r.form_id for r in db.query(EvaluationResponse).all()) == ["f0", "f1"]
    assert "over the limit" in job(db, call.id).error_message


def test_global_kill_switch(db, call, monkeypatch):
    monkeypatch.setenv("AI_FORM_EVAL_ENABLED", "false")
    get_settings.cache_clear()
    llm = FakeLLM()
    use_llm(monkeypatch, llm)
    add_form(db, "qa1")
    pipeline._stage_form_evaluation(db, call, SEGMENTS)
    assert llm.calls == 0 and db.query(EvaluationResponse).count() == 0
