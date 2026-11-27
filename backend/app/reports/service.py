"""Build a scheduled report and send it."""
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.api.analytics import analytics_overview
from app.core.config import get_settings
from app.models.models import ReportSchedule
from app.reports import email_html, mailer, render
from app.reports.schedule import next_run

log = logging.getLogger("agnocall.reports")

MIME = {"pdf": "application/pdf", "csv": "text/csv"}


def build_message(db: Session, sched: ReportSchedule, now: datetime, test: bool = False) -> tuple[str, str, str, list]:
    """(subject, plain text, html, attachments). `test` marks it as a try-out of an unsaved schedule."""
    cfg = get_settings()
    overview = analytics_overview(days=sched.period_days or None, agent_id=None, attention=False, db=db)
    generated = now.strftime("%d %b %Y, %H:%M UTC")
    period = render.period_label(overview.days)
    attachments = []
    stem = "agnocall-report-" + now.strftime("%Y%m%d")
    for fmt in sched.formats:
        data = (render.build_pdf if fmt == "pdf" else render.build_csv)(overview, sched.name, generated)
        attachments.append((f"{stem}.{fmt}", data, MIME[fmt]))
    k = overview.kpis
    message = cfg.report_message.replace("\\n", "\n").strip()
    quality = render.quality_sentence(overview)
    kpis = [
        ("Average AI QA score", str(k["avg_qa_score"]) if k["avg_qa_score"] is not None else "-"),
        ("Negative endings", f"{k['negative_end_percent']}%" if k["negative_end_percent"] is not None else "-"),
        ("Follow-ups", str(k["follow_up_required"])),
    ]
    attached = "The full report is attached (" + ", ".join(f.upper() for f in sched.formats) + ")."
    period_line = f"{period}, generated {generated}"
    company = cfg.report_company
    footer = [
        "-" * 40,
        f"Sent automatically by AgnoCall for {company}. This report contains call data: please do not forward it "
        f"outside {company}.",
        "Please do not reply to this message; the mailbox is not monitored.",
    ]
    lines = [
        *(["[TEST] This is a test of a schedule that has not been saved. Nothing is scheduled yet.", ""] if test else []),
        *([message, "", "-" * 40, ""] if message else []),
        f"{sched.name}", period_line, "", quality, "",
        *(f"{label}: {value}" for label, value in kpis), "", attached, "", *footer,
    ]
    html = email_html.build_html(intro=message, title=sched.name, period_line=period_line, quality=quality,
                                 kpis=kpis, attached=attached, company=company, test=test)
    subject = f"{sched.name} · {period}"
    return ("[TEST] " + subject if test else subject), "\n".join(lines), html, attachments


def deliver(db: Session, sched: ReportSchedule, now: datetime | None = None) -> None:
    """Build and send one report, then record the outcome on the schedule. Raises ReportError on failure
    after recording it, so the caller can show the message."""
    now = now or datetime.utcnow()
    smtp = get_settings()
    try:
        subject, text, html, attachments = build_message(db, sched, now)
        mailer.send_email(smtp, list(sched.recipients), subject, text, attachments, html)
    except mailer.ReportError as e:
        _record(db, sched, now, "failed", str(e))
        raise
    except Exception as e:                                           # report generation bug: keep it visible
        log.exception("report %s failed", sched.id)
        _record(db, sched, now, "failed", f"Could not build the report ({type(e).__name__}).")
        raise mailer.ReportError(sched.last_error)
    _record(db, sched, now, "sent", None)


def send_test(db: Session, body: dict, now: datetime | None = None) -> None:
    """Send one report for a schedule that is NOT saved. Nothing is written to the database."""
    now = now or datetime.utcnow()
    sched = ReportSchedule(name=body["name"], recipients=body["recipients"], formats=body["formats"],
                           period_days=body["period_days"])
    try:
        subject, text, html, attachments = build_message(db, sched, now, test=True)
        mailer.send_email(get_settings(), list(sched.recipients), subject, text, attachments, html)
    except mailer.ReportError:
        raise
    except Exception as e:
        log.exception("test report failed")
        raise mailer.ReportError(f"Could not build the report ({type(e).__name__}).")


def _record(db: Session, sched: ReportSchedule, now: datetime, status: str, error: str | None) -> None:
    sched.last_run_at, sched.last_status, sched.last_error = now, status, error
    db.commit()


def advance(sched: ReportSchedule, after: datetime) -> datetime:
    return next_run(sched.frequency, sched.send_time, sched.weekday, sched.month_day,
                    get_settings().report_timezone, after)
