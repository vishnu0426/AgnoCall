"""
Calibration: is the AI's marking in line with the people who own quality?

A reviewer scores a sample of calls by hand (Manual QA panel) and confirms or
rejects the AI's compliance flags; this module turns that into plain numbers:
how far off the AI is, in which direction, on which criteria and rules.
"""
from collections import defaultdict
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import calibration as cal
from app.core import settings_store as store
from app.core.database import get_db, get_read_db
from app.core.ids import is_uuid
from app.models.models import (
    Agent, Call, CallStatus, ComplianceViolation, ManualQACriteriaScore, ManualQAReview, QAEvaluation,
)
from app.tasks import rubric

router = APIRouter(prefix="/calibration", tags=["Calibration"])


class CriterionCalibration(BaseModel):
    criterion: str
    n: int
    bias: Optional[float]
    mean_abs_error: Optional[float]
    agreement_percent: Optional[float]


class RuleCalibration(BaseModel):
    rule_code: str
    reviewed: int
    confirmed: int
    rejected: int
    precision_percent: Optional[float]


class ComplianceCalibration(BaseModel):
    reviewed: int
    confirmed: int
    rejected: int
    precision_percent: Optional[float]
    unreviewed_flags: int
    by_rule: List[RuleCalibration]


class CalibrationSummary(BaseModel):
    reviewed_calls: int
    target_reviews: int
    bias: Optional[float]
    mean_abs_error: Optional[float]
    agreement_percent: Optional[float]
    verdict_level: str
    verdict_text: str
    ai_average_qa: Optional[float]
    human_average_qa: Optional[float]
    flagged_call_percent: Optional[float]
    by_criterion: List[CriterionCalibration]
    compliance: ComplianceCalibration
    rubric_version: str
    reviewed_on_current_rubric: int


class SampleCall(BaseModel):
    call_id: str
    filename: str
    agent_name: Optional[str]
    ai_qa: Optional[float]
    violations: int
    reason: str


class ComplianceReviewIn(BaseModel):
    outcome: Optional[str] = None  # "confirmed" | "rejected" | null (clear the review)


@router.get("/summary", response_model=CalibrationSummary)
def calibration_summary(db: Session = Depends(get_read_db)):
    reviews = db.query(ManualQAReview).filter(ManualQAReview.status == "completed").all()
    review_ids = [r.id for r in reviews]
    ai_by_call = dict(
        db.query(QAEvaluation.call_id, QAEvaluation.overall_score)
        .filter(QAEvaluation.call_id.in_([r.call_id for r in reviews])).all()
    ) if reviews else {}
    overall_pairs = [(ai_by_call[r.call_id], r.overall_score) for r in reviews
                     if r.call_id in ai_by_call and r.overall_score is not None]
    overall = cal.pair_stats(overall_pairs)
    target_reviews = store.value_of(db, "calibration_target_reviews")
    level, text = cal.verdict(overall.bias, overall.n, target_reviews)

    per_criterion: dict[str, list] = defaultdict(list)
    if review_ids:
        for c in db.query(ManualQACriteriaScore).filter(ManualQACriteriaScore.review_id.in_(review_ids)).all():
            if c.ai_score is not None and c.manual_score is not None:
                per_criterion[c.criterion].append((c.ai_score, c.manual_score))
    by_criterion = []
    for crit, pairs in sorted(per_criterion.items()):
        s = cal.pair_stats(pairs)
        by_criterion.append(CriterionCalibration(criterion=crit, n=s.n, bias=s.bias,
                                                 mean_abs_error=s.mean_abs_error, agreement_percent=s.agreement_percent))
    by_criterion.sort(key=lambda c: -abs(c.bias or 0))   # worst offenders first

    # Compliance: how many AI flags a human upheld.
    flags = db.query(ComplianceViolation.rule_code, ComplianceViolation.review_outcome, ComplianceViolation.reviewed) \
        .join(Call, Call.id == ComplianceViolation.call_id).filter(Call.status == CallStatus.processed).all()
    rule_outcomes: dict[str, list] = defaultdict(list)
    unreviewed = 0
    for rule, outcome, reviewed in flags:
        if reviewed and outcome in ("confirmed", "rejected"):
            rule_outcomes[rule].append(outcome)
        else:
            unreviewed += 1
    overall_c = cal.compliance_stats([o for outs in rule_outcomes.values() for o in outs])
    by_rule = []
    for rule, outs in sorted(rule_outcomes.items()):
        s = cal.compliance_stats(outs)
        by_rule.append(RuleCalibration(rule_code=rule, reviewed=s.reviewed, confirmed=s.confirmed,
                                       rejected=s.rejected, precision_percent=s.precision_percent))
    by_rule.sort(key=lambda r: (r.precision_percent if r.precision_percent is not None else 101))

    # Context: what the AI is doing across ALL processed calls.
    processed = db.query(func.count(Call.id)).filter(Call.status == CallStatus.processed).scalar() or 0
    ai_avg = (db.query(func.avg(QAEvaluation.overall_score)).join(Call, Call.id == QAEvaluation.call_id)
              .filter(Call.status == CallStatus.processed).scalar())
    flagged_calls = (db.query(func.count(func.distinct(ComplianceViolation.call_id)))
                     .join(Call, Call.id == ComplianceViolation.call_id)
                     .filter(Call.status == CallStatus.processed).scalar() or 0)
    human_avg = (sum(h for _, h in overall_pairs) / len(overall_pairs)) if overall_pairs else None

    on_current = 0
    if reviews:
        for (meta,) in db.query(Call.call_metadata).filter(Call.id.in_([r.call_id for r in reviews])).all():
            if (meta or {}).get("rubric_version") == rubric.RUBRIC_VERSION:
                on_current += 1

    return CalibrationSummary(
        reviewed_calls=len(reviews), target_reviews=target_reviews,
        bias=overall.bias, mean_abs_error=overall.mean_abs_error, agreement_percent=overall.agreement_percent,
        verdict_level=level, verdict_text=text,
        ai_average_qa=round(ai_avg, 1) if ai_avg is not None else None,
        human_average_qa=round(human_avg, 1) if human_avg is not None else None,
        flagged_call_percent=round(100 * flagged_calls / processed, 1) if processed else None,
        by_criterion=by_criterion,
        compliance=ComplianceCalibration(
            reviewed=overall_c.reviewed, confirmed=overall_c.confirmed, rejected=overall_c.rejected,
            precision_percent=overall_c.precision_percent, unreviewed_flags=unreviewed, by_rule=by_rule),
        rubric_version=rubric.RUBRIC_VERSION, reviewed_on_current_rubric=on_current,
    )


@router.get("/sample", response_model=List[SampleCall])
def review_sample(n: int = 20, db: Session = Depends(get_read_db)):
    """Calls to score by hand, picked to exercise the AI across its whole range."""
    n = max(1, min(n, 50))
    reviewed_ids = db.query(ManualQAReview.call_id).filter(ManualQAReview.status == "completed")
    rows = (
        db.query(Call.id, Call.original_filename, Agent.name, QAEvaluation.overall_score)
        .join(QAEvaluation, QAEvaluation.call_id == Call.id)
        .outerjoin(Agent, Agent.id == Call.agent_id)
        .filter(Call.status == CallStatus.processed, ~Call.id.in_(reviewed_ids))
        .order_by(Call.uploaded_at.desc())
        .limit(2000)
        .all()
    )
    if not rows:
        return []
    ids = [r[0] for r in rows]
    vcount = dict(db.query(ComplianceViolation.call_id, func.count(ComplianceViolation.id))
                  .filter(ComplianceViolation.call_id.in_(ids)).group_by(ComplianceViolation.call_id).all())
    info = {r[0]: r for r in rows}
    cands = [{"id": r[0], "qa": r[3], "violations": vcount.get(r[0], 0)} for r in rows]
    out = []
    for c in cal.pick_review_sample(cands, n):
        _, fname, agent, qa = info[c["id"]]
        if c["violations"]:
            reason = f"AI flagged {c['violations']} compliance issue{'s' if c['violations'] != 1 else ''}"
        elif qa is not None and qa < 30:
            reason = "AI scored this low"
        elif qa is not None and qa >= 60:
            reason = "AI scored this high"
        else:
            reason = "Mid-range score"
        out.append(SampleCall(call_id=c["id"], filename=fname, agent_name=agent, ai_qa=qa,
                              violations=c["violations"], reason=reason))
    return out


@router.put("/compliance/{violation_id}")
def review_compliance_flag(violation_id: str, payload: ComplianceReviewIn, db: Session = Depends(get_db)):
    """A reviewer upholds or rejects one AI compliance flag (null clears it)."""
    if payload.outcome not in (None, "confirmed", "rejected"):
        raise HTTPException(400, "outcome must be 'confirmed', 'rejected' or null")
    v = (db.query(ComplianceViolation).filter(ComplianceViolation.id == violation_id).first()
         if is_uuid(violation_id) else None)
    if not v:
        raise HTTPException(404, "Compliance flag not found")
    v.reviewed = payload.outcome is not None
    v.review_outcome = payload.outcome
    db.commit()
    return {"id": v.id, "reviewed": v.reviewed, "review_outcome": v.review_outcome}
