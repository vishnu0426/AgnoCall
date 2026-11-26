"""Scheduled reports: create, change and send analytics reports by email (PDF and/or CSV)."""
import re
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy.orm import Session

from app.api.forms import require_auth
from app.api.settings import require_admin
from app.core.config import get_settings
from app.core.database import get_db
from app.core.ids import is_uuid
from app.models.models import ReportSchedule
from app.reports import mailer, schedule as sched_math, service

router = APIRouter(prefix="/report-schedules", tags=["Reports"])

MAX_SCHEDULES = 20
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


class ScheduleIn(BaseModel):
    name: str
    recipients: List[str]
    frequency: str
    send_time: str = "08:00"
    weekday: Optional[int] = None
    month_day: Optional[int] = None
    period_days: int = 7
    formats: List[str] = ["pdf", "csv"]
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 80:
            raise ValueError("Give the report a name (up to 80 characters).")
        return v

    @field_validator("recipients")
    @classmethod
    def _recipients(cls, v: List[str]) -> List[str]:
        cleaned = list(dict.fromkeys(a.strip().lower() for a in v if a.strip()))
        limit = get_settings().report_max_recipients
        if not cleaned:
            raise ValueError("Add at least one recipient email address.")
        if len(cleaned) > limit:
            raise ValueError(f"At most {limit} recipients per report.")
        bad = [a for a in cleaned if not _EMAIL.match(a) or len(a) > 254]
        if bad:
            raise ValueError(f"Not a valid email address: {bad[0]}")
        return cleaned

    @field_validator("frequency")
    @classmethod
    def _frequency(cls, v: str) -> str:
        if v not in sched_math.FREQUENCIES:
            raise ValueError("Frequency must be daily, weekly or monthly.")
        return v

    @field_validator("send_time")
    @classmethod
    def _time(cls, v: str) -> str:
        sched_math.parse_time(v)
        return v

    @field_validator("period_days")
    @classmethod
    def _period(cls, v: int) -> int:
        if v not in sched_math.PERIODS:
            raise ValueError("Period must be 7, 30 or 90 days, or 0 for all time.")
        return v

    @field_validator("formats")
    @classmethod
    def _formats(cls, v: List[str]) -> List[str]:
        v = [f for f in sched_math.FORMATS if f in {x.lower() for x in v}]
        if not v:
            raise ValueError("Pick PDF, CSV or both.")
        return v

    @model_validator(mode="after")
    def _day(self):
        # only keep the day field that applies, and insist on it
        if self.frequency == "weekly":
            if self.weekday is None or not 0 <= self.weekday <= 6:
                raise ValueError("Pick a day of the week.")
            self.month_day = None
        elif self.frequency == "monthly":
            if self.month_day is None or not 1 <= self.month_day <= 28:
                raise ValueError("Pick a day of the month between 1 and 28.")
            self.weekday = None
        else:
            self.weekday = self.month_day = None
        return self


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat(timespec="minutes") + "Z" if d else None


def _out(s: ReportSchedule) -> dict:
    return {
        "id": s.id, "name": s.name, "recipients": s.recipients, "frequency": s.frequency, "weekday": s.weekday,
        "month_day": s.month_day, "send_time": s.send_time, "period_days": s.period_days, "formats": s.formats,
        "enabled": s.enabled, "when": sched_math.describe(s.frequency, s.send_time, s.weekday, s.month_day),
        "next_run_at": _iso(s.next_run_at) if s.enabled else None, "last_run_at": _iso(s.last_run_at),
        "last_status": s.last_status, "last_error": s.last_error, "created_by": s.created_by,
    }


def _get(db: Session, schedule_id: str) -> ReportSchedule:
    s = db.get(ReportSchedule, schedule_id) if is_uuid(schedule_id) else None
    if s is None:
        raise HTTPException(404, "Report schedule not found.")
    return s


def _apply(s: ReportSchedule, body: ScheduleIn) -> None:
    s.name, s.recipients, s.frequency, s.send_time = body.name, body.recipients, body.frequency, body.send_time
    s.weekday, s.month_day, s.period_days, s.formats, s.enabled = (
        body.weekday, body.month_day, body.period_days, body.formats, body.enabled)
    s.next_run_at = service.advance(s, datetime.utcnow()) if s.enabled else None


@router.get("")
def list_schedules(db: Session = Depends(get_db), _user: dict = Depends(require_auth)):
    cfg = get_settings()
    return {
        # never the username or password
        "smtp": {"configured": mailer.smtp_configured(cfg), "host": cfg.smtp_host or None,
                 "from": cfg.smtp_from or None, "security": cfg.smtp_security},
        "timezone": cfg.report_timezone,
        "max_recipients": cfg.report_max_recipients,
        "items": [_out(s) for s in db.query(ReportSchedule).order_by(ReportSchedule.created_at).all()],
    }


@router.post("", status_code=201)
def create_schedule(body: ScheduleIn, db: Session = Depends(get_db), user: dict = Depends(require_admin)):
    if db.query(ReportSchedule).count() >= MAX_SCHEDULES:
        raise HTTPException(400, f"At most {MAX_SCHEDULES} scheduled reports. Delete one first.")
    s = ReportSchedule(created_by=str(user.get("username") or user.get("sub") or "")[:255] or None)
    _apply(s, body)
    db.add(s)
    db.commit()
    return _out(s)


@router.put("/{schedule_id}")
def update_schedule(schedule_id: str, body: ScheduleIn, db: Session = Depends(get_db), _a: dict = Depends(require_admin)):
    s = _get(db, schedule_id)
    _apply(s, body)
    db.commit()
    return _out(s)


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: str, db: Session = Depends(get_db), _a: dict = Depends(require_admin)):
    db.delete(_get(db, schedule_id))
    db.commit()
    return {"ok": True}


@router.post("/{schedule_id}/send-now")
def send_now(schedule_id: str, db: Session = Depends(get_db), _a: dict = Depends(require_admin)):
    """Send this report right now (a test, or a one-off). Does not change when it is next due."""
    s = _get(db, schedule_id)
    try:
        service.deliver(db, s)
    except mailer.ReportError as e:
        raise HTTPException(502, str(e))
    return _out(s)
