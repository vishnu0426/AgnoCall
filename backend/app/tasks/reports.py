"""Beat task: send every scheduled report that is due."""
import logging
from datetime import datetime

from app.core.database import SessionLocal
from app.models.models import ReportSchedule
from app.reports import mailer, service
from app.tasks.celery_app import celery_app

log = logging.getLogger("agnocall.reports")


@celery_app.task(name="app.tasks.reports.run_due_reports")
def run_due_reports() -> int:
    """Called every minute by beat. A schedule is claimed by moving its `next_run_at` forward in the same
    UPDATE that matches the old value, so two workers (or a retried tick) can never send it twice. If the
    system was down, a missed report is sent once, not once per missed day."""
    sent = 0
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        due = db.query(ReportSchedule).filter(ReportSchedule.enabled.is_(True), ReportSchedule.next_run_at <= now).all()
        for s in due:
            claimed = db.query(ReportSchedule).filter(
                ReportSchedule.id == s.id, ReportSchedule.next_run_at == s.next_run_at,
            ).update({"next_run_at": service.advance(s, now)}, synchronize_session=False)
            db.commit()
            if not claimed:
                continue
            db.refresh(s)
            try:
                service.deliver(db, s, now)
                sent += 1
            except mailer.ReportError as e:
                log.warning("scheduled report %s not sent: %s", s.id, e)
    finally:
        db.close()
    return sent
