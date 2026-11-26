import re
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Core services
    database_url: str = "postgresql+psycopg://AgnoCall:AgnoCall@localhost:5432/AgnoCall"
    redis_url: str = "redis://localhost:6379/0"

    # MinIO / S3-compatible object storage
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "AgnoCall"
    minio_secret_key: str = "AgnoCall123"
    minio_bucket: str = "call-recordings"
    minio_secure: bool = False
    # Endpoint used when building presigned URLs the *browser* will call directly.
    # Inside docker-compose the backend talks to MinIO via the "minio" service
    # name, but a presigned URL handed to the frontend must resolve from the
    # user's machine, hence a separate public endpoint.
    # Region used to sign playback links locally (MinIO's default). Change only if the server sets MINIO_REGION.
    minio_region: str = "us-east-1"
    minio_public_endpoint: str = "localhost:9000"

    # Provider abstraction (ADR-001): deployment_mode gates which providers
    # are even selectable — "air_gapped" disables every *Cloud provider.
    deployment_mode: str = "hybrid"  # cloud | air_gapped | hybrid
    openai_api_key: str = ""
    # "auto" preserves existing OpenAI/Ollama selection; "mock" forces the
    # instant, no-network MockLLMProvider (load-testing / local dev only).
    llm_provider: str = "auto"

    # Dev convenience: create_all() + ad-hoc ALTERs at API startup. Set to
    # false in production and manage the schema with `alembic upgrade head`
    # (existing databases: `alembic stamp 0001` once, then upgrade).
    auto_schema_sync: bool = True

    # How often the poll-based MinIO fallback scans for new recordings. The MinIO
    # webhook is the primary trigger; this only needs to catch what it misses.
    sync_poll_seconds: float = 1.0

    # Identical read-only summary GETs are answered from memory for this many seconds (0 = off).
    # Any write empties the cache. See app/core/response_cache.py.
    response_cache_seconds: float = 5.0

    # SQLAlchemy connection pool (per process: API, each Celery worker).
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Targets shown beside the dashboard KPIs (so a number has something to be compared with).
    qa_target_score: float = 80.0
    compliance_target_percent: float = 95.0

    # Browser origin allowed by CORS. "*" is the dev default; set to the real
    # frontend origin (e.g. "https://calls.example.com") in production.
    frontend_origin: str = "*"

    # Speech-to-text provider selection: deepgram | google | mock
    stt_provider: str = "deepgram"
    deepgram_api_key: str = ""
    # Path to a Google Cloud service account JSON key (same convention as
    # GOOGLE_APPLICATION_CREDENTIALS used by the google-cloud-speech client).
    google_application_credentials: str = ""
    # Stereo recordings: which channel of the PBX recording is the agent ("left" or "right").
    stereo_agent_channel: str = "left"

    # Outgoing email for scheduled reports (Settings > Scheduled reports). Leave SMTP_HOST empty to turn
    # sending off; schedules can still be created and are reported as "SMTP not configured".
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_security: str = "starttls"      # starttls (port 587) | ssl (port 465) | none (plain, internal relay only)
    smtp_from: str = ""                  # e.g. "AgnoCall Reports <reports@yourcompany.com>"
    smtp_timeout_seconds: int = 20
    # The clock schedules are read in ("08:00" means 08:00 here). An IANA name such as Asia/Kolkata.
    report_timezone: str = "UTC"
    report_max_recipients: int = 20
    # The one standard message at the top of every report email. "\\n" in .env means a line break.
    report_message: str = "Hello,\n\nHere is your scheduled AgnoCall analytics report. It covers real conversations only: IVR surveys, silent and very short recordings are left out of the averages and counted separately. The attached report has the full analytics: key metrics, categories, topics, sentiment, emotions, call volume, agent scores and how the AI compares with your reviewers.\n\nThis message is sent automatically."

    # Forms module (ported from the Form Builder project): secret used to sign
    # and verify the form-builder JWTs (FB's JWT_SECRET env var).
    forms_jwt_secret: str = "form_builder_secret_key"

    # Form-driven AI evaluation (forms flagged `ai_enabled` are scored by the
    # LLM on every new call). Each enabled form costs one LLM call per call
    # processed, so the number of enabled forms and questions per form are
    # capped. `ai_form_eval_enabled=false` is a global kill switch.
    ai_form_eval_enabled: bool = True
    ai_form_eval_max_enabled_forms: int = 3
    ai_form_eval_max_questions: int = 40
    ai_form_eval_llm_attempts: int = 2
    # When true, anonymous callers cannot enable AI evaluation (set once the
    # frontend sends the forms JWT; authenticated non-admins are always refused).
    ai_form_eval_require_admin: bool = False
    # Upper bound on calls one backfill request may queue (each = 1 LLM call).
    ai_form_eval_backfill_max_calls: int = 1000

    # Analytics only averages real conversations: a recording shorter than this (words or seconds) is an IVR
    # survey, a dropped call or a "hello?" and is reported separately instead of dragging the averages down.
    analytics_min_words: int = 50
    analytics_min_seconds: int = 15

    class Config:
        env_file = ".env"

    @field_validator("minio_endpoint", "minio_public_endpoint")
    @classmethod
    def _strip_scheme(cls, value: str) -> str:
        # The minio-py client rejects an endpoint that includes a scheme
        # ("ValueError: path in endpoint is not allowed") — it wants a bare
        # host:port and derives http vs. https solely from `minio_secure`.
        # Stripping any accidental http(s):// prefix here means .env can be
        # written either way without silently breaking the client at import
        # time (minio_client.py constructs both clients at module load).
        return re.sub(r"^https?://", "", value).rstrip("/")

    @field_validator("smtp_security")
    @classmethod
    def _valid_smtp_security(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"starttls", "ssl", "none"}:
            raise ValueError("SMTP_SECURITY must be starttls, ssl or none.")
        return value

    @field_validator("report_timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(value.strip())
        except Exception:
            raise ValueError(f"REPORT_TIMEZONE={value!r} is not a time zone name (for example 'UTC' or 'Asia/Kolkata').")
        return value.strip()

    @field_validator("minio_bucket")
    @classmethod
    def _valid_bucket(cls, value: str) -> str:
        # S3/MinIO bucket names: 3-63 chars, lower-case letters, digits, dots and hyphens only (no
        # spaces or underscores). Fail at startup with a message that names the setting, not with
        # minio-py's "invalid bucket name" from deep inside the startup hook.
        value = value.strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", value):
            raise ValueError(
                f"MINIO_BUCKET={value!r} is not a valid bucket name: use 3-63 lower-case letters, digits, "
                "hyphens or dots, with no spaces (for example 'workspace-1')."
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
