"""
Ingestion health for a MinIO-first deployment: is the bucket reachable, are
files arriving (push webhook and/or the poller), and what is queued.
"""
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db, get_read_db
from app.core.failures import classify_failure
from app.core.heartbeat import last_beats
from app.models.models import Call, CallStatus
from app.schemas.schemas import IngestionStatus
from app.storage import minio_client

router = APIRouter(prefix="/ingestion", tags=["Ingestion"])

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="minio-probe")
_probe_cache: dict = {"at": 0.0, "ok": False}
PROBE_TTL_SECONDS = 15
PROBE_TIMEOUT_SECONDS = 2
WEBHOOK_STALE_HOURS = 24


def _minio_reachable() -> bool:
    """Cheap, cached, time-boxed reachability probe (the MinIO client has no short default timeout)."""
    now = time.monotonic()
    if now - _probe_cache["at"] < PROBE_TTL_SECONDS:
        return _probe_cache["ok"]
    try:
        ok = bool(_executor.submit(minio_client._internal_client.bucket_exists, minio_client.BUCKET)
                  .result(timeout=PROBE_TIMEOUT_SECONDS))
    except (FutureTimeout, Exception):
        ok = False
    _probe_cache.update(at=now, ok=ok)
    return ok


def _age(ts: float | None) -> float | None:
    return round(time.time() - ts, 1) if ts else None


@router.get("/status", response_model=IngestionStatus)
def ingestion_status(db: Session = Depends(get_read_db)):
    settings = get_settings()
    since = datetime.utcnow() - timedelta(hours=24)
    # One round trip for every figure (each statement costs a network hop to the database).
    pending, processing, ingested_24h, last_call = db.query(
        func.count(Call.id).filter(Call.status.in_([CallStatus.uploaded, CallStatus.validating])),
        func.count(Call.id).filter(Call.status == CallStatus.processing),
        func.count(Call.id).filter(Call.uploaded_at >= since),
        func.max(Call.uploaded_at),
    ).one()

    webhook_beat, poller_beat = last_beats("webhook", "poller")
    webhook_age = _age(webhook_beat)
    poller_age = _age(poller_beat)
    interval = settings.sync_poll_seconds
    poller_ok = poller_age is not None and poller_age <= max(3 * interval, 30)
    webhook_ok = webhook_age is not None and webhook_age <= WEBHOOK_STALE_HOURS * 3600
    minio_ok = _minio_reachable()

    issues = []
    if not minio_ok:
        issues.append("The recording storage is not reachable from the backend.")
    if not poller_ok and not webhook_ok:
        issues.append("No ingestion trigger seen: the poller (celery beat) is not running and no "
                      f"webhook arrived in the last {WEBHOOK_STALE_HOURS}h.")
    if pending > 0 and not poller_ok:
        issues.append(f"{pending} file(s) waiting but the poller is not running.")
    state = "healthy" if not issues else ("down" if not minio_ok else "degraded")

    return IngestionStatus(
        state=state,
        issues=issues,
        minio_reachable=minio_ok,
        bucket=minio_client.BUCKET,
        webhook_last_seen_seconds_ago=webhook_age,
        poller_last_run_seconds_ago=poller_age,
        poll_interval_seconds=interval,
        pending=pending,
        processing=processing,
        ingested_last_24h=ingested_24h,
        last_ingested_at=last_call,
    )
