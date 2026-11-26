from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from sqlalchemy.exc import DataError

from app.core.config import get_settings
from app.core.database import Base, engine
from app.storage.minio_client import ensure_bucket
from app.api import calls, dashboard, internal, agents, compliance, analytics, forms, forms_graphql, triage, ingestion, calibration, review, settings as settings_api
from app.core.indexes import ensure_indexes
from app.core.response_cache import ResponseCacheMiddleware

app = FastAPI(
    title="Enterprise AI Call Recording Analysis Platform",
    version="1.0.0",
    description="Analyzes recorded customer support calls into AI-generated investigation reports.",
)

@app.exception_handler(DataError)
async def invalid_value_handler(request: Request, exc: DataError):
    # e.g. a malformed UUID or an out-of-range number reaching Postgres from a URL/query value.
    return JSONResponse(status_code=400, content={"detail": "Invalid identifier or value in the request."})


# Innermost: answers repeat summary GETs from memory for a few seconds (see response_cache.py).
app.add_middleware(ResponseCacheMiddleware, ttl_seconds=get_settings().response_cache_seconds)
# Compress JSON responses (transcripts, call lists, analytics are large and repetitive).
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    # Set FRONTEND_ORIGIN in production; "*" remains the dev default.
    allow_origins=[get_settings().frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(calls.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(internal.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(compliance.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(triage.router, prefix="/api/v1")
app.include_router(ingestion.router, prefix="/api/v1")
app.include_router(calibration.router, prefix="/api/v1")
app.include_router(review.router, prefix="/api/v1")
app.include_router(settings_api.router, prefix="/api/v1")
app.include_router(settings_api.account_router, prefix="/api/v1")

# Forms module (ported from the standalone Form Builder project).
app.include_router(forms.router, prefix="/api/v1")
app.include_router(forms.auth_router, prefix="/api/v1")
app.include_router(forms_graphql.graphql_router, prefix="/api/v1")

# Form uploads land in backend/public/uploads and are served back verbatim.
_form_uploads_dir = Path(__file__).resolve().parents[1] / "public" / "uploads"
_form_uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/api/v1/uploads", StaticFiles(directory=str(_form_uploads_dir)), name="form-uploads")


def _ensure_incremental_columns():
    # create_all() only creates missing TABLES, it never ALTERs an existing
    # one. This closes that gap for columns added to already-existing tables
    # (e.g. `health_score` on `conversation_analytics`) so a pre-existing dev
    # DB self-heals on next startup instead of needing a manual psql step.
    # Replaced by `alembic upgrade head` in a real deployment, same as
    # create_all() above.
    inspector = inspect(engine)
    if "conversation_analytics" not in inspector.get_table_names():
        return  # create_all() just created it above, column already included
    existing = {c["name"] for c in inspector.get_columns("conversation_analytics")}
    if "health_score" not in existing:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE conversation_analytics ADD COLUMN IF NOT EXISTS health_score FLOAT"
            ))
    # manual_score became nullable (null = criterion marked N/A by the
    # reviewer) after the table first shipped with NOT NULL.
    if "manual_qa_criteria_scores" in inspector.get_table_names():
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE manual_qa_criteria_scores ALTER COLUMN manual_score DROP NOT NULL"
            ))
    if "transcript_segments" in inspector.get_table_names():
        if "speaker_id" not in {c["name"] for c in inspector.get_columns("transcript_segments")}:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE transcript_segments ADD COLUMN IF NOT EXISTS speaker_id VARCHAR"))
    # Forms module: call_id links an evaluation-form submission to the call
    # it scored; added after rec_app_evaluation_responses first shipped.
    if "rec_app_evaluation_responses" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("rec_app_evaluation_responses")}
        if "call_id" not in existing:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE rec_app_evaluation_responses ADD COLUMN IF NOT EXISTS call_id UUID"
                ))


def _ensure_ai_form_eval_schema(inspector):
    # Form-driven AI evaluation columns/enum value/index, added after the
    # forms tables first shipped. Every statement is idempotent. Superseded by
    # an Alembic migration in a real deployment.
    tables = set(inspector.get_table_names())
    if "rec_app_evaluation_forms" in tables:
        existing = {c["name"] for c in inspector.get_columns("rec_app_evaluation_forms")}
        with engine.begin() as conn:
            for name, ddl in (
                ("ai_enabled", "BOOLEAN NOT NULL DEFAULT false"),
                ("ai_enabled_by", "INTEGER"),
                ("ai_enabled_at", "TIMESTAMPTZ"),
                ("version", "INTEGER NOT NULL DEFAULT 1"),
                ("draft_content", "JSONB"),
                ("draft_title", "VARCHAR(255)"),
                ("draft_ai_enabled", "BOOLEAN"),
                ("draft_updated_at", "TIMESTAMPTZ"),
                ("draft_updated_by", "INTEGER"),
            ):
                if name not in existing:
                    conn.execute(text(
                        f"ALTER TABLE rec_app_evaluation_forms ADD COLUMN IF NOT EXISTS {name} {ddl}"
                    ))
    if "rec_app_evaluation_responses" in tables:
        existing = {c["name"] for c in inspector.get_columns("rec_app_evaluation_responses")}
        with engine.begin() as conn:
            for name, ddl in (
                ("source", "VARCHAR(16) NOT NULL DEFAULT 'human'"),
                ("form_version", "INTEGER"),
                ("evidence", "JSONB"),
            ):
                if name not in existing:
                    conn.execute(text(
                        f"ALTER TABLE rec_app_evaluation_responses ADD COLUMN IF NOT EXISTS {name} {ddl}"
                    ))
            # One AI evaluation per (call, form): the pipeline upserts, and a
            # duplicate/concurrent run can never leave two competing scores.
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_eval_response_ai_call_form "
                "ON rec_app_evaluation_responses (call_id, form_id) WHERE source = 'ai'"
            ))
    # New pipeline stage value on the existing Postgres enum type. ADD VALUE
    # must be committed before use, hence AUTOCOMMIT.
    if "processing_jobs" in tables and engine.dialect.name == "postgresql":
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("ALTER TYPE jobstage ADD VALUE IF NOT EXISTS 'form_eval'"))


@app.on_event("startup")
def on_startup():
    # Dev convenience: create tables if they don't exist yet. In a real
    # deployment this is replaced entirely by `alembic upgrade head`.
    if get_settings().auto_schema_sync:
        Base.metadata.create_all(bind=engine)
        _ensure_incremental_columns()
        _ensure_ai_form_eval_schema(inspect(engine))
        with engine.begin() as conn:
            ensure_indexes(conn)
    ensure_bucket()
    _warm_pool()


def _warm_pool(n: int = 4) -> None:
    """Open a few database connections now. The first connection to a remote database took ~0.8 s, so
    the first page after every restart was slow. Best-effort: a failure here must not stop startup."""
    if engine.dialect.name != "postgresql":
        return
    try:
        conns = [engine.connect() for _ in range(n)]
        for c in conns:
            c.close()
    except Exception:
        pass


@app.get("/health")
def health():
    return {"status": "ok"}
