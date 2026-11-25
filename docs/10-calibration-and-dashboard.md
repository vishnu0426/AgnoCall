# Calibration, QA-manager dashboard, agent inference

## Calibration (`/calibration`, page "Calibration")
Question answered: *is the AI marking in line with the people who own quality?*

1. **Pick calls** — `GET /calibration/sample`: processed, not-yet-reviewed calls spread across the AI's score range (low / middle / high) plus a few the AI flagged, so a harsh or generous AI cannot hide. Deterministic.
2. **A person scores them** — existing Manual QA panel on each call (stores the AI score it was made against).
3. **A person checks the AI's compliance flags** — "Correct / Wrong" on each flag in the call's Compliance tab (`PUT /calibration/compliance/{id}`).
4. **Read the result** — `GET /calibration/summary`: bias (human − AI; positive = AI too harsh), typical gap, agreement within ±10 pts, a plain-English verdict, worst criteria first, compliance precision per rule, progress to 20 reviews. The maths is in `app/core/calibration.py` (unit-tested).
5. **Fix and re-measure** — scoring rules live in `app/tasks/rubric.py` (`RUBRIC_VERSION`, stored on every analysed call). Change the wording, bump the version, then use **Re-run analysis** on a call (`POST /calls/{id}/reprocess`; manual reviews are kept) and compare agreement.

**Why a rubric:** the QA prompt used to say "score these criteria 0-100" with bare names and no definition of a good score; the compliance prompt had no "when in doubt, don't flag". Live data before the change: median QA 12, 100% of processed calls flagged. `rubric.py` adds a definition + high/low anchors per criterion, a scoring scale, "null if not assessable", and "flag only with an exact quote".
**Not proven:** whether v2 actually brings the AI close to your reviewers. That needs a real model run and ~20 human scores; the Calibration page is the instrument for it.

## Dashboard
- Period (7/30/90 days / all) and agent filters, kept in the URL. Every figure follows them; with a period, each card shows ▲/▼ against the previous equal period (`previous` in `GET /dashboard/summary`).
- Targets next to QA and compliance (`QA_TARGET_SCORE`, `COMPLIANCE_TARGET_PERCENT`).
- Cards link to the matching list; Calls page supports search, date, agent, has-violations filters.
- **Needs review** (`GET /review/queue`): high customer risk, serious unreviewed compliance flags, low AI confidence; calls a person already reviewed drop out.
- **AI evaluation** card (`GET /dashboard/ai-evaluation`): calls scored per AI-enabled form and agreement with human scores of the same form.
- QA-by-day chart with the target line.

## Agents from file names
`app/core/filename_meta.py`: `call__<customer>_<ext>_…`, `call_<ext>_<customer>_…`, `call_<ext>_<ext>_…` (internal). A 1-6 digit number is an extension, 7+ digits a phone number; unparseable names infer nothing. On ingestion and upload, the call is attached to "Extension <n>" (created once; unique index prevents duplicates). Rename it on the Agents page and all that extension's calls follow. **Detect agents from file names** (`POST /agents/backfill-from-filenames`) attaches existing calls; idempotent. An explicit agent in an upload always wins, and the old bug where an upload with only a name could attach to an unrelated agent is fixed.

## Sign-in
`/login` stores the Forms JWT; the GraphQL client sends it, so admin-only actions (enable / run / backfill AI evaluation) can be enforced (`AI_FORM_EVAL_REQUIRE_ADMIN=true` once everyone who needs it can sign in). The seed script creates `admin` with a well-known password: change it before relying on this.

## Robustness note
PostgreSQL rejects a malformed UUID (`agent_id=nope`) with a data error where SQLite just matches nothing. New endpoints validate IDs (400/404) and a global handler maps `DataError` to 400. Tests run on SQLite, so the live API was also exercised for these paths.
