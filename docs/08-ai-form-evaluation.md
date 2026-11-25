# Form-driven AI evaluation

An evaluation form built in the Forms module can be switched to **AI evaluation**.
While on, **every newly processed call** is scored against that form by the LLM.
The built-in 9-criteria QA and the 4 compliance rules are unaffected and always run.

## Behaviour

| Aspect | Rule |
|---|---|
| Trigger | `EvaluationForm.ai_enabled = true`. Disabled forms cost nothing: no LLM call, no job row. |
| Questions | Scored fields (rating, nps, yesno, segmented, slider, dropdown, radio, checkbox). Text/textarea fields only when the field has an **AI instruction**. Other types are ignored. |
| Answers | The LLM only *chooses answers*, constrained per field type. **The score is computed in code** (`tasks/form_eval.py::score_form`) with the form's own weights, a port of `frontend/.../score-utils.js`, so AI and human scores are on the same scale. Parity is tested against the real frontend scorer (`tests/golden_cases.json`). |
| Not assessable | The model may answer `applicable=false`. N/A, missing and invalid answers are excluded from numerator and denominator (same rule as QA N/A). |
| Never trusted | Out-of-contract answers are rejected (`invalid`), not coerced. Each answer carries an evidence quote, which is checked against the transcript; a quote that cannot be found is flagged `evidence_verified=false`. The transcript is fenced and declared untrusted in the prompt. |
| Storage | One `EvaluationResponse` per (call, form) with `source='ai'`, `form_version`, `responses` (same shape as a human submission) and `evidence` (per-answer audit trail + `_meta`: model, prompt version, coverage). Unique partial index enforces one AI row per (call, form). |
| Versioning | `EvaluationForm.version` bumps whenever `form_content` changes, so an old AI score always says which revision produced it. |
| Reprocess | Only `source='ai'` rows are regenerated. **Human evaluations are never deleted by the pipeline.** |
| Failure isolation | The stage never raises. Failures are recorded on the `form_eval` job (`GET /calls/{id}/jobs`) and logged; the call still completes as `processed`. Each form runs in its own transaction; the LLM call is retried. |
| Human review | In the call's scorecard, an AI row is opened read-only with its evidence. Submitting creates a **new human evaluation** pre-filled from the AI answers (calibration), leaving the AI record intact. |

## Limits and switches (env)

| Variable | Default | Meaning |
|---|---|---|
| `AI_FORM_EVAL_ENABLED` | `true` | Global kill switch (also blocks enabling). |
| `AI_FORM_EVAL_MAX_ENABLED_FORMS` | `3` | Hard cap, enforced **server-side** when enabling (advisory-locked on Postgres) and again in the pipeline (oldest-first). Each enabled form = 1 LLM call per call. |
| `AI_FORM_EVAL_MAX_QUESTIONS` | `40` | Max AI-answerable fields per form; checked when enabling. |
| `AI_FORM_EVAL_LLM_ATTEMPTS` | `2` | Attempts per form per call. |
| `AI_FORM_EVAL_BACKFILL_MAX_CALLS` | `1000` | Max calls one backfill request may queue. |
| `AUTO_SCHEMA_SYNC` | `true` | Legacy startup create_all/ALTER shim; `false` in production (use Alembic). |
| `AI_FORM_EVAL_REQUIRE_ADMIN` | `false` | Refuse anonymous enabling. Authenticated non-admins are always refused. Turn on once the frontend sends the forms JWT. |

Enabling/disabling is audit-logged (`AUDIT ai_form_eval ENABLED|DISABLED form_id=… actor=…`) and recorded on the form (`ai_enabled_by/at`).

## Running on existing calls

Enabling a form does not touch calls processed earlier. Two admin-only paths cover them:

- **Run on this call** (scorecard, "Run AI evaluation"): queues `run_form_evaluation(call_id, form_id)` on `cpu-io`. Only processed calls with a stored transcript; only AI-enabled forms.
- **Backfill** (builder header, "Backfill"): optional date range. It **always previews first** (dry run: "N calls would be evaluated"), then queues `backfill_form_evaluation`, which fans out one task per eligible call. Eligible = processed calls with no AI evaluation of that form yet, so re-running only fills gaps. Capped by `AI_FORM_EVAL_BACKFILL_MAX_CALLS` per request (the UI says when more remain).
- A Redis in-flight lock per (call, form) stops repeated clicks/overlapping backfills queueing the same paid work twice (fails open if Redis is down; duplicates are harmless because results are upserted).
- Both are audit-logged (`AUDIT ai_form_eval RUN|BACKFILL_REQUESTED|BACKFILL ...`).

## Schema management

`backend/alembic/` now exists: `0001` baseline (adopts the create_all schema) and `0002` (this feature, idempotent).

- Existing database: `alembic stamp 0001 && alembic upgrade head`
- Empty database: `alembic upgrade head`
- Production: set `AUTO_SCHEMA_SYNC=false` so the API no longer runs `create_all()` / the legacy ALTER shim at startup.

## Auth

The frontend Apollo client sends `Authorization: Bearer <jwt>` when a token is stored in `localStorage['forms_jwt']`. **There is still no login screen that stores it**, so until one exists requests are anonymous. Do not set `AI_FORM_EVAL_REQUIRE_ADMIN=true` before that, or nobody (including admins) can enable/run AI evaluation.

## Known gaps
- No authentication on the call/analytics endpoints; the admin gate only covers AI evaluation actions.
- Per-form assignment rules (queue/intent/agent) are not implemented; `ai_enabled` means "every call".
- Migration 0002 and the in-flight lock were not run against a real PostgreSQL/Redis in development (offline SQL rendering and fail-open paths only).

## Tests
`cd backend && pip install -r requirements-dev.txt && python -m pytest` — pure logic, stage (fake LLM), and GraphQL guardrails; all run on in-memory SQLite, no Postgres/Redis/LLM needed.
