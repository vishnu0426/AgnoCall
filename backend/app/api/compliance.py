from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.core import compliance_rules as cr
from app.core.database import get_db, get_read_db
from app.models.models import Call, CallStatus, ComplianceViolation
from app.schemas.schemas import ComplianceSummary, ComplianceRuleBreakdown, ComplianceViolationWithCallOut

router = APIRouter(prefix="/compliance", tags=["Compliance"])


@router.get("/summary", response_model=ComplianceSummary)
def compliance_summary(db: Session = Depends(get_read_db)):
    total_processed = db.query(func.count(Call.id)).filter(Call.status == CallStatus.processed).scalar() or 0
    # Processed calls only (same rule as the dashboard card), clamped to 0-100.
    calls_with_violations = (
        db.query(func.count(func.distinct(ComplianceViolation.call_id)))
        .join(Call, Call.id == ComplianceViolation.call_id)
        .filter(Call.status == CallStatus.processed)
        .scalar() or 0
    )
    clean_percent = (
        round(max(0.0, min(100.0, 100 * (1 - calls_with_violations / total_processed))), 1)
        if total_processed else None
    )

    # Grouped by rule code only: the AI's free-text category differs call to call for the same rule.
    # Rows are merged in Python because codes may differ in case or punctuation ("Greeting missing").
    merged: dict = {}
    for code, raw_cat, n in (
        db.query(ComplianceViolation.rule_code, ComplianceViolation.category, func.count(ComplianceViolation.id))
        .group_by(ComplianceViolation.rule_code, ComplianceViolation.category).all()
    ):
        c = cr.normalise_code(code)
        entry = merged.setdefault(c, [cr.rule_category(c, raw_cat), 0])
        entry[1] += n
    by_rule_rows = sorted(((c, v[0], v[1]) for c, v in merged.items()), key=lambda r: -r[2])
    by_severity = dict(
        db.query(ComplianceViolation.severity, func.count(ComplianceViolation.id))
        .group_by(ComplianceViolation.severity).all()
    )
    # ComplianceViolation has no wall-clock timestamp of its own (only
    # timestamp_ref, the in-call audio offset), so "recent" is ordered via
    # the parent call's upload time.
    recent = (
        db.query(ComplianceViolation)
        .join(Call, Call.id == ComplianceViolation.call_id)
        .options(joinedload(ComplianceViolation.call).joinedload(Call.agent))
        .order_by(Call.uploaded_at.desc())
        .limit(60)
        .all()
    )

    return ComplianceSummary(
        total_processed_calls=total_processed,
        calls_with_violations=calls_with_violations,
        clean_call_percent=clean_percent,
        by_rule=[ComplianceRuleBreakdown(rule_code=r, label=cr.rule_label(r), category=c, count=n) for r, c, n in by_rule_rows],
        by_severity=by_severity,
        recent_violations=[
            ComplianceViolationWithCallOut(
                id=v.id, rule_code=v.rule_code, category=v.category, severity=v.severity,
                call_date=v.call.call_date or v.call.uploaded_at,
                timestamp_ref=v.timestamp_ref, explanation=v.explanation, evidence=v.evidence,
                reviewed=v.reviewed, review_outcome=v.review_outcome,
                call_id=v.call_id, call_filename=v.call.original_filename,
                agent_name=v.call.agent.name if v.call.agent else None,
            ) for v in recent
        ],
    )
