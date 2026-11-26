import hashlib
import csv
import io
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload, load_only, selectinload

from app.core import settings_store as store
from app.core.conversation import conversation_ids
from app.core.database import get_db, get_read_db
from app.models.models import (
    Call, Agent, CallStatus, ProcessingJob, JobStage, JobStatus,
    Transcript, QAEvaluation, ComplianceViolation, SentimentAnalysis,
    TimelineEvent, ConversationAnalytics, CustomerAnalytics,
    CallExtraction, CallClassification, CallLabel, PauseEvent,
    EmotionAnalysis, AIObservation, Recommendation,
    CallInsight, ManualQAReview, ManualQACriteriaScore,
)
from app.schemas.schemas import (
    CallAccepted, CallSummary, CallListResponse, TranscriptOut, TranscriptSegmentOut,
    QAEvaluationOut, ComplianceViolationOut, SentimentOut, TimelineEventOut,
    CallAnalyticsOut, CallExtractionOut, CallClassificationOut, CallLabelOut,
    PauseEventOut, EmotionOut, AIObservationOut, RecommendationOut, ProcessingJobOut,
    CallInsightOut, ManualQAReviewIn, ManualQAReviewOut,
)
from app.core.agent_resolution import agent_for_upload, apply_filename_metadata
from app.core.failures import classify_failure
from app.core.ids import is_uuid
from app.core.parallel import run_parallel
from app.storage import minio_client
from app.tasks.pipeline import run_pipeline

router = APIRouter(prefix="/calls", tags=["Calls"])

ALLOWED_EXTENSIONS = {"wav", "mp3", "flac", "m4a"}


def _extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _processing_duration(call: Call) -> Optional[float]:
    if not call.processed_at or not call.uploaded_at:
        return None
    return round((call.processed_at - call.uploaded_at).total_seconds(), 1)


def _summary_loader_options():
    """Eager-loading for call summaries. One-to-one relations are JOINed (they can't multiply rows,
    so LIMIT stays cheap); the only collection that is rendered, `labels`, is loaded with one extra
    IN() query.

    Only the columns a summary actually shows are fetched (`load_only`). The full rows carry large
    JSON/text fields (waveform peaks, rubric notes, evidence ...); with the database a network hop
    away, shipping them for a 25-row list cost ~250 ms per page on its own."""
    return (
        load_only(Call.id, Call.status, Call.agent_id, Call.duration_seconds, Call.call_date,
                  Call.original_filename, Call.failure_reason, Call.uploaded_at, Call.processed_at),
        joinedload(Call.agent).load_only(Agent.name),
        joinedload(Call.qa_evaluation).load_only(QAEvaluation.overall_score),
        joinedload(Call.customer_analytics).load_only(CustomerAnalytics.risk_level),
        joinedload(Call.classification).load_only(CallClassification.category),
        joinedload(Call.conversation_analytics).load_only(ConversationAnalytics.health_score),
        joinedload(Call.manual_qa_review).load_only(ManualQAReview.status, ManualQAReview.overall_score),
        selectinload(Call.labels).load_only(CallLabel.label),
    )


def violation_stats(db: Session, call_ids: list) -> tuple[dict, dict]:
    """(call_id -> violation count, call_id -> {severity: count}) in ONE grouped query
    (instead of loading every violation row, with its evidence text, only to len() it)."""
    counts: dict = {}
    severities: dict = {}
    if not call_ids:
        return counts, severities
    rows = (
        db.query(ComplianceViolation.call_id, ComplianceViolation.severity, func.count(ComplianceViolation.id))
        .filter(ComplianceViolation.call_id.in_(call_ids))
        .group_by(ComplianceViolation.call_id, ComplianceViolation.severity)
        .all()
    )
    for cid, sev, n in rows:
        counts[cid] = counts.get(cid, 0) + n
        severities.setdefault(cid, {})[sev or "unknown"] = n
    return counts, severities


def violation_counts(db: Session, call_ids: list) -> dict:
    return violation_stats(db, call_ids)[0]


def _to_summary(call: Call, violation_count: Optional[int] = None, severities: Optional[dict] = None) -> CallSummary:
    qa_score = call.qa_evaluation.overall_score if call.qa_evaluation else None
    risk = call.customer_analytics.risk_level if call.customer_analytics else None
    review = call.manual_qa_review
    status_value = call.status.value if hasattr(call.status, "value") else call.status
    failure = classify_failure(call.failure_reason) if status_value == "failed" else None
    return CallSummary(
        violation_severities=severities or {},
        failure_category=failure.category if failure else None,
        failure_label=failure.label if failure else None,
        failure_advice=failure.advice if failure else None,
        failure_retryable=failure.retryable if failure else None,
        manual_reviewed=bool(review and review.status == "completed"),
        manual_qa_score=review.overall_score if review else None,
        id=call.id,
        status=call.status.value if hasattr(call.status, "value") else call.status,
        agent_name=call.agent.name if call.agent else None,
        duration_seconds=call.duration_seconds,
        call_date=call.call_date,
        overall_qa_score=qa_score,
        compliance_violation_count=(
            violation_count if violation_count is not None else len(call.compliance_violations or [])
        ),
        risk_level=risk,
        original_filename=call.original_filename,
        category=call.classification.category if call.classification else None,
        health_score=call.conversation_analytics.health_score if call.conversation_analytics else None,
        labels=[l.label for l in (call.labels or [])],
        failure_reason=call.failure_reason,
        processing_duration_seconds=_processing_duration(call),
    )


@router.post("", response_model=CallAccepted, status_code=202)
async def upload_call(
    file: UploadFile = File(...),
    agent_external_id: Optional[str] = Form(None),
    agent_name: Optional[str] = Form(None),
    call_date: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    ext = _extension(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type .{ext}. Allowed: {sorted(ALLOWED_EXTENSIONS)}")

    # The same recording uploaded twice would be analysed twice and counted twice in every average, so an
    # identical file (same content) returns the existing call instead of making a new one.
    file_bytes = await file.read()
    digest = hashlib.sha256(file_bytes).hexdigest()
    existing = (
        db.query(Call)
        .filter(Call.call_metadata["content_sha256"].as_string() == digest, Call.status != CallStatus.failed)
        .order_by(Call.uploaded_at.asc())
        .first()
    )
    if existing:
        return CallAccepted(call_id=existing.id, status=existing.status.value, duplicate=True)

    # Explicit agent from the form wins. (This used to look up
    # `external_agent_id == None` when only a name was given, which matched an
    # arbitrary unrelated agent and attributed the call to the wrong person.)
    agent = agent_for_upload(db, agent_external_id, agent_name)

    call = Call(
        original_filename=file.filename,
        storage_path="",  # set once uploaded
        status=CallStatus.uploaded,
        agent_id=agent.id if agent else None,
        call_date=datetime.fromisoformat(call_date) if call_date else datetime.utcnow(),
        call_metadata={"content_sha256": digest},
    )
    db.add(call)
    apply_filename_metadata(db, call)  # fills agent from the filename only if none was given
    db.flush()  # assigns call.id without committing yet

    object_key = minio_client.upload_audio(call.id, file.filename, file_bytes, file.content_type)
    call.storage_path = object_key
    db.commit()
    db.refresh(call)

    # In a real MinIO deployment the bucket's event notification (configured
    # in docker-compose's minio-init service) fires the webhook below on its
    # own once the PUT above lands, which is what actually enqueues the
    # pipeline. We also enqueue directly here so upload -> processing works
    # immediately in dev even before MinIO's own event delivery is wired up
    # (e.g. first run, before minio-init has finished configuring the bucket).
    run_pipeline.delay(call.id)

    return CallAccepted(call_id=call.id, status=call.status.value)


SORTS = {"date", "qa", "violations", "duration", "risk", "status", "agent"}
EXPORT_LIMIT = 5000


def _filtered_calls(db: Session, status, risk_level, agent_id, days, has_violations, search, reviewed,
                    category=None, conversation=None):
    """The Calls-page filters as one query (shared by the list and the CSV export).
    Returns (query, set of tables already joined, so a sort never joins one twice)."""
    if agent_id and not is_uuid(agent_id):
        raise HTTPException(400, "Invalid agent_id")
    q = db.query(Call)
    joined: set = set()
    if status:
        q = q.filter(Call.status == status)
    if agent_id:
        q = q.filter(Call.agent_id == agent_id)
    if days and days > 0:
        q = q.filter(func.coalesce(Call.call_date, Call.uploaded_at) >= datetime.utcnow() - timedelta(days=min(days, 365)))
    if has_violations is not None:
        flagged = db.query(ComplianceViolation.call_id)
        q = q.filter(Call.id.in_(flagged) if has_violations else ~Call.id.in_(flagged))
    if reviewed is not None:
        done = db.query(ManualQAReview.call_id).filter(ManualQAReview.status == "completed")
        q = q.filter(Call.id.in_(done) if reviewed else ~Call.id.in_(done))
    if category:
        q = q.filter(Call.id.in_(db.query(CallClassification.call_id).filter(CallClassification.category == category)))
    if conversation is not None:
        # the same test analytics uses: a real conversation vs an IVR survey / "hello?" / one-liner
        cfg = store.effective(db)
        real = conversation_ids(cfg.analytics_min_words, cfg.analytics_min_seconds)
        q = q.filter(Call.id.in_(real) if conversation else ~Call.id.in_(real))
    if search and search.strip():
        # escape LIKE wildcards so a search for "100%" or "a_b" is literal
        term = search.strip()[:100].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        q = q.filter(Call.original_filename.ilike(f"%{term}%", escape="\\"))
    if risk_level:
        # Joined (not filtered post-fetch in Python) so `total` and the paginated page agree.
        q = q.join(CustomerAnalytics).filter(CustomerAnalytics.risk_level == risk_level)
        joined.add("risk")
    return q, joined


def _apply_sort(db: Session, q, joined: set, sort: Optional[str], order: str):
    """ORDER BY for the chosen column; empty values always last, ties broken by id so paging is stable."""
    desc = order != "asc"
    if sort is None or sort not in SORTS:
        return q.order_by(Call.uploaded_at.desc(), Call.id)
    if sort == "qa":
        q = q.outerjoin(QAEvaluation, QAEvaluation.call_id == Call.id)
        col = QAEvaluation.overall_score
    elif sort == "risk":
        if "risk" not in joined:
            q = q.outerjoin(CustomerAnalytics, CustomerAnalytics.call_id == Call.id)
        col = case((CustomerAnalytics.risk_level == "high", 3), (CustomerAnalytics.risk_level == "medium", 2),
                   (CustomerAnalytics.risk_level == "low", 1), else_=None)
    elif sort == "agent":
        q = q.outerjoin(Agent, Agent.id == Call.agent_id)
        col = func.lower(Agent.name)
    elif sort == "violations":
        col = (db.query(func.count(ComplianceViolation.id))
               .filter(ComplianceViolation.call_id == Call.id).correlate(Call).scalar_subquery())
    elif sort == "duration":
        col = Call.duration_seconds
    elif sort == "status":
        col = Call.status
    else:  # date
        col = func.coalesce(Call.call_date, Call.uploaded_at)
    return q.order_by((col.desc() if desc else col.asc()).nulls_last(), Call.id)


@router.get("", response_model=CallListResponse)
def list_calls(
    status: Optional[str] = None,
    risk_level: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
    db: Session = Depends(get_read_db),
    agent_id: Optional[str] = None,
    days: Optional[int] = None,
    has_violations: Optional[bool] = None,
    search: Optional[str] = None,
    reviewed: Optional[bool] = None,
    sort: Optional[str] = None,
    order: str = "desc",
    category: Optional[str] = None,
    conversation: Optional[bool] = None,
):
    base_query, joined = _filtered_calls(db, status, risk_level, agent_id, days, has_violations, search, reviewed,
                                         category, conversation)

    # Bound the page size so one request can't ask for the whole table.
    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    def count(sess):
        # a bare COUNT: `.count()` wraps the whole wide query in a subquery and is slower
        return base_query.with_session(sess).with_entities(func.count(Call.id)).scalar() or 0

    def rows(sess):
        query = _apply_sort(sess, base_query.with_session(sess).options(*_summary_loader_options()), joined, sort, order)
        calls = query.offset((page - 1) * page_size).limit(page_size).all()
        counts, severities = violation_stats(sess, [c.id for c in calls])
        return [_to_summary(c, counts.get(c.id, 0), severities.get(c.id)) for c in calls]

    total, results = run_parallel(db, [count, rows])      # the count and the page are independent
    return CallListResponse(items=results, total=total, page=page, page_size=page_size)


def _csv_safe(value) -> str:
    """Spreadsheet apps run text starting with = + - @ as a formula; a recording's file name is
    attacker-controlled, so neutralise it."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/export.csv")
def export_calls_csv(
    status: Optional[str] = None, risk_level: Optional[str] = None, db: Session = Depends(get_read_db),
    agent_id: Optional[str] = None, days: Optional[int] = None, has_violations: Optional[bool] = None,
    search: Optional[str] = None, reviewed: Optional[bool] = None, sort: Optional[str] = None, order: str = "desc",
    category: Optional[str] = None, conversation: Optional[bool] = None,
):
    """The current filtered list as a spreadsheet (newest first unless sorted), capped at EXPORT_LIMIT rows."""
    base_query, joined = _filtered_calls(db, status, risk_level, agent_id, days, has_violations, search, reviewed,
                                         category, conversation)
    calls = _apply_sort(db, base_query.options(*_summary_loader_options()), joined, sort, order).limit(EXPORT_LIMIT).all()
    counts, severities = violation_stats(db, [c.id for c in calls])
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["File", "Call date", "Agent", "Status", "Duration (s)", "AI QA score", "Violations",
                "Violation severities", "Risk", "Reviewed by a person", "Human QA score", "Category", "Failure"])
    for c in calls:
        r = _to_summary(c, counts.get(c.id, 0), severities.get(c.id))
        w.writerow([_csv_safe(v) for v in [
            r.original_filename, r.call_date.isoformat(sep=" ", timespec="minutes") if r.call_date else "",
            r.agent_name, r.status, r.duration_seconds, r.overall_qa_score, r.compliance_violation_count,
            ", ".join(f"{n} {sev}" for sev, n in sorted(r.violation_severities.items())), r.risk_level,
            "yes" if r.manual_reviewed else "no", r.manual_qa_score, r.category, r.failure_label]])
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M")
    return Response(
        content="﻿" + out.getvalue(),   # BOM so Excel reads UTF-8
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="agnocall-calls-{stamp}.csv"'},
    )


MAX_REPROCESS = 10


@router.post("/{call_id}/reprocess")
def reprocess_call(call_id: str, db: Session = Depends(get_db)):
    """Run the analysis again (e.g. after the scoring rubric improved). Only a finished call
    (processed or failed) can be re-run; the claim is a conditional update so a double-click
    can't queue it twice, and a per-call cap stops an endless loop. A human's manual review is
    kept: it stores the AI score it was made against."""
    outcome = _claim_reprocess(db, call_id)
    if outcome == "not_found":
        raise HTTPException(404, "Call not found")
    if outcome == "cap":
        raise HTTPException(409, f"This call has already been re-run {MAX_REPROCESS} times.")
    if outcome == "busy":
        raise HTTPException(409, "The call is still being processed.")
    run_pipeline.delay(call_id)
    return {"call_id": call_id, "status": "queued"}


def _claim_reprocess(db: Session, call_id: str) -> str:
    """'queued' | 'not_found' | 'cap' | 'busy'. The caller sends the task for 'queued'."""
    if not is_uuid(call_id):
        return "not_found"
    call = db.query(Call).filter(Call.id == call_id).first()
    if not call:
        return "not_found"
    meta = call.call_metadata or {}
    count = int(meta.get("reprocess_count", 0))
    if count >= MAX_REPROCESS:
        return "cap"
    claimed = db.query(Call).filter(
        Call.id == call_id, Call.status.in_([CallStatus.processed, CallStatus.failed]),
    ).update({"status": CallStatus.validating, "failure_reason": None,
              "call_metadata": {**meta, "reprocess_count": count + 1}}, synchronize_session=False)
    db.commit()
    return "queued" if claimed else "busy"


MAX_BULK = 100


class BulkReprocessIn(BaseModel):
    call_ids: List[str]


@router.post("/reprocess")
def reprocess_many(payload: BulkReprocessIn, db: Session = Depends(get_db)):
    """Re-run analysis for the selected calls (same rules as one call; at most MAX_BULK at a time)."""
    ids = list(dict.fromkeys(payload.call_ids))
    if not ids:
        raise HTTPException(400, "Select at least one call.")
    if len(ids) > MAX_BULK:
        raise HTTPException(400, f"Select at most {MAX_BULK} calls at a time.")
    result = {"queued": 0, "busy": 0, "cap": 0, "not_found": 0}
    queued = []
    for cid in ids:
        outcome = _claim_reprocess(db, cid)
        result[outcome] += 1
        if outcome == "queued":
            queued.append(cid)
    for cid in queued:
        run_pipeline.delay(cid)
    return result


@router.get("/{call_id}", response_model=CallSummary)
def get_call(call_id: str, db: Session = Depends(get_read_db)):
    if not is_uuid(call_id):
        raise HTTPException(404, "Call not found")
    call = db.query(Call).options(
        joinedload(Call.agent), joinedload(Call.qa_evaluation),
        joinedload(Call.compliance_violations), joinedload(Call.customer_analytics),
        joinedload(Call.classification), joinedload(Call.conversation_analytics),
        joinedload(Call.labels), joinedload(Call.manual_qa_review),
    ).filter(Call.id == call_id).first()
    if not call:
        raise HTTPException(404, "Call not found")
    return _to_summary(call)


@router.get("/{call_id}/audio")
def get_audio_url(call_id: str, db: Session = Depends(get_read_db)):
    call = db.query(Call).filter(Call.id == call_id).first()
    if not call or not call.storage_path:
        raise HTTPException(404, "Call or audio not found")
    # Prefer the normalized, browser-playable copy written during
    # transcription (see minio_client.object_key_for_playback) — the
    # original upload is never re-encoded in place and may use a codec (e.g.
    # G.729, common from PBX/SIP sources) no browser can decode. Falls back
    # to the original for calls that haven't reached that pipeline stage yet.
    mp3_key = minio_client.object_key_for_playback(call_id)
    wav_key = minio_client.object_key_for_playback_wav(call_id)
    if minio_client.object_exists(mp3_key):
        key, source = mp3_key, "playback"
    elif minio_client.object_exists(wav_key):
        key, source = wav_key, "playback"
    else:
        # `source: original` lets the frontend warn that the browser may not
        # be able to decode the un-transcoded upload.
        key, source = call.storage_path, "original"
    url = minio_client.get_presigned_audio_url(key)
    # Precomputed peaks let the player draw the waveform immediately and
    # stream the audio on demand instead of downloading the whole file first.
    peaks = (call.call_metadata or {}).get("waveform_peaks")
    return {
        "url": url,
        "expires_minutes": 30,
        "source": source,
        "peaks": peaks,
        "duration": call.duration_seconds,
    }


@router.get("/{call_id}/transcript", response_model=TranscriptOut)
def get_transcript(call_id: str, db: Session = Depends(get_read_db)):
    transcript = db.query(Transcript).filter(Transcript.call_id == call_id).first()
    if not transcript:
        raise HTTPException(404, "Transcript not available yet")
    return TranscriptOut(
        call_id=call_id,
        pii_masked=transcript.pii_masked,
        segments=[
            TranscriptSegmentOut(
                sequence=s.sequence, speaker_role=s.speaker_role,
                start_time=s.start_time, end_time=s.end_time,
                text=s.text_masked, stt_confidence=s.stt_confidence,
            ) for s in transcript.segments
        ],
    )


@router.get("/{call_id}/qa", response_model=QAEvaluationOut)
def get_qa(call_id: str, db: Session = Depends(get_read_db)):
    qa = db.query(QAEvaluation).filter(QAEvaluation.call_id == call_id).first()
    if not qa:
        raise HTTPException(404, "QA evaluation not available yet")
    return qa


@router.get("/{call_id}/compliance", response_model=List[ComplianceViolationOut])
def get_compliance(call_id: str, db: Session = Depends(get_read_db)):
    return db.query(ComplianceViolation).filter(ComplianceViolation.call_id == call_id).all()


@router.get("/{call_id}/sentiment", response_model=SentimentOut)
def get_sentiment(call_id: str, db: Session = Depends(get_read_db)):
    sentiment = db.query(SentimentAnalysis).filter(SentimentAnalysis.call_id == call_id).first()
    if not sentiment:
        raise HTTPException(404, "Sentiment not available yet")
    return sentiment


@router.get("/{call_id}/timeline", response_model=List[TimelineEventOut])
def get_timeline(call_id: str, db: Session = Depends(get_read_db)):
    return db.query(TimelineEvent).filter(TimelineEvent.call_id == call_id).order_by(TimelineEvent.start_time).all()


@router.get("/{call_id}/analytics", response_model=CallAnalyticsOut)
def get_analytics(call_id: str, db: Session = Depends(get_read_db)):
    conv = db.query(ConversationAnalytics).filter(ConversationAnalytics.call_id == call_id).first()
    cust = db.query(CustomerAnalytics).filter(CustomerAnalytics.call_id == call_id).first()

    def to_dict(obj):
        if not obj:
            return None
        return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in ("id", "call_id")}

    return CallAnalyticsOut(conversation=to_dict(conv), customer=to_dict(cust))


@router.get("/{call_id}/extraction", response_model=CallExtractionOut)
def get_extraction(call_id: str, db: Session = Depends(get_read_db)):
    extraction = db.query(CallExtraction).filter(CallExtraction.call_id == call_id).first()
    if not extraction:
        raise HTTPException(404, "Extraction not available yet")
    return extraction


@router.get("/{call_id}/classification", response_model=CallClassificationOut)
def get_classification(call_id: str, db: Session = Depends(get_read_db)):
    classification = db.query(CallClassification).filter(CallClassification.call_id == call_id).first()
    if not classification:
        raise HTTPException(404, "Classification not available yet")
    return classification


@router.get("/{call_id}/labels", response_model=List[CallLabelOut])
def get_labels(call_id: str, db: Session = Depends(get_read_db)):
    return db.query(CallLabel).filter(CallLabel.call_id == call_id).all()


@router.get("/{call_id}/pauses", response_model=List[PauseEventOut])
def get_pauses(call_id: str, db: Session = Depends(get_read_db)):
    return db.query(PauseEvent).filter(PauseEvent.call_id == call_id).order_by(PauseEvent.start_time).all()


@router.get("/{call_id}/emotion", response_model=EmotionOut)
def get_emotion(call_id: str, db: Session = Depends(get_read_db)):
    emotion = db.query(EmotionAnalysis).filter(EmotionAnalysis.call_id == call_id).first()
    if not emotion:
        raise HTTPException(404, "Emotion analysis not available yet")
    return emotion


@router.get("/{call_id}/observations", response_model=List[AIObservationOut])
def get_observations(call_id: str, db: Session = Depends(get_read_db)):
    return db.query(AIObservation).filter(AIObservation.call_id == call_id).all()


@router.get("/{call_id}/recommendations", response_model=List[RecommendationOut])
def get_recommendations(call_id: str, db: Session = Depends(get_read_db)):
    return db.query(Recommendation).filter(Recommendation.call_id == call_id).all()


@router.get("/{call_id}/insights", response_model=CallInsightOut)
def get_insights(call_id: str, db: Session = Depends(get_read_db)):
    insight = db.query(CallInsight).filter(CallInsight.call_id == call_id).first()
    if not insight:
        raise HTTPException(404, "Insights not available yet")
    return insight


@router.get("/{call_id}/manual-qa", response_model=ManualQAReviewOut)
def get_manual_qa(call_id: str, db: Session = Depends(get_read_db)):
    review = db.query(ManualQAReview).filter(ManualQAReview.call_id == call_id).first()
    if not review:
        raise HTTPException(404, "No manual QA review for this call yet")
    return review


@router.put("/{call_id}/manual-qa", response_model=ManualQAReviewOut)
def upsert_manual_qa(call_id: str, payload: ManualQAReviewIn, db: Session = Depends(get_db)):
    call = db.query(Call).filter(Call.id == call_id).first()
    if not call:
        raise HTTPException(404, "Call not found")
    if payload.status not in ("draft", "completed"):
        raise HTTPException(400, "status must be 'draft' or 'completed'")
    if not payload.reviewer_name.strip():
        raise HTTPException(400, "reviewer_name is required")

    review = db.query(ManualQAReview).filter(ManualQAReview.call_id == call_id).first()
    if not review:
        review = ManualQAReview(call_id=call_id, reviewer_name=payload.reviewer_name)
        db.add(review)
        db.flush()
    else:
        # Full-replace upsert: the panel always submits the complete review.
        db.query(ManualQACriteriaScore).filter(
            ManualQACriteriaScore.review_id == review.id
        ).delete(synchronize_session=False)

    review.reviewer_name = payload.reviewer_name.strip()
    review.status = payload.status
    review.notes = payload.notes
    # N/A criteria (manual_score null) stay on the review for the record but
    # are excluded from the overall — same rule the AI pipeline uses.
    scores = [c.manual_score for c in payload.criteria if c.manual_score is not None]
    review.overall_score = round(sum(scores) / len(scores), 1) if scores else None

    for c in payload.criteria:
        db.add(ManualQACriteriaScore(
            review_id=review.id,
            criterion=c.criterion,
            ai_score=c.ai_score,
            manual_score=c.manual_score,
            comment=c.comment,
        ))
    db.commit()
    db.refresh(review)
    return review


@router.get("/{call_id}/jobs", response_model=List[ProcessingJobOut])
def get_jobs(call_id: str, db: Session = Depends(get_read_db)):
    """Per-stage timing breakdown (e.g. how long transcription vs. LLM
    analysis took), sourced from ProcessingJob rows the pipeline already
    writes via `_touch_job()`. Stages that don't call `_touch_job` (currently
    extraction/labeling, sentiment/emotion, timeline/recommendations — see
    pipeline.py) won't have a row and simply won't appear here."""
    jobs = db.query(ProcessingJob).filter(ProcessingJob.call_id == call_id).order_by(ProcessingJob.started_at).all()
    return [
        ProcessingJobOut(
            stage=j.stage.value if hasattr(j.stage, "value") else j.stage,
            status=j.status.value if hasattr(j.status, "value") else j.status,
            started_at=j.started_at,
            completed_at=j.completed_at,
            duration_seconds=round((j.completed_at - j.started_at).total_seconds(), 1)
            if j.started_at and j.completed_at else None,
            error_message=j.error_message,
        )
        for j in jobs
    ]
