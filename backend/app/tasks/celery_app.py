from celery import Celery
from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "AgnoCall",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.pipeline", "app.tasks.sync"],
)

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_routes={
        "app.tasks.pipeline.stage_audio": {"queue": "gpu-heavy"},
        "app.tasks.pipeline.stage_diarize_transcribe": {"queue": "gpu-heavy"},
        "app.tasks.pipeline.stage_llm_analysis": {"queue": "cpu-io"},
        "app.tasks.pipeline.stage_qa": {"queue": "cpu-io"},
        "app.tasks.pipeline.stage_compliance": {"queue": "cpu-io"},
        "app.tasks.pipeline.stage_sentiment_emotion": {"queue": "cpu-io"},
        "app.tasks.pipeline.stage_analytics": {"queue": "cpu-io"},
        "app.tasks.pipeline.run_pipeline": {"queue": "cpu-io"},
        "app.tasks.pipeline.run_form_evaluation": {"queue": "cpu-io"},
        "app.tasks.pipeline.backfill_form_evaluation": {"queue": "priority-reprocess"},
        "app.tasks.sync.sync_call_records": {"queue": "priority-reprocess"},
        "app.tasks.sync.reap_stale_processing": {"queue": "priority-reprocess"},
    },
    # Poll-based fallback for call-records/ ingestion when MinIO's push
    # webhook can't reach this backend (see app/tasks/sync.py). This entry
    # is inert on its own — it only takes effect once a `celery beat`
    # process is actually running (worker container's `-B` flag, or a
    # dedicated beat container/service); beat is what enqueues the task on
    # this schedule, the worker only executes tasks handed to it.
    beat_schedule={
        "sync-call-records": {
            "task": "app.tasks.sync.sync_call_records",
            "schedule": settings.sync_poll_seconds,
            # A tick that sat in the queue (worker busy) is stale by the time it runs; drop it
            # instead of replaying a backlog of one-second ticks.
            "options": {"expires": max(5.0, 5 * settings.sync_poll_seconds)},
        },
        # Recovery pass for calls stuck at processing/validating because the
        # worker handling them died mid-task -- see reap_stale_processing's
        # docstring. 5 minutes is frequent enough to recover promptly without
        # meaningfully adding to priority-reprocess's load.
        "reap-stale-processing": {
            "task": "app.tasks.sync.reap_stale_processing",
            "schedule": 300.0,
        },
    },
)
