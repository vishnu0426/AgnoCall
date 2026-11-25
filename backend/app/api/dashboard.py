from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.api.calls import _summary_loader_options, _to_summary, violation_counts
from app.api.triage import summarize_failures
from app.core import settings_store as store
from app.core.parallel import run_parallel
from app.core.database import get_db, get_read_db
from app.core.ids import is_uuid
from app.models.models import (
    Call, CallStatus, ComplianceViolation, CustomerAnalytics, EvaluationForm, EvaluationResponse, QAEvaluation,
)
from app.schemas.schemas import (
    AIEvaluationSummary, AIFormStat, DashboardSummary, PeriodMetrics, QATrendPoint,
)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

MAX_DAYS = 365
DEFAULT_TREND_DAYS = 90


def call_time(call=Call):
    """When a call happened: its recorded date, else when it arrived."""
    return func.coalesce(call.call_date, call.uploaded_at)


def window_conditions(start: Optional[datetime], end: Optional[datetime], agent_id: Optional[str], call=Call) -> list:
    conds = []
    if start is not None:
        conds.append(call_time(call) >= start)
    if end is not None:
        conds.append(call_time(call) < end)
    if agent_id:
        conds.append(call.agent_id == agent_id)
    return conds


def normalise_days(days: Optional[int]) -> Optional[int]:
    if not days or days <= 0:
        return None
    return min(days, MAX_DAYS)


def _metrics(db: Session, start: Optional[datetime], end: Optional[datetime], agent_id: Optional[str]) -> dict:
    """Every KPI for one window in ONE statement (each statement is a network round trip to the
    database). Quality metrics use PROCESSED calls only; stale results on a failed/reprocessing
    call must never count against a processed-only denominator."""
    c2 = aliased(Call)                      # subqueries get their own alias so they never correlate to the outer FROM
    w2 = [c2.status == CallStatus.processed, *window_conditions(start, end, agent_id, c2)]
    avg_qa = (select(func.avg(QAEvaluation.overall_score)).select_from(QAEvaluation)
              .join(c2, c2.id == QAEvaluation.call_id).where(*w2).scalar_subquery())
    high_risk = (select(func.count(CustomerAnalytics.id)).select_from(CustomerAnalytics)
                 .join(c2, c2.id == CustomerAnalytics.call_id)
                 .where(CustomerAnalytics.risk_level == "high", *w2).scalar_subquery())
    flagged = (select(func.count(func.distinct(ComplianceViolation.call_id))).select_from(ComplianceViolation)
               .join(c2, c2.id == ComplianceViolation.call_id).where(*w2).scalar_subquery())
    total, processed, processing, failed, avg_qa, high_risk, with_violations = db.query(
        func.count(Call.id),
        func.count(Call.id).filter(Call.status == CallStatus.processed),
        func.count(Call.id).filter(Call.status == CallStatus.processing),
        func.count(Call.id).filter(Call.status == CallStatus.failed),
        avg_qa, high_risk, flagged,
    ).filter(*window_conditions(start, end, agent_id)).one()
    high_risk, with_violations = high_risk or 0, with_violations or 0
    compliance = None
    if processed:
        compliance = round(max(0.0, min(100.0, 100 * (1 - with_violations / processed))), 1)
    failures = summarize_failures(db, window_conditions(start, end, agent_id)) if failed else None
    return {
        "total": total,
        "processed": processed,
        "processing": processing,
        "failed": failed,
        "average_qa": round(avg_qa, 1) if avg_qa is not None else None,
        "compliance_percent": compliance,
        "high_risk": high_risk,
        "failed_expected": failures.expected if failures else 0,
        "failed_actionable": failures.actionable if failures else 0,
        "failed_retryable": failures.retryable if failures else 0,
    }


def _qa_trend(db: Session, conds: list, days: Optional[int]) -> list[QATrendPoint]:
    conds = list(conds)
    if days is None:  # "all time" would be an unbounded scan and an unreadable chart
        conds.append(call_time() >= datetime.utcnow() - timedelta(days=DEFAULT_TREND_DAYS))
    rows = (
        db.query(call_time(), QAEvaluation.overall_score)
        .join(QAEvaluation, QAEvaluation.call_id == Call.id)
        .filter(Call.status == CallStatus.processed, *conds)
        .all()
    )
    per_day: dict[str, list] = defaultdict(list)
    for when, score in rows:
        if when is not None and score is not None:
            per_day[when.strftime("%Y-%m-%d")].append(score)
    return [QATrendPoint(day=d, avg_qa=round(sum(v) / len(v), 1), calls=len(v)) for d, v in sorted(per_day.items())]


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(db: Session = Depends(get_read_db), days: Optional[int] = None, agent_id: Optional[str] = None):
    """`days` limits every figure to the last N days (None = all time); `agent_id` to one agent.
    With a period, `previous` holds the same figures for the N days before it (for trend arrows)."""
    settings = store.effective(db)
    if agent_id and not is_uuid(agent_id):
        raise HTTPException(400, "Invalid agent_id")
    days = normalise_days(days)
    now = datetime.utcnow()
    start = now - timedelta(days=days) if days else None
    conds = window_conditions(start, None, agent_id)

    def current(sess):
        return _metrics(sess, start, None, agent_id)

    def before(sess):
        return _metrics(sess, start - timedelta(days=days), start, agent_id) if days else None

    def trend(sess):
        return _qa_trend(sess, conds, days)

    def recent_calls(sess):
        recent = (sess.query(Call).options(*_summary_loader_options()).filter(*conds)
                  .order_by(Call.uploaded_at.desc()).limit(10).all())
        counts = violation_counts(sess, [c.id for c in recent])
        return [_to_summary(c, counts.get(c.id, 0)) for c in recent]

    # Four independent groups of queries: run side by side (see app/core/parallel.py).
    m, pm, qa_trend, recent_summaries = run_parallel(db, [current, before, trend, recent_calls])
    previous = None
    if pm is not None:
        previous = PeriodMetrics(
            total_calls=pm["total"], processed=pm["processed"], failed_actionable=pm["failed_actionable"],
            average_qa=pm["average_qa"], compliance_percent=pm["compliance_percent"],
            high_risk_calls=pm["high_risk"],
        )

    return DashboardSummary(
        total_calls=m["total"], processed=m["processed"], processing=m["processing"], failed=m["failed"],
        average_qa=m["average_qa"], compliance_percent=m["compliance_percent"], high_risk_calls=m["high_risk"],
        recent_calls=recent_summaries,
        failed_expected=m["failed_expected"], failed_actionable=m["failed_actionable"],
        failed_retryable=m["failed_retryable"],
        period_days=days, agent_id=agent_id, previous=previous,
        qa_target=settings.qa_target_score, compliance_target=settings.compliance_target_percent,
        qa_trend=qa_trend,
    )


@router.get("/ai-evaluation", response_model=AIEvaluationSummary)
def ai_evaluation_summary(db: Session = Depends(get_read_db)):
    """How the AI-scored forms are doing, and how closely the AI agrees with humans who scored the
    same call with the same form (within 10% of the form's total score)."""
    forms = db.query(EvaluationForm).filter(EvaluationForm.ai_enabled.is_(True)).order_by(EvaluationForm.title).all()
    items = []
    for f in forms:
        total = float((f.form_content or {}).get("total_score") or 100) or 100.0
        ai = {(r.call_id): r.score for r in db.query(EvaluationResponse.call_id, EvaluationResponse.score)
              .filter(EvaluationResponse.form_id == f.form_id, EvaluationResponse.source == "ai",
                      EvaluationResponse.call_id.isnot(None)).all()}
        human: dict = defaultdict(list)
        for cid, score in (db.query(EvaluationResponse.call_id, EvaluationResponse.score)
                           .filter(EvaluationResponse.form_id == f.form_id, EvaluationResponse.source == "human",
                                   EvaluationResponse.call_id.isnot(None), EvaluationResponse.score.isnot(None)).all()):
            human[cid].append(score)
        ai_scores = [s for s in ai.values() if s is not None]
        pairs = [(ai[cid], sum(h) / len(h)) for cid, h in human.items() if ai.get(cid) is not None]
        agree = (round(100 * sum(1 for a, h in pairs if abs(a - h) <= 0.10 * total) / len(pairs), 1)
                 if pairs else None)
        items.append(AIFormStat(
            form_id=f.form_id, title=f.title, version=f.version or 1, scored_calls=len(ai_scores),
            average_score=round(sum(ai_scores) / len(ai_scores), 1) if ai_scores else None,
            total_score=total, compared_with_human=len(pairs), agreement_percent=agree,
        ))
    return AIEvaluationSummary(enabled_forms=len(forms), items=items)
