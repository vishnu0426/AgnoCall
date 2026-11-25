"""
"Needs review": the processed calls a QA manager should look at first, with the reason.

A call qualifies for any of: high customer risk, a serious (high/critical) compliance flag
nobody has reviewed yet, or low AI confidence in its own scoring. Calls a human has already
completed a manual review for are left out. Ranked by how many reasons apply and how severe.
"""
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dashboard import call_time, normalise_days, window_conditions
from app.core import settings_store as store
from app.core.database import get_db, get_read_db
from app.core.ids import is_uuid
from app.models.models import (
    Agent, Call, CallStatus, ComplianceViolation, CustomerAnalytics, ManualQAReview, QACriteriaScore, QAEvaluation,
)
from app.schemas.schemas import ReviewQueue, ReviewQueueItem

from datetime import datetime, timedelta

router = APIRouter(prefix="/review", tags=["Review"])

SERIOUS = ("high", "critical")
CANDIDATE_LIMIT = 1500


@router.get("/queue", response_model=ReviewQueue)
def review_queue(db: Session = Depends(get_read_db), days: Optional[int] = None,
                 agent_id: Optional[str] = None, limit: int = 10):
    if agent_id and not is_uuid(agent_id):
        raise HTTPException(400, "Invalid agent_id")
    limit = max(1, min(limit, 50))
    low_confidence = store.value_of(db, "review_low_confidence")
    days = normalise_days(days)
    start = datetime.utcnow() - timedelta(days=days) if days else None
    conds = window_conditions(start, None, agent_id)

    reviewed = db.query(ManualQAReview.call_id).filter(ManualQAReview.status == "completed")
    base = db.query(Call.id).filter(Call.status == CallStatus.processed, ~Call.id.in_(reviewed), *conds)
    ids = [r[0] for r in base.order_by(call_time().desc()).limit(CANDIDATE_LIMIT).all()]
    if not ids:
        return ReviewQueue(total=0, items=[])

    high_risk = {r[0] for r in db.query(CustomerAnalytics.call_id)
                 .filter(CustomerAnalytics.call_id.in_(ids), CustomerAnalytics.risk_level == "high").all()}
    serious = dict(db.query(ComplianceViolation.call_id, func.count(ComplianceViolation.id))
                   .filter(ComplianceViolation.call_id.in_(ids), ComplianceViolation.severity.in_(SERIOUS),
                           ComplianceViolation.reviewed.isnot(True))
                   .group_by(ComplianceViolation.call_id).all())
    low_conf = {r[0] for r in (
        db.query(QAEvaluation.call_id)
        .join(QACriteriaScore, QACriteriaScore.qa_evaluation_id == QAEvaluation.id)
        .filter(QAEvaluation.call_id.in_(ids))
        .group_by(QAEvaluation.call_id)
        .having(func.avg(QACriteriaScore.confidence) < low_confidence).all())}

    scored = []
    for cid in ids:
        reasons, priority = [], 0
        if cid in high_risk:
            reasons.append("High customer risk")
            priority += 3
        if cid in serious:
            n = serious[cid]
            reasons.append(f"{n} serious compliance flag{'s' if n != 1 else ''} not yet reviewed")
            priority += 2 + min(n, 3)
        if cid in low_conf:
            reasons.append("AI was not confident in its scoring")
            priority += 1
        if reasons:
            scored.append((priority, cid, reasons))
    scored.sort(key=lambda t: (-t[0], ids.index(t[1])))   # most urgent first; newest first among equals

    top = scored[:limit]
    if not top:
        return ReviewQueue(total=0, items=[])
    rows = {r[0]: r for r in (
        db.query(Call.id, Call.original_filename, Agent.name, call_time(), QAEvaluation.overall_score)
        .outerjoin(Agent, Agent.id == Call.agent_id)
        .outerjoin(QAEvaluation, QAEvaluation.call_id == Call.id)
        .filter(Call.id.in_([c for _, c, _ in top])).all())}
    items = []
    for priority, cid, reasons in top:
        _, fname, agent, when, qa = rows[cid]
        items.append(ReviewQueueItem(call_id=cid, filename=fname, agent_name=agent, call_date=when,
                                     overall_qa_score=qa, reasons=reasons, priority=priority))
    return ReviewQueue(total=len(scored), items=items)
