# Ingestion, failure triage and performance

## MinIO-first ingestion
Recordings arrive in the MinIO bucket (`call-records/YYYY/MM/DD/<uuid>-...wav`). The dashboard no longer has a manual upload box; it shows **Ingestion health** (`GET /api/v1/ingestion/status`): bucket reachable, last file, files in last 24h, waiting / in progress, and when the webhook and poller last fired.

- Primary trigger: MinIO webhook -> `POST /internal/minio-webhook`.
- Fallback: `sync_call_records` (celery beat), every `SYNC_POLL_SECONDS` (default **10s**, was 1s). It is now set-based: one MinIO listing + one DB query per date prefix per tick (it used to run one SELECT per object per second).
- Health: `healthy` / `degraded` (no trigger seen, or files waiting while the poller is stopped) / `down` (MinIO unreachable). Liveness markers live in Redis (`app/core/heartbeat.py`); if Redis is down they are silently skipped and never block ingestion.
- The upload API (`POST /calls`) still exists for tests/integrations; only the UI entry points were removed.

## Failure triage (`/api/v1/failures`)
`Call.failure_reason` is classified (`app/core/failures.py`) into: `no_speech` (expected, not a fault), `bad_audio`, `tool_missing` (e.g. ffmpeg not installed), `timeout`, `external_service`, `worker_crashed`, `unexpected`.

- Dashboard "Failed" shows **actionable** failures; silent recordings are shown separately ("+ N silent (not a fault)").
- `GET /failures/summary`: counts per category with a sample message.
- `POST /failures/retry` `{call_ids?, category?}`: re-queues only retryable failures. Safeguards: non-retryable categories are skipped; at most 5 manual retries per call; at most 500 calls per request; the claim is a conditional update so concurrent requests can't queue a call twice.

## Metrics correctness
Dashboard and Compliance numbers are computed over **processed calls only** and clamped to 0-100 (a stale result on a failed call once produced Compliance -1.2%). A genuine pipeline bug (`int + None` when a QA criterion was N/A, in `_stage_analytics`) was fixed.

## Performance changes
| Change | Why |
|---|---|
| Indexes on every `call_id` foreign key + hot filters (`app/core/indexes.py`, Alembic `0003`, also applied by the dev startup shim) | PostgreSQL does not index foreign keys; every call page/list/dashboard join was a sequential scan. |
| Calls list: 1:1 relations JOINed, `labels` via one IN() query, violation counts via one grouped query; page size capped at 100 | Joining the 1:N collections multiplied rows and forced a wrapping subquery for LIMIT. |
| Dashboard: one grouped query for the status cards (was four COUNTs) | Fewer round trips. |
| Poller batched (above) | ~hundreds of queries/second -> 2-3 per tick. |
| GZip for JSON responses > 1 KB | Smaller payloads for transcripts/lists/analytics. |
| Sized connection pool + recycling (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`) | No per-request connection setup, no stale connections. |
| Frontend dashboard fetches summary / failures / ingestion in parallel | Wall time = slowest request, not the sum. |

Regression guards in `backend/tests/test_triage_ingestion_perf.py`: the calls list issues the **same number of queries for 5 rows and 45 rows** (no N+1), the dashboard stays under a fixed query budget, and the poller issues <= 3 queries for 60 files.

Applying: restart API, worker and **beat** (new interval). Indexes are created at startup when `AUTO_SCHEMA_SYNC=true`, otherwise run `alembic upgrade head` (on a large production table build them in a quiet window / CONCURRENTLY).
