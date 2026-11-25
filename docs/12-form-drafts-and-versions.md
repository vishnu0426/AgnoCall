# Form builder: drafts, versions, duplicate, safety nets

## Why
"Save" used to overwrite the LIVE form at once. With AI scoring every new call, a half-edited form could score real calls, and renaming a form silently published any unsaved edits.

## Model
- Live = `title` / `form_content` / `ai_enabled` / `version` (what AI and reviewers use). Unchanged.
- Draft = `draft_title` / `draft_content` / `draft_ai_enabled` (+ who/when). NULL = no draft. Never read by the pipeline.
- `rec_app_evaluation_form_versions`: one snapshot per published revision. A form created before this feature gets its old revision saved the first time it is republished.
- Migration `0006` (idempotent; the startup shim adds the same columns when `AUTO_SCHEMA_SYNC` is on).

## GraphQL
`saveEvaluationFormDraft`, `discardEvaluationFormDraft`, `restoreEvaluationFormVersion` (-> draft, never live), `duplicateEvaluationForm` (live content only; **AI always off on the copy**), `getEvaluationFormVersions`. `saveEvaluationForm` is now "publish": snapshots the old and new revision, clears the draft. Deleting a form deletes its history. Draft content must be a JSON object with a `fields` list (<= 2 MB).

## Editor
- Header: status tag (Unsaved changes / Draft saved, not live / Published), History, Discard draft / Revert, Save draft, Publish.
- Publish validates first (`constants/validateForm.js`): errors block (no questions, unlabeled question, choice question with < 2 options or a blank option, AI on with nothing the AI can answer), warnings can be published anyway (duplicate labels, points not adding up to the total, text questions the AI will skip). If AI is on, the dialog says publishing affects every new call immediately.
- Unsaved changes: browser tab close / reload asks; clicking an in-app link, another form, New form or Restore asks. The browser Back button is not intercepted.
- Rename is now part of the draft (it no longer publishes).

## "Try on a real call" (dry run)
Header button -> pick a recent processed call -> the AI answers the form AS IT IS IN THE EDITOR (including unsaved edits) and the dialog shows each answer, the quote it relied on (flagged "Quote not found" when the quote is not in the transcript), confidence, the score, coverage, and the model. **Nothing is saved.**
- Backend: `testAIFormEvaluation(call_id, form_content, title)` and `getCallsForFormTest`. Uses `pipeline.compute_form_evaluation`, the SAME function the real run uses (prompt, validation, scoring), so the preview cannot drift from reality.
- Guardrails: costs one LLM request, so it needs the same permission as running AI evaluation, honours the kill switch (Settings -> AI form evaluation), is limited to one test per person per 5 s, rejects calls that are unfinished or have no transcript BEFORE any LLM spend, and is audit-logged.

## Incident note: call page stuck on its skeleton
Cause: the API's `uvicorn --reload` supervisor was alive and listening, but its worker had died at startup (earlier: `MINIO_BUCKET=workspace 1`). The reloader only watches `.py` files, so fixing `.env` did not restart it, and every request hung. Fix: restart the API (or save any `.py` file). Hardening: API calls from the web app now time out after 20 s with a clear message instead of leaving the page on a skeleton.

## Critical questions and sections (scoring rules)
One spec, implemented twice and kept identical by golden test cases whose expected values were produced by running the real frontend code (`backend/tests/golden_cases.json`; Python: `form_eval.score_breakdown`, JavaScript: `scoreBreakdown` in `utils/score-utils.js`).

- **Critical question** (`critical: true` on a scored question): if it is answered and earns **0 points**, the whole form scores **0** (automatic fail). `raw_score` still records what the form would have scored, so a manager sees how the call otherwise did. A critical question the AI could not judge (N/A, missing, invalid) is **not** a failure, and neither is one the person left blank: nothing was judged.
- **Section heading** (new field type `section`): groups the questions below it until the next heading. Each section with scored questions gets `{percent, earned, max}`; `earned`/`max` are on the form's scale and add up to the raw score. Questions above the first heading are "General". A heading with nothing scored under it shows no score (the publish checklist warns). Sections are never AI questions.
- Stored for AI evaluations in `evidence._meta`: `raw_score`, `critical_failed`, `sections`. The call page recomputes the same breakdown from the answers, so it also works for human submissions.
- Existing forms score exactly as before (the four original golden cases are unchanged).

## Incident note: "Hydration failed" on the Calls page
`formatDate` used `toLocaleDateString(undefined, ...)`, i.e. the machine's locale. The Next server rendered "Nov 25, 2026" and the browser "25 Nov 2026"; React discarded the server HTML and re-rendered the whole page in the browser (slower, and one console error). `formatDate` / `formatDayMonth` (lib/api.ts) now format the stored date directly ("25 Nov 2026"), independent of locale and time zone. All pages were loaded in headless Chrome afterwards: no console messages.
