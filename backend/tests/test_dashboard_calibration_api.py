"""Calibration API, dashboard filters/trends, review queue, agent inference, reprocess."""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

pytest.importorskip("celery")

from app.api import agents as agents_api  # noqa: E402
from app.api import calibration, calls as calls_api, dashboard, review  # noqa: E402
from app.core.agent_resolution import agent_for_upload, apply_filename_metadata  # noqa: E402
from app.core.indexes import ensure_indexes  # noqa: E402
from app.models.models import (  # noqa: E402
    Agent, Call, CallStatus, ComplianceViolation, CustomerAnalytics, EvaluationForm, EvaluationResponse,
    ManualQACriteriaScore, ManualQAReview, QACriteriaScore, QAEvaluation,
)
from app.schemas.schemas import AgentUpdate  # noqa: E402
from app.tasks import rubric  # noqa: E402
from app.tasks.call_ingest import get_or_create_call_from_key  # noqa: E402

NOW = datetime.utcnow()


def mk(db, name="c.wav", status=CallStatus.processed, qa=None, when=None, agent=None, risk=None,
       violations=(), conf=None, meta=None):
    c = Call(original_filename=name, storage_path=f"x/{name}", status=status, call_date=when or NOW,
             agent_id=agent.id if agent else None, call_metadata=meta or {})
    db.add(c)
    db.flush()
    if qa is not None:
        ev = QAEvaluation(call_id=c.id, overall_score=qa)
        db.add(ev)
        db.flush()
        if conf is not None:
            db.add(QACriteriaScore(qa_evaluation_id=ev.id, criterion="greeting", score=qa, confidence=conf))
    if risk:
        db.add(CustomerAnalytics(call_id=c.id, risk_level=risk))
    for sev in violations:
        db.add(ComplianceViolation(call_id=c.id, rule_code="R1", category="x", severity=sev))
    db.commit()
    return c


def review_call(db, call, ai, human, crit_ai=None, crit_human=None, status="completed"):
    r = ManualQAReview(call_id=call.id, reviewer_name="Rev", status=status, overall_score=human)
    db.add(r)
    db.flush()
    db.add(ManualQACriteriaScore(review_id=r.id, criterion=crit_ai or "greeting",
                                 ai_score=ai, manual_score=crit_human if crit_human is not None else human))
    db.commit()


# ---- calibration summary -------------------------------------------------------------

def test_harsh_ai_is_detected_and_explained(db):
    for i in range(6):
        c = mk(db, f"r{i}.wav", qa=15 + i)               # AI marks ~15-20
        review_call(db, c, 15 + i, 60 + i)               # humans mark ~60-65
    s = calibration.calibration_summary(db)
    assert s.reviewed_calls == 6 and s.verdict_level == "harsh"
    assert s.bias > 40 and s.agreement_percent == 0.0
    assert "lower than your reviewers" in s.verdict_text
    assert s.human_average_qa > s.ai_average_qa
    assert s.by_criterion[0].criterion == "greeting" and s.by_criterion[0].bias > 40


def test_summary_with_no_reviews_is_safe(db):
    mk(db, qa=50)
    s = calibration.calibration_summary(db)
    assert s.reviewed_calls == 0 and s.verdict_level == "not_enough_data" and s.bias is None
    assert s.compliance.reviewed == 0 and s.compliance.unreviewed_flags == 0


def test_drafts_do_not_count_and_rubric_version_is_tracked(db):
    a = mk(db, "a.wav", qa=20, meta={"rubric_version": rubric.RUBRIC_VERSION})
    b = mk(db, "b.wav", qa=20, meta={"rubric_version": "qa-rubric/v1"})
    d = mk(db, "d.wav", qa=20)
    review_call(db, a, 20, 70)
    review_call(db, b, 20, 70)
    review_call(db, d, 20, 70, status="draft")
    s = calibration.calibration_summary(db)
    assert s.reviewed_calls == 2 and s.reviewed_on_current_rubric == 1


def test_compliance_precision_by_rule(db):
    c = mk(db, "x.wav", qa=50, violations=["high", "high", "low"])
    vs = db.query(ComplianceViolation).filter_by(call_id=c.id).all()
    calibration.review_compliance_flag(vs[0].id, calibration.ComplianceReviewIn(outcome="confirmed"), db)
    calibration.review_compliance_flag(vs[1].id, calibration.ComplianceReviewIn(outcome="rejected"), db)
    s = calibration.calibration_summary(db).compliance
    assert (s.reviewed, s.confirmed, s.rejected, s.precision_percent, s.unreviewed_flags) == (2, 1, 1, 50.0, 1)
    assert s.by_rule[0].rule_code == "R1"


def test_compliance_review_validation_and_clearing(db):
    c = mk(db, qa=50, violations=["low"])
    v = db.query(ComplianceViolation).one()
    with pytest.raises(HTTPException) as e:
        calibration.review_compliance_flag(v.id, calibration.ComplianceReviewIn(outcome="maybe"), db)
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        calibration.review_compliance_flag("nope", calibration.ComplianceReviewIn(outcome="confirmed"), db)
    assert e.value.status_code == 404
    calibration.review_compliance_flag(v.id, calibration.ComplianceReviewIn(outcome="confirmed"), db)
    out = calibration.review_compliance_flag(v.id, calibration.ComplianceReviewIn(outcome=None), db)
    assert out["reviewed"] is False and out["review_outcome"] is None


def test_review_sample_excludes_reviewed_and_spans_range(db):
    done = mk(db, "done.wav", qa=5)
    review_call(db, done, 5, 50)
    for i in range(30):
        mk(db, f"s{i}.wav", qa=float(i * 3), violations=["low"] if i % 5 == 0 else ())
    out = calibration.review_sample(n=10, db=db)
    ids = {s.call_id for s in out}
    assert done.id not in ids and len(out) == 10
    qas = sorted(s.ai_qa for s in out)
    assert qas[0] <= 15 and qas[-1] >= 70
    assert any("compliance" in s.reason for s in out)


# ---- reprocess ----------------------------------------------------------------------------

@pytest.fixture()
def queued(monkeypatch):
    sent = []
    monkeypatch.setattr(calls_api.run_pipeline, "delay", lambda cid: sent.append(cid))
    return sent


def test_reprocess_queues_once_and_keeps_manual_review(db, queued):
    c = mk(db, qa=20)
    review_call(db, c, 20, 70)
    assert calls_api.reprocess_call(c.id, db)["status"] == "queued"
    assert queued == [c.id]
    db.refresh(c)
    assert c.status == CallStatus.validating and c.call_metadata["reprocess_count"] == 1
    assert db.query(ManualQAReview).count() == 1                       # human work preserved
    with pytest.raises(HTTPException) as e:                             # already in flight
        calls_api.reprocess_call(c.id, db)
    assert e.value.status_code == 409 and queued == [c.id]


def test_reprocess_rejects_unknown_busy_and_capped(db, queued):
    with pytest.raises(HTTPException) as e:
        calls_api.reprocess_call("missing", db)
    assert e.value.status_code == 404
    busy = mk(db, "b.wav", status=CallStatus.processing)
    with pytest.raises(HTTPException) as e:
        calls_api.reprocess_call(busy.id, db)
    assert e.value.status_code == 409
    capped = mk(db, "c.wav", meta={"reprocess_count": calls_api.MAX_REPROCESS})
    with pytest.raises(HTTPException) as e:
        calls_api.reprocess_call(capped.id, db)
    assert e.value.status_code == 409 and queued == []


# ---- calls list filters --------------------------------------------------------------------------

def test_call_list_filters(db):
    ag = Agent(name="Asha", external_agent_id="1001")
    db.add(ag)
    db.commit()
    a = mk(db, "alpha_100%.wav", agent=ag, violations=["low"], when=NOW)
    b = mk(db, "beta.wav", when=NOW - timedelta(days=40))
    c = mk(db, "gamma.wav", when=NOW)
    names = lambda **kw: sorted(i.original_filename for i in calls_api.list_calls(db=db, **kw).items)  # noqa: E731
    assert names(agent_id=ag.id) == ["alpha_100%.wav"]
    assert names(days=7) == ["alpha_100%.wav", "gamma.wav"]
    assert names(has_violations=True) == ["alpha_100%.wav"]
    assert names(has_violations=False) == ["beta.wav", "gamma.wav"]
    assert names(search="BETA") == ["beta.wav"]
    assert names(search="100%") == ["alpha_100%.wav"]            # % is literal, not a wildcard
    assert names(search="%") == ["alpha_100%.wav"]
    assert names(search="a_p") == []                             # _ is literal, not "any character"


# ---- dashboard filters, trend, targets -------------------------------------------------------------

def test_dashboard_period_agent_trend_and_targets(db):
    ag = Agent(name="Asha")
    db.add(ag)
    db.commit()
    mk(db, "now1.wav", qa=80, when=NOW - timedelta(days=1), agent=ag)
    mk(db, "now2.wav", qa=60, when=NOW - timedelta(days=2))
    mk(db, "old.wav", qa=20, when=NOW - timedelta(days=10))          # previous 7-day window
    mk(db, "ancient.wav", qa=10, when=NOW - timedelta(days=60))      # outside both
    s = dashboard.dashboard_summary(db=db, days=7)
    assert (s.total_calls, s.average_qa, s.period_days) == (2, 70.0, 7)
    assert s.previous.total_calls == 1 and s.previous.average_qa == 20.0
    assert s.qa_target == 80.0 and s.compliance_target == 95.0
    assert len(s.qa_trend) == 2 and all(p.calls == 1 for p in s.qa_trend)
    one = dashboard.dashboard_summary(db=db, days=7, agent_id=ag.id)
    assert one.total_calls == 1 and one.average_qa == 80.0 and one.agent_id == ag.id
    alltime = dashboard.dashboard_summary(db=db)
    assert alltime.total_calls == 4 and alltime.previous is None and alltime.period_days is None


def test_dashboard_days_are_clamped(db):
    assert dashboard.normalise_days(0) is None and dashboard.normalise_days(-3) is None
    assert dashboard.normalise_days(99999) == dashboard.MAX_DAYS and dashboard.normalise_days(30) == 30


def test_ai_evaluation_card_counts_and_agreement(db):
    f = EvaluationForm(form_id="qa", title="QA", form_content={"total_score": 100}, created_by=1,
                       ai_enabled=True, version=2)
    db.add(f)
    off = EvaluationForm(form_id="off", title="Off", form_content={}, created_by=1, ai_enabled=False)
    db.add(off)
    c1, c2 = mk(db, "1.wav"), mk(db, "2.wav")
    for cid, ai, human in ((c1.id, 80.0, 85.0), (c2.id, 80.0, 40.0)):
        db.add(EvaluationResponse(form_id="qa", call_id=cid, source="ai", score=ai, responses={}))
    db.add(EvaluationResponse(form_id="qa", call_id=c1.id, source="human", score=85.0, responses={}))
    db.add(EvaluationResponse(form_id="qa", call_id=c2.id, source="human", score=40.0, responses={}))
    db.commit()
    out = dashboard.ai_evaluation_summary(db)
    assert out.enabled_forms == 1
    it = out.items[0]
    assert (it.scored_calls, it.average_score, it.compared_with_human, it.agreement_percent, it.version) \
        == (2, 80.0, 2, 50.0, 2)


# ---- needs-review queue ---------------------------------------------------------------------------------

def test_review_queue_ranks_reasons_and_skips_reviewed(db):
    urgent = mk(db, "urgent.wav", qa=30, risk="high", violations=["critical", "high"])
    risky = mk(db, "risky.wav", qa=50, risk="high")
    flagged = mk(db, "flagged.wav", qa=50, violations=["high"])
    unsure = mk(db, "unsure.wav", qa=50, conf=0.3)
    calm = mk(db, "calm.wav", qa=90, risk="low", violations=["low"], conf=0.95)       # nothing qualifying
    done = mk(db, "done.wav", qa=10, risk="high")
    review_call(db, done, 10, 60)
    q = review.review_queue(db=db)
    order = [i.filename for i in q.items]
    assert order[0] == "urgent.wav" and set(order) == {"urgent.wav", "risky.wav", "flagged.wav", "unsure.wav"}
    assert "done.wav" not in order and "calm.wav" not in order
    assert q.total == 4
    top = q.items[0]
    assert "High customer risk" in top.reasons and any("serious compliance" in r for r in top.reasons)
    assert review.review_queue(db=db, limit=2).items.__len__() == 2


def test_reviewed_flags_leave_the_queue(db):
    c = mk(db, "f.wav", qa=50, violations=["high"])
    v = db.query(ComplianceViolation).one()
    assert review.review_queue(db=db).total == 1
    calibration.review_compliance_flag(v.id, calibration.ComplianceReviewIn(outcome="rejected"), db)
    assert review.review_queue(db=db).total == 0


# ---- agent inference ------------------------------------------------------------------------------------------

def test_filename_fills_agent_and_customer_but_never_overrides(db):
    c = mk(db, "call__919551818896_1002_agnoshin.com.wav")
    assert apply_filename_metadata(db, c) is True
    db.commit()
    agent = db.query(Agent).filter_by(id=c.agent_id).one()
    assert (agent.external_agent_id, agent.name) == ("1002", "Extension 1002")
    assert c.call_metadata["customer_number"] == "919551818896"
    # a second call under the same extension reuses the same agent
    c2 = mk(db, "call__911111111111_1002_agnoshin.com.wav")
    apply_filename_metadata(db, c2)
    db.commit()
    assert c2.agent_id == agent.id and db.query(Agent).count() == 1
    # an agent set explicitly is never replaced
    manual = Agent(name="Manual")
    db.add(manual)
    db.commit()
    c3 = mk(db, "call__922222222222_1003_agnoshin.com.wav", agent=manual)
    apply_filename_metadata(db, c3)
    assert c3.agent_id == manual.id and db.query(Agent).filter_by(external_agent_id="1003").count() == 0


def test_ingestion_assigns_agent_when_it_creates_the_call(db):
    key = sync_key = "call-records/2026/11/25/aaaaaaaa-1111-2222-3333-444444444444-170-call__918838559627_1006_x.wav"
    call = get_or_create_call_from_key(db, sync_key)
    assert call.agent_id is not None
    assert db.query(Agent).filter_by(external_agent_id="1006").count() == 1


def test_upload_by_name_does_not_grab_an_unrelated_agent(db):
    other = Agent(name="Someone Else")                      # external_agent_id is NULL
    db.add(other)
    db.commit()
    got = agent_for_upload(db, None, "Priya")
    assert got.name == "Priya" and got.id != other.id       # used to resolve to `other`
    assert agent_for_upload(db, None, "Priya").id == got.id  # same name -> same agent
    assert agent_for_upload(db, None, None) is None and agent_for_upload(db, "", "  ") is None
    assert agent_for_upload(db, "77", None).external_agent_id == "77"


def test_backfill_assigns_existing_calls_and_is_idempotent(db):
    mk(db, "call__919551818896_1002_agnoshin.com.wav")
    mk(db, "call__919551818897_1002_agnoshin.com.wav")
    mk(db, "call_1004_1005_agnoshin.com.wav")
    mk(db, "719001004809577.wav")                                         # no pattern
    r = agents_api.backfill_agents_from_filenames(db)
    assert (r.assigned, r.agents_created, r.unrecognised) == (3, 2, 1)
    again = agents_api.backfill_agents_from_filenames(db)
    assert (again.assigned, again.agents_created) == (0, 0) and again.unrecognised == 1


def test_rename_agent_validation_and_options(db):
    a = Agent(name="Extension 1001", external_agent_id="1001")
    db.add(a)
    db.commit()
    assert agents_api.update_agent(a.id, AgentUpdate(name="  Asha Rao "), db).name == "Asha Rao"
    for bad in ("", "   ", "x" * 121):
        with pytest.raises(HTTPException) as e:
            agents_api.update_agent(a.id, AgentUpdate(name=bad), db)
        assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        agents_api.update_agent("missing", AgentUpdate(name="X"), db)
    assert e.value.status_code == 404
    assert [o.name for o in agents_api.agent_options(db)] == ["Asha Rao"]


def test_unique_agent_extension_index_blocks_duplicates(db):
    from sqlalchemy.exc import IntegrityError
    ensure_indexes(db.connection())
    db.add(Agent(name="A", external_agent_id="1001"))
    db.commit()
    db.add(Agent(name="B", external_agent_id="1001"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add_all([Agent(name="C"), Agent(name="D")])            # many NULLs are fine
    db.commit()


# ---- invalid ids: clean 400/404, never a Postgres 500 -------------------------------------------------

@pytest.mark.parametrize("bad", ["nope", "123", "", "not-a-uuid-at-all"])
def test_invalid_ids_are_rejected_cleanly(db, queued, bad):
    from app.api import triage
    from app.core.ids import is_uuid
    from app.schemas.schemas import RetryRequest
    assert not is_uuid(bad)

    def code(fn, *a, **kw):
        with pytest.raises(HTTPException) as e:
            fn(*a, **kw)
        return e.value.status_code

    assert code(calls_api.list_calls, db=db, agent_id=bad or "x") == 400
    assert code(dashboard.dashboard_summary, db=db, agent_id=bad or "x") == 400
    assert code(review.review_queue, db=db, agent_id=bad or "x") == 400
    assert code(calls_api.reprocess_call, bad, db) == 404
    assert code(calls_api.get_call, bad, db) == 404
    assert code(calibration.review_compliance_flag, bad,
                calibration.ComplianceReviewIn(outcome="confirmed"), db) == 404
    assert code(agents_api.update_agent, bad, AgentUpdate(name="X"), db) == 404
    assert code(agents_api.get_agent, bad, db) == 404
    assert code(triage.retry_failed, RetryRequest(call_ids=[bad]), db) == 404


def test_valid_uuid_shapes_pass():
    from app.core.ids import is_uuid
    assert is_uuid("3bb2d08c-dc02-453e-964e-2c8bed190215") and is_uuid("3bb2d08cdc02453e964e2c8bed190215")
    assert not is_uuid(None) and not is_uuid(12345)


def test_data_errors_map_to_400():
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import DataError
    from app.main import app

    @app.get("/__boom")
    def boom():
        raise DataError("stmt", {}, Exception("invalid input syntax for type uuid"))

    r = TestClient(app, raise_server_exceptions=False).get("/__boom")
    assert r.status_code == 400 and "Invalid" in r.json()["detail"]
