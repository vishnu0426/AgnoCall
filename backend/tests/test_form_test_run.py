"""'Try it on a call': a dry run of the AI against one real call, with nothing saved."""
import json

import pytest

pytest.importorskip("celery")
pytest.importorskip("strawberry")

from app.core import locks  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.models.models import (  # noqa: E402
    Call, CallStatus, EvaluationResponse, FormBuilderUser, Transcript, TranscriptSegment,
)
from app.tasks import pipeline  # noqa: E402
from tests.test_form_eval_graphql import run  # noqa: E402
from tests.test_form_eval_stage import FakeLLM, SEGMENTS, form_content  # noqa: E402

TEST = """
mutation($c: String!, $f: String!, $t: String) {
  testAIFormEvaluation(call_id: $c, form_content: $f, title: $t) {
    score total_score questions answered coverage unverified_evidence model
    answers { question_id label status value evidence timestamp confidence evidence_verified reason }
  }
}"""
PICKER = "{ getCallsForFormTest(limit: 10) { id filename duration_seconds } }"
ADMIN = {"id": 1, "username": "admin", "role": "admin"}


@pytest.fixture(autouse=True)
def _env(db, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setattr(pipeline.time, "sleep", lambda *_: None)
    monkeypatch.setattr(locks, "acquire", lambda name, ttl: True)          # never touch a real Redis
    db.add(FormBuilderUser(username="admin", role="admin"))
    db.commit()
    yield
    get_settings.cache_clear()


def make_call(db, status=CallStatus.processed, with_transcript=True):
    c = Call(original_filename="t.wav", storage_path="x/t.wav", status=status, duration_seconds=8)
    db.add(c)
    db.flush()
    if with_transcript:
        t = Transcript(call_id=c.id)
        db.add(t)
        db.flush()
        for i, s in enumerate(SEGMENTS):
            db.add(TranscriptSegment(transcript_id=t.id, sequence=i, speaker_role=s["speaker_role"],
                                     start_time=s["start_time"], end_time=s["end_time"], text_masked=s["text"]))
    db.commit()
    return c


def test_dry_run_returns_answers_evidence_and_score_and_saves_nothing(db, monkeypatch):
    llm = FakeLLM()
    monkeypatch.setattr(pipeline, "get_llm_provider", lambda: llm)
    call = make_call(db)
    res = run(db, TEST, {"c": call.id, "f": json.dumps(form_content()), "t": "QA"}, user=ADMIN)
    assert res.errors is None, res.errors
    out = res.data["testAIFormEvaluation"]
    assert llm.calls == 1 and out["model"] == "fake-llm"
    assert out["questions"] == 2 and out["answered"] == 2 and out["coverage"] == 1.0
    by_id = {a["question_id"]: a for a in out["answers"]}
    assert by_id["greet"]["value"] == "Yes" and by_id["greet"]["evidence_verified"] is True
    assert by_id["emp"]["evidence_verified"] is False and out["unverified_evidence"] == 1   # invented quote is flagged
    assert out["score"] is not None and out["total_score"] == 100
    assert db.query(EvaluationResponse).count() == 0                                        # nothing stored


def test_dry_run_uses_the_unsaved_content_it_is_given(db, monkeypatch):
    monkeypatch.setattr(pipeline, "get_llm_provider", lambda: FakeLLM())
    call = make_call(db)
    content = form_content()
    content["fields"] = content["fields"][:1]                                               # editor has one question
    out = run(db, TEST, {"c": call.id, "f": json.dumps(content)}, user=ADMIN).data["testAIFormEvaluation"]
    assert out["questions"] == 1


@pytest.mark.parametrize("setup,message", [
    (lambda db: make_call(db, status=CallStatus.processing), "not finished"),
    (lambda db: make_call(db, with_transcript=False), "no transcript"),
])
def test_dry_run_rejects_unusable_calls(db, monkeypatch, setup, message):
    llm = FakeLLM()
    monkeypatch.setattr(pipeline, "get_llm_provider", lambda: llm)
    call = setup(db)
    res = run(db, TEST, {"c": call.id, "f": json.dumps(form_content())}, user=ADMIN)
    assert res.errors and message in str(res.errors[0]) and llm.calls == 0                  # no LLM spend


def test_dry_run_unknown_or_malformed_call_and_bad_form(db, monkeypatch):
    llm = FakeLLM()
    monkeypatch.setattr(pipeline, "get_llm_provider", lambda: llm)
    call = make_call(db)
    assert run(db, TEST, {"c": "not-a-uuid", "f": json.dumps(form_content())}, user=ADMIN).errors
    assert run(db, TEST, {"c": call.id, "f": "not json"}, user=ADMIN).errors
    nothing = json.dumps({"fields": [{"id": "n", "type": "text", "label": "Notes"}]})      # AI has nothing to answer
    res = run(db, TEST, {"c": call.id, "f": nothing}, user=ADMIN)
    assert res.errors and "no fields the AI can answer" in str(res.errors[0]) and llm.calls == 0


def test_llm_outage_is_reported_in_plain_words(db, monkeypatch):
    monkeypatch.setattr(pipeline, "get_llm_provider", lambda: FakeLLM("raise"))
    call = make_call(db)
    res = run(db, TEST, {"c": call.id, "f": json.dumps(form_content())}, user=ADMIN)
    assert res.errors and "did not respond" in str(res.errors[0])


def test_permissions_kill_switch_and_rate_limit(db, monkeypatch):
    llm = FakeLLM()
    monkeypatch.setattr(pipeline, "get_llm_provider", lambda: llm)
    call = make_call(db)
    args = {"c": call.id, "f": json.dumps(form_content())}
    agent = {"id": 2, "username": "bob", "role": "agent"}
    assert run(db, TEST, args, user=agent).errors                                           # not an admin
    monkeypatch.setattr(locks, "acquire", lambda name, ttl: False)
    res = run(db, TEST, args, user=ADMIN)
    assert res.errors and "wait a few seconds" in str(res.errors[0])                        # rate limited
    monkeypatch.setattr(locks, "acquire", lambda name, ttl: True)
    monkeypatch.setenv("AI_FORM_EVAL_ENABLED", "false")
    get_settings.cache_clear()
    assert "disabled" in str(run(db, TEST, args, user=ADMIN).errors[0])
    assert llm.calls == 0


def test_call_picker_lists_only_processed_calls_with_a_transcript(db):
    good = make_call(db)
    make_call(db, status=CallStatus.failed)
    make_call(db, with_transcript=False)
    rows = run(db, PICKER).data["getCallsForFormTest"]
    assert [r["id"] for r in rows] == [good.id]
