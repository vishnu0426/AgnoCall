# Analytics: trustworthy numbers and click-through

## Why
The first version averaged every processed recording. On the live data 69 of 98 "calls" were IVR surveys
("Press 1, very satisfied"), "hello?" calls or one-liners, and 84 had speech from one side only. They scored
near zero and dragged every KPI down, so the page measured recording junk, not agent quality.

## What counts as a real conversation
`app/core/conversation.py`: at least `analytics_min_words` spoken words (default 50) AND at least
`analytics_min_seconds` (default 15). Both are editable in Settings > Analytics. The same test powers the
Calls page filter "Real conversations" / "IVR, silent or very short", so every number can be opened as a list.

## The endpoint
`GET /analytics/overview?days=7|30|90&agent_id=...`
- every block is limited to real, processed conversations in the window (and the chosen agent);
- `kpis_previous`: the same KPIs for the period before (only when `days` is set) for "up/down vs previous";
- `quality`: processed / conversations / excluded / one_sided / roles_from_channel / failed + thresholds;
- `attention`: the calls to open first, each with reasons (compliance flags by severity, escalated/unresolved,
  negative ending, QA < 40), ranked by seriousness;
- `category_stats[].key`: the raw category the Calls page filters on (`/calls?category=...`).

## On the page
Period and agent filters (shared with the dashboard, kept in the URL), a data-quality banner, KPI cards with
a definition on hover, sample size and change vs the previous period (hidden when the previous period is
empty), a "Review these first" list, clickable category tiles, table alternatives for the treemap and the
word cloud, "Updated" time and a CSV export of the headline numbers.

## Not covered here
Per-question scorecard analytics, scheduled reports, alerts, cost/usage, roles and permissions, audit log.

## Scheduled reports (Settings > Scheduled reports)
An administrator can email the Analytics numbers on a schedule, as a PDF, a CSV, or both.
- **Schedule:** daily, weekly (pick the weekday) or monthly (day 1-28), at a time of day, covering the last
  7 / 30 / 90 days or all time, to up to 20 recipients. Up to 20 schedules. Pause, resume, edit, delete, and
  "Send now" for a test (that does not change when it is next due).
- **Clock:** times are read in `REPORT_TIMEZONE` (default UTC; for example `Asia/Kolkata`).
- **Email server:** `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY` (starttls | ssl | none), `SMTP_USERNAME`,
  `SMTP_PASSWORD`, `SMTP_FROM` in `backend/.env` (see `.env.example`). Restart the API and the worker after
  changing them. With `SMTP_HOST` empty nothing is sent and the page says so; the password is never returned
  by the API or shown in an error.
- **Sending:** `celery beat` runs `app.tasks.reports.run_due_reports` every minute (the worker needs `-B` or a
  beat process). A schedule is claimed by moving `next_run_at` forward before sending, so it cannot go out
  twice; if the system was down, one report is sent, not one per missed day. A failed send is recorded on the
  schedule (shown in red) and the next run is still scheduled.
- **Files:** the PDF is built with `reportlab`; the CSV has a UTF-8 BOM so Excel opens it correctly, and cells
  that start with `=`, `+`, `-` or `@` are escaped so a hostile category name cannot run as a formula.
- **Code:** `app/reports/` (schedule maths, render, mailer, service), `app/api/reports.py`,
  `app/tasks/reports.py`, table `report_schedules` (migration 0008).

### What is in a report email
- **Body:** one standard message (same for every report; `REPORT_MESSAGE` in `.env`, `\n` = new line, empty = none),
  then the report name, period, the data-quality sentence and three headline numbers.
- **PDF:** the Analytics page as a document: key metrics (with change vs the previous period), categories,
  topics, sentiment trend, customer emotions, call volume, agent x QA criteria and AI-vs-reviewer calibration.
  There is no link or button; everything is in the file. Charts are drawn in `app/reports/charts.py`.
- **CSV:** the same numbers as rows, including the sentiment trend, emotions and calibration.
