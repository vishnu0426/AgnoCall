"""
Failure triage for the QA manager: what failed, why, and a safe retry.

Failures are grouped by category (app/core/failures.py). "Expected" failures
(a silent recording) are reported separately so they don't inflate the failure
rate; only retryable categories can be retried, and each call has a retry cap
so a call that keeps failing can't be re-queued forever.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, literal_column
from sqlalchemy.orm import Session

from app.core.database import get_db, get_read_db
from app.core.failures import classify_failure
from app.core.ids import is_uuid
from app.models.models import Call, CallStatus
from app.schemas.schemas import FailureGroup, FailureSummary, RetryRequest, RetryResult
from app.tasks.pipeline import run_pipeline

router = APIRouter(prefix="/failures", tags=["Failures"])

MAX_MANUAL_RETRIES = 5   # per call
MAX_BATCH = 500          # calls re-queued per request


def summarize_failures(db: Session, conds=()) -> FailureSummary:
    """Failure groups, optionally restricted to the same period/agent window as the dashboard."""
    # The expression is inlined (no bind parameters) on purpose: with bound
    # parameters PostgreSQL sees the SELECT and GROUP BY copies as different
    # expressions and rejects the query ("must appear in the GROUP BY clause").
    reason_head = literal_column("substr(calls.failure_reason, 1, 600)")
    rows = (
        db.query(reason_head, func.count(Call.id))
        .filter(Call.status == CallStatus.failed, *conds)
        .group_by(reason_head)
        .all()
    )
    groups: dict[str, FailureGroup] = {}
    for reason, count in rows:
        info = classify_failure(reason)
        g = groups.get(info.category)
        if g is None:
            sample = ((reason or "").strip().splitlines() or [""])[0][:200] or None
            g = groups[info.category] = FailureGroup(
                category=info.category, label=info.label, retryable=info.retryable,
                expected=info.expected, count=0, sample_reason=sample, advice=info.advice,
            )
        g.count += count
    ordered = sorted(groups.values(), key=lambda g: -g.count)
    total = sum(g.count for g in ordered)
    expected = sum(g.count for g in ordered if g.expected)
    return FailureSummary(
        total_failed=total,
        expected=expected,
        actionable=total - expected,
        retryable=sum(g.count for g in ordered if g.retryable),
        groups=ordered,
    )


@router.get("/summary", response_model=FailureSummary)
def failure_summary(db: Session = Depends(get_read_db)):
    return summarize_failures(db)


@router.post("/retry", response_model=RetryResult)
def retry_failed(payload: RetryRequest, db: Session = Depends(get_db)):
    """Re-queue failed calls. Give `call_ids`, or a `category`, or neither (= every
    retryable failed call). Non-retryable failures (silent audio, undecodable audio)
    are skipped -- retrying them cannot succeed."""
    query = db.query(Call).filter(Call.status == CallStatus.failed)
    if payload.call_ids is not None:
        valid = [c for c in payload.call_ids if is_uuid(c)]   # a non-UUID can never match; don't send it to Postgres
        if not valid:
            raise HTTPException(404, "No failed calls match the request")
        query = query.filter(Call.id.in_(valid))
    calls: List[Call] = query.limit(5000).all()
    if payload.call_ids is not None and not calls:
        raise HTTPException(404, "No failed calls match the request")

    retried, skipped_not_retryable, skipped_cap, ids = 0, 0, 0, []
    for call in calls:
        info = classify_failure(call.failure_reason)
        if payload.category and info.category != payload.category:
            continue
        if not info.retryable:
            skipped_not_retryable += 1
            continue
        meta = call.call_metadata or {}
        tries = int(meta.get("manual_retries", 0))
        if tries >= MAX_MANUAL_RETRIES:
            skipped_cap += 1
            continue
        if retried >= MAX_BATCH:
            break
        # Conditional update: only a call still `failed` is claimed, so two
        # concurrent retry requests can never queue the same call twice.
        claimed = db.query(Call).filter(Call.id == call.id, Call.status == CallStatus.failed).update(
            {"status": CallStatus.validating, "failure_reason": None,
             "call_metadata": {**meta, "manual_retries": tries + 1}},
            synchronize_session=False,
        )
        db.commit()
        if claimed:
            ids.append(call.id)
            retried += 1
    for cid in ids:
        run_pipeline.delay(cid)
    return RetryResult(
        retried=retried, skipped_not_retryable=skipped_not_retryable,
        skipped_retry_cap=skipped_cap, truncated=retried >= MAX_BATCH,
    )
