"""Scheduled reports: when they are due, what is sent, how it is sent, and who may change them."""
import smtplib
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

pytest.importorskip("celery")
pytest.importorskip("reportlab")

from app.api import reports as api  # noqa: E402
from app.api.analytics import analytics_overview  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.models.models import CallClassification, ReportSchedule  # noqa: E402
from app.reports import mailer, render, schedule, service  # noqa: E402
from app.tasks import reports as task  # noqa: E402
from tests.test_analytics_page import speak  # noqa: E402
from tests.test_dashboard_calibration_api import mk  # noqa: E402

IST = "Asia/Kolkata"           # UTC+5:30, no daylight saving: easy to reason about


def utc(*a):
    return datetime(*a)


# ---- when is a report due ------------------------------------------------------------

def test_daily_picks_today_if_still_ahead_else_tomorrow():
    # 08:00 IST is 02:30 UTC. At 01:00 UTC (06:30 IST) today's 08:00 is still ahead.
    assert schedule.next_run("daily", "08:00", None, None, IST, utc(2026, 11, 26, 1, 0)) == utc(2026, 11, 26, 2, 30)
    assert schedule.next_run("daily", "08:00", None, None, IST, utc(2026, 11, 26, 3, 0)) == utc(2026, 11, 27, 2, 30)


def test_it_is_strictly_after_so_a_report_cannot_fire_twice():
    due = utc(2026, 11, 26, 2, 30)
    assert schedule.next_run("daily", "08:00", None, None, IST, due) == utc(2026, 11, 27, 2, 30)


def test_weekly_goes_to_the_chosen_weekday():
    # 26 Nov 2026 is a Thursday; Monday is 30 Nov.
    assert schedule.next_run("weekly", "08:00", 0, None, IST, utc(2026, 11, 26, 3, 0)) == utc(2026, 11, 30, 2, 30)
    # same weekday, time already passed -> next week
    assert schedule.next_run("weekly", "08:00", 3, None, IST, utc(2026, 11, 26, 3, 0)) == utc(2026, 12, 3, 2, 30)


def test_monthly_rolls_over_the_year():
    assert schedule.next_run("monthly", "08:00", None, 5, IST, utc(2026, 11, 26, 3, 0)) == utc(2026, 12, 5, 2, 30)
    assert schedule.next_run("monthly", "08:00", None, 5, IST, utc(2026, 12, 15, 3, 0)) == utc(2027, 1, 5, 2, 30)


def test_bad_times_and_days_are_rejected():
    for bad in ("8:00", "24:00", "08:60", "", "ab:cd"):
        with pytest.raises(ValueError):
            schedule.parse_time(bad)
    with pytest.raises(ValueError):
        schedule.next_run("weekly", "08:00", None, None, IST, utc(2026, 1, 1))
    with pytest.raises(ValueError):
        schedule.next_run("monthly", "08:00", None, 31, IST, utc(2026, 1, 1))


# ---- input validation ------------------------------------------------------------------

def body(**kw):
    base = dict(name="Weekly QA", recipients=["a@x.com"], frequency="weekly", weekday=0, send_time="08:00")
    return api.ScheduleIn(**{**base, **kw})


def test_valid_schedule_is_cleaned():
    b = body(recipients=[" A@X.com ", "a@x.com", "b@y.org"], formats=["CSV", "pdf", "pdf"])
    assert b.recipients == ["a@x.com", "b@y.org"] and b.formats == ["pdf", "csv"]


@pytest.mark.parametrize("kw", [
    {"recipients": []}, {"recipients": ["not-an-email"]}, {"recipients": ["a@x.com\nBcc: evil@x.com"]},
    {"formats": []}, {"formats": ["docx"]}, {"frequency": "hourly"}, {"period_days": 5}, {"name": "  "},
    {"weekday": None}, {"weekday": 9}, {"send_time": "25:00"},
    {"frequency": "monthly", "month_day": 31}, {"recipients": [f"u{i}@x.com" for i in range(21)]},
])
def test_invalid_schedules_are_refused(kw):
    with pytest.raises(ValidationError):
        body(**kw)


def test_only_the_relevant_day_field_is_kept():
    assert body(frequency="daily").weekday is None
    assert body(frequency="monthly", month_day=3).weekday is None


# ---- the report ------------------------------------------------------------------------

@pytest.fixture()
def overview(db):
    c = speak(db, mk(db, "real.wav", qa=80))
    db.add(CallClassification(call_id=c.id, category="=cmd|' /C calc'!A0"))     # hostile category name
    db.commit()
    return analytics_overview(db=db)


def test_pdf_is_a_real_pdf(overview):
    pdf = render.build_pdf(overview, "Weekly QA", "26 Nov 2026, 08:00 UTC")
    assert pdf.startswith(b"%PDF") and len(pdf) > 1500


def test_csv_opens_in_excel_and_blocks_formula_injection(overview):
    data = render.build_csv(overview, "Weekly QA", "now")
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    assert "Average AI QA score,80.0" in text and "'=cmd" in text and "\n=cmd" not in text


def test_report_name_is_not_trusted_in_a_formula_cell(overview):
    assert render.build_csv(overview, "=1+1", "now").decode("utf-8-sig").splitlines()[0] == "'=1+1"


# ---- sending ---------------------------------------------------------------------------

class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.context, self.calls, self.sent = host, port, context, [], None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user))
        if password == "wrong":
            raise smtplib.SMTPAuthenticationError(535, b"nope")

    def send_message(self, msg):
        self.sent = msg


@pytest.fixture()
def smtp(monkeypatch):
    FakeSMTP.instances.clear()
    cfg = get_settings()
    for k, v in dict(smtp_host="smtp.test", smtp_port=587, smtp_security="starttls", smtp_username="u",
                     smtp_password="p", smtp_from="AgnoCall <reports@x.com>").items():
        monkeypatch.setattr(cfg, k, v)
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    return cfg


def test_email_has_both_attachments_and_uses_starttls_and_login(db, smtp):
    s = ReportSchedule(name="Weekly QA", recipients=["a@x.com", "b@y.org"], frequency="daily", send_time="08:00",
                       period_days=7, formats=["pdf", "csv"], enabled=True)
    db.add(s)
    db.commit()
    speak(db, mk(db, "real.wav", qa=80))
    service.deliver(db, s, utc(2026, 11, 26, 8, 0))
    srv = FakeSMTP.instances[0]
    assert srv.calls == ["starttls", ("login", "u")]
    msg = srv.sent
    assert msg["To"] == "a@x.com, b@y.org" and msg["From"] == "AgnoCall <reports@x.com>"
    assert "Last 7 days" in msg["Subject"]
    names = sorted(p.get_filename() for p in msg.iter_attachments())
    assert names == ["agnocall-report-20261126.csv", "agnocall-report-20261126.pdf"]
    assert s.last_status == "sent" and s.last_error is None


def test_single_format_means_a_single_attachment(db, smtp):
    s = ReportSchedule(name="CSV only", recipients=["a@x.com"], frequency="daily", send_time="08:00",
                       period_days=0, formats=["csv"], enabled=True)
    db.add(s)
    db.commit()
    service.deliver(db, s)
    assert [p.get_filename()[-4:] for p in FakeSMTP.instances[0].sent.iter_attachments()] == [".csv"]


def test_ssl_mode_does_not_also_starttls(db, smtp, monkeypatch):
    monkeypatch.setattr(smtp, "smtp_security", "ssl")
    mailer.send_email(smtp, ["a@x.com"], "s", "t", [])
    assert "starttls" not in FakeSMTP.instances[0].calls


def test_no_login_without_a_username(smtp, monkeypatch):
    monkeypatch.setattr(smtp, "smtp_username", "")
    mailer.send_email(smtp, ["a@x.com"], "s", "t", [])
    assert ("login", "") not in FakeSMTP.instances[0].calls and FakeSMTP.instances[0].sent is not None


def test_wrong_password_gives_a_clear_message_without_leaking_it(db, smtp, monkeypatch):
    monkeypatch.setattr(smtp, "smtp_password", "wrong")
    s = ReportSchedule(name="r", recipients=["a@x.com"], frequency="daily", send_time="08:00", period_days=7,
                       formats=["csv"], enabled=True)
    db.add(s)
    db.commit()
    with pytest.raises(mailer.ReportError) as e:
        service.deliver(db, s)
    assert "username or password" in str(e.value) and "wrong" not in str(e.value)
    assert s.last_status == "failed" and "username or password" in s.last_error


def test_unreachable_server_is_reported(db, smtp, monkeypatch):
    def boom(*a, **k):
        raise ConnectionRefusedError()
    monkeypatch.setattr(mailer.smtplib, "SMTP", boom)
    with pytest.raises(mailer.ReportError) as e:
        mailer.send_email(smtp, ["a@x.com"], "s", "t", [])
    assert "smtp.test:587" in str(e.value)


def test_not_configured_says_what_to_set(monkeypatch):
    cfg = get_settings()
    monkeypatch.setattr(cfg, "smtp_host", "")
    assert not mailer.smtp_configured(cfg)
    with pytest.raises(mailer.ReportError) as e:
        mailer.send_email(cfg, ["a@x.com"], "s", "t", [])
    assert "SMTP_HOST" in str(e.value)


# ---- the API ---------------------------------------------------------------------------

def test_create_list_update_delete(db, smtp):
    out = api.create_schedule(body(), db=db, user={"username": "admin"})
    assert out["next_run_at"] and out["when"] == "Every Monday at 08:00" and out["created_by"] == "admin"
    listing = api.list_schedules(db=db, _user={})
    assert listing["smtp"]["configured"] is True and listing["smtp"]["host"] == "smtp.test"
    assert "password" not in str(listing).lower() and "username" not in str(listing["smtp"])
    upd = api.update_schedule(out["id"], body(frequency="daily", name="Daily"), db=db, _a={})
    assert upd["when"] == "Every day at 08:00" and upd["weekday"] is None
    off = api.update_schedule(out["id"], body(enabled=False), db=db, _a={})
    assert off["next_run_at"] is None
    api.delete_schedule(out["id"], db=db, _a={})
    assert api.list_schedules(db=db, _user={})["items"] == []


def test_unknown_or_malformed_id_is_a_404(db):
    for bad in ("nope", "00000000-0000-0000-0000-000000000000"):
        with pytest.raises(HTTPException) as e:
            api.delete_schedule(bad, db=db, _a={})
        assert e.value.status_code == 404


def test_schedule_count_is_capped(db):
    for i in range(api.MAX_SCHEDULES):
        api.create_schedule(body(name=f"r{i}"), db=db, user={})
    with pytest.raises(HTTPException) as e:
        api.create_schedule(body(), db=db, user={})
    assert e.value.status_code == 400


def test_send_now_success_and_failure(db, smtp, monkeypatch):
    out = api.create_schedule(body(), db=db, user={})
    before = db.get(ReportSchedule, out["id"]).next_run_at
    res = api.send_now(out["id"], db=db, _a={})
    assert res["last_status"] == "sent" and db.get(ReportSchedule, out["id"]).next_run_at == before
    monkeypatch.setattr(smtp, "smtp_host", "")
    with pytest.raises(HTTPException) as e:
        api.send_now(out["id"], db=db, _a={})
    assert e.value.status_code == 502 and "SMTP_HOST" in e.value.detail
    assert db.get(ReportSchedule, out["id"]).last_status == "failed"


# ---- the beat task ---------------------------------------------------------------------

@pytest.fixture()
def run_task(db, smtp, monkeypatch):
    monkeypatch.setattr(task, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    return task.run_due_reports


def due_schedule(db, **kw):
    s = ReportSchedule(name="r", recipients=["a@x.com"], frequency="daily", send_time="08:00", period_days=7,
                       formats=["csv"], enabled=True, next_run_at=datetime.utcnow() - timedelta(minutes=1), **kw)
    db.add(s)
    db.commit()
    return s


def test_due_report_is_sent_once_and_rescheduled(db, run_task):
    s = due_schedule(db)
    assert run_task() == 1 and len(FakeSMTP.instances) == 1
    assert s.next_run_at > datetime.utcnow() and s.last_status == "sent"
    assert run_task() == 0 and len(FakeSMTP.instances) == 1            # the next tick finds nothing due


def test_missed_days_send_one_report_not_a_backlog(db, run_task):
    s = due_schedule(db)
    s.next_run_at = datetime.utcnow() - timedelta(days=5)
    db.commit()
    assert run_task() == 1 and run_task() == 0


def test_disabled_and_future_schedules_are_skipped(db, run_task):
    s = due_schedule(db)
    s.enabled = False
    future = due_schedule(db)
    future.next_run_at = datetime.utcnow() + timedelta(hours=1)
    db.commit()
    assert run_task() == 0 and FakeSMTP.instances == []


def test_a_failed_send_is_recorded_and_still_rescheduled(db, run_task, monkeypatch):
    monkeypatch.setattr(get_settings(), "smtp_host", "")
    s = due_schedule(db)
    assert run_task() == 0
    assert s.last_status == "failed" and "SMTP_HOST" in s.last_error and s.next_run_at > datetime.utcnow()


# ---- the standard message and the full-analytics PDF -------------------------------------

def _schedule(db, **kw):
    s = ReportSchedule(name="Weekly QA", recipients=["a@x.com"], frequency="daily", send_time="08:00",
                       period_days=7, formats=["csv"], enabled=True, **kw)
    db.add(s)
    db.commit()
    return s


def test_every_email_starts_with_the_one_standard_message(db, smtp):
    s = _schedule(db)
    service.deliver(db, s)
    body = FakeSMTP.instances[0].sent.get_body().get_content()
    assert body.startswith("Hello,\n\nHere is your scheduled AgnoCall analytics report.")
    assert "Weekly QA" in body and "The full report is attached (CSV)." in body


def test_message_from_env_turns_backslash_n_into_line_breaks(db, smtp, monkeypatch):
    monkeypatch.setattr(smtp, "report_message", "Hi team,\n\nPlease read this.")
    service.deliver(db, _schedule(db))
    assert FakeSMTP.instances[0].sent.get_body().get_content().startswith("Hi team,\n\nPlease read this.\n")


def test_an_empty_message_is_left_out(db, smtp, monkeypatch):
    monkeypatch.setattr(smtp, "report_message", "")
    service.deliver(db, _schedule(db))
    assert FakeSMTP.instances[0].sent.get_body().get_content().startswith("Weekly QA\n")


def pdf_text(data: bytes) -> str:
    import base64
    import re
    import zlib
    out = b""
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        raw = m.group(1).strip()
        try:
            if raw.endswith(b"~>"):                         # reportlab writes ASCII85 + Flate
                raw = base64.a85decode(raw[:-2])
            out += zlib.decompress(raw)
        except Exception:
            pass
    return out.decode("latin-1")


def test_pdf_contains_the_analytics_not_just_a_link(db):
    from app.models.models import Call, SentimentAnalysis, EmotionAnalysis
    c = speak(db, mk(db, "real.wav", qa=80))
    db.add(CallClassification(call_id=c.id, category="billing"))
    db.add(SentimentAnalysis(call_id=c.id, overall_sentiment="negative", end_sentiment="negative"))
    db.add(EmotionAnalysis(call_id=c.id, dominant_customer_emotion="frustration"))
    db.commit()
    o = analytics_overview(db=db, days=30)
    pdf = render.build_pdf(o, "Weekly QA", "now")
    text = pdf_text(pdf)
    for heading in ("Key metrics", "Categories", "Sentiment trend", "Customer emotions", "Call volume",
                    "QA calibration"):
        assert heading in text, heading
    assert "Billing" in text and "Frustration" in text
    assert "Open Analytics" not in text and len(pdf) > 4000


def test_pdf_still_builds_with_no_data_at_all(db):
    o = analytics_overview(db=db)
    pdf = render.build_pdf(o, "Empty", "now")
    assert pdf.startswith(b"%PDF") and "Key metrics" in pdf_text(pdf)


def test_csv_also_carries_trend_emotions_and_calibration(db):
    from app.models.models import EmotionAnalysis, SentimentAnalysis
    c = speak(db, mk(db, "real.wav", qa=80))
    db.add(SentimentAnalysis(call_id=c.id, overall_sentiment="positive", end_sentiment="positive"))
    db.add(EmotionAnalysis(call_id=c.id, dominant_customer_emotion="calm"))
    db.commit()
    text = render.build_csv(analytics_overview(db=db, days=30), "r", "now").decode("utf-8-sig")
    assert "Day,Positive,Neutral,Negative" in text and "Customer emotion,Calls" in text
    assert "QA calibration (AI vs human reviewers)" in text
