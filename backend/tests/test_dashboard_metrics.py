"""Regression tests for dashboard/compliance numbers (once showed Compliance -1.2%)."""
import pytest

pytest.importorskip("celery")

from app.api import compliance, dashboard  # noqa: E402
from app.models.models import (  # noqa: E402
    Call, CallStatus, ComplianceViolation, CustomerAnalytics, QAEvaluation,
)


def add_call(db, name, status, qa=None, violations=0, risk=None):
    c = Call(original_filename=name, storage_path=f"x/{name}", status=status)
    db.add(c)
    db.flush()
    if qa is not None:
        db.add(QAEvaluation(call_id=c.id, overall_score=qa))
    for i in range(violations):
        db.add(ComplianceViolation(call_id=c.id, rule_code=f"R{i}", category="c", severity="low"))
    if risk:
        db.add(CustomerAnalytics(call_id=c.id, risk_level=risk))
    db.commit()
    return c


def test_compliance_never_negative_when_unprocessed_calls_hold_violations(db):
    # 2 processed calls, 1 clean; plus 2 FAILED calls that still carry violations.
    add_call(db, "p1", CallStatus.processed, qa=80, violations=1)
    add_call(db, "p2", CallStatus.processed, qa=60)
    add_call(db, "f1", CallStatus.failed, violations=2)
    add_call(db, "f2", CallStatus.processing, violations=1)

    pct = dashboard.dashboard_summary(db).compliance_percent
    assert pct == 50.0                      # 1 of 2 processed calls is clean
    assert compliance.compliance_summary(db).clean_call_percent == 50.0


def test_qa_and_risk_ignore_unprocessed_calls(db):
    add_call(db, "p1", CallStatus.processed, qa=80, risk="high")
    add_call(db, "p2", CallStatus.processed, qa=60, risk="low")
    add_call(db, "f1", CallStatus.failed, qa=0, risk="high")     # stale rows on a failed call
    s = dashboard.dashboard_summary(db)
    assert s.average_qa == 70.0
    assert s.high_risk_calls == 1
    assert (s.total_calls, s.processed, s.failed) == (3, 2, 1)


def test_zero_qa_score_is_shown_not_hidden(db):
    add_call(db, "p1", CallStatus.processed, qa=0.0)
    assert dashboard.dashboard_summary(db).average_qa == 0.0


def test_no_processed_calls_gives_none_not_a_crash(db):
    add_call(db, "f1", CallStatus.failed)
    s = dashboard.dashboard_summary(db)
    assert s.compliance_percent is None and s.average_qa is None


def test_stage_analytics_tolerates_not_applicable_qa_scores(db):
    """The production failure: `int + NoneType` when the LLM returned a null score."""
    from app.tasks import pipeline
    c = add_call(db, "p1", CallStatus.processing)
    analysis = {"qa_scores": [{"criterion": "greeting", "score": 80},
                              {"criterion": "closing", "score": None}]}
    pipeline._stage_analytics(db, c, [], analysis)    # must not raise
    assert db.query(CustomerAnalytics).filter_by(call_id=c.id).count() == 1
