"""Build a scheduled report and send it."""
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.api.analytics import analytics_overview
from app.core.config import get_settings
from app.models.models import ReportSchedule
from app.reports import mailer, render
from app.reports.schedule import next_run

log = logging.getLogger("agnocall.reports")

MIME = {"pdf": "application/pdf", "csv": "text/csv"}


def build_message(db: Session, sched: ReportSchedule, now: datetime) -> tuple[str, str, list]:
    overview = analytics_overview(days=sched.period_days or None, agent_id=None, attention=False, db=db)
    generated = now.strftime("%d %b %Y, %H:%M UTC")
    period = render.period_label(overview.days)
    attachments = []
    stem = "agnocall-report-" + now.strftime("%Y%m%d")
    for fmt in sched.formats:
        data = (render.build_pdf if fmt == "pdf" else render.build_csv)(overview, sched.name, generated)
        attachments.append((f"{stem}.{fmt}", data, MIME[fmt]))
    k = overview.kpis
    message = get_settings().report_message.replace("\\n", "\n").strip()
    lines = [
        *([message, "", "-" * 40, ""] if message else []),
        f"{sched.name}", f"{period}, generated {generated}", "",
        render.quality_sentence(overview), "",
        f"Average AI QA score: {k['avg_qa_score'] if k['avg_qa_score'] is not None else '-'}",
        f"Negative endings: {str(k['negative_end_percent']) + '%' if k['negative_end_percent'] is not None else '-'}",
        f"Follow-ups: {k['follow_up_required']}", "",
        "The full report is attached (" + ", ".join(f.upper() for f in sched.formats) + ").",
    ]
    return f"{sched.name} · {period}", "\n".join(lines), attachments


def deliver(db: Session, sched: ReportSchedule, now: datetime | None = None) -> None:
    """Build and send one report, then record the outcome on the schedule. Raises ReportError on failure
    after recording it, so the caller can show the message."""
    now = now or datetime.utcnow()
    smtp = get_settings()
    try:
        subject, text, attachments = build_message(db, sched, now)
        mailer.send_email(smtp, list(sched.recipients), subject, text, attachments)
    except mailer.ReportError as e:
        _record(db, sched, now, "failed", str(e))
        raise
    except Exception as e:                                           # report generation bug: keep it visible
        log.exception("report %s failed", sched.id)
        _record(db, sched, now, "failed", f"Could not build the report ({type(e).__name__}).")
        raise mailer.ReportError(sched.last_error)
    _record(db, sched, now, "sent", None)


def _record(db: Session, sched: ReportSchedule, now: datetime, status: str, error: str | None) -> None:
    sched.last_run_at, sched.last_status, sched.last_error = now, status, error
    db.commit()


def advance(sched: ReportSchedule, after: datetime) -> datetime:
    return next_run(sched.frequency, sched.send_time, sched.weekday, sched.month_day,
                    get_settings().report_timezone, after)
