"""One name per compliance rule, and the same recording is never analysed twice."""
import time

import jwt
import pytest

pytest.importorskip("celery")

from fastapi.testclient import TestClient  # noqa: E402

from app.core import compliance_rules as cr  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.database import get_db, get_read_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.models import Call, CallStatus, ComplianceViolation  # noqa: E402


def test_rule_names_and_categories_are_canonical():
    assert cr.normalise_code("Greeting missing") == "GREETING_MISSING"
    assert cr.normalise_code("identity-verification missing ") == "IDENTITY_VERIFICATION_MISSING"
    assert cr.normalise_code(None) == "UNKNOWN"
    for raw in ("Security", "security", "Identity Verification", "Process", "procedure", None):
        assert cr.rule_category("IDENTITY_VERIFICATION_MISSING", raw) == "Security"
        assert cr.rule_category("CLOSING_MISSING", raw) == "Process"
    assert cr.rule_label("GREETING_MISSING") == "Greeting missing"
    assert cr.rule_category("NEW_RULE", "call_structure") == "Call Structure"   # unknown rules keep a tidy category
    assert cr.rule_label("NEW_RULE") == "New rule"


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_read_db] = lambda: db
    tok = jwt.encode({"id": 1, "username": "t", "role": "admin", "exp": int(time.time()) + 600},
                     get_settings().forms_jwt_secret, algorithm="HS256")
    c = TestClient(app, headers={"Authorization": f"Bearer {tok}"})
    yield c
    app.dependency_overrides.clear()


def _call(db, name="a.wav"):
    c = Call(original_filename=name, storage_path="x", status=CallStatus.processed)
    db.add(c)
    db.commit()
    return c


def test_the_same_rule_is_one_row_whatever_category_the_ai_wrote(db, client):
    call = _call(db)
    for cat in ("Security", "security", "Identity Verification", "procedure"):
        db.add(ComplianceViolation(call_id=call.id, rule_code="IDENTITY_VERIFICATION_MISSING", category=cat,
                                   severity="high"))
    db.add(ComplianceViolation(call_id=call.id, rule_code="Greeting missing", category="Process", severity="low"))
    db.commit()
    body = client.get("/api/v1/compliance/summary").json()
    rows = {r["rule_code"]: r for r in body["by_rule"]}
    assert set(rows) == {"IDENTITY_VERIFICATION_MISSING", "GREETING_MISSING"}
    assert rows["IDENTITY_VERIFICATION_MISSING"] == {"rule_code": "IDENTITY_VERIFICATION_MISSING",
                                                     "label": "Identity not verified", "category": "Security", "count": 4}
    assert all(v["category"] in {"Security", "Process"} for v in body["recent_violations"])
    assert {v["rule_label"] for v in body["recent_violations"]} == {"Identity not verified", "Greeting missing"}


@pytest.fixture()
def uploads(monkeypatch):
    from app.api import calls as calls_api
    sent = []
    monkeypatch.setattr(calls_api.minio_client, "upload_audio", lambda cid, name, data, ctype: f"calls/{cid}/{name}")
    monkeypatch.setattr(calls_api.run_pipeline, "delay", lambda cid: sent.append(cid))
    return sent


def test_uploading_the_same_recording_twice_does_not_create_a_second_call(db, client, uploads):
    wav = b"RIFF....WAVEfmt " + b"\x01" * 64
    r1 = client.post("/api/v1/calls", files={"file": ("one.wav", wav, "audio/wav")})
    assert r1.status_code == 202 and r1.json()["duplicate"] is False
    r2 = client.post("/api/v1/calls", files={"file": ("renamed.wav", wav, "audio/wav")})
    assert r2.json()["duplicate"] is True and r2.json()["call_id"] == r1.json()["call_id"]
    assert db.query(Call).count() == 1 and len(uploads) == 1            # analysed once
    other = client.post("/api/v1/calls", files={"file": ("two.wav", wav + b"x", "audio/wav")})
    assert other.json()["duplicate"] is False and db.query(Call).count() == 2


def test_a_failed_earlier_upload_does_not_block_a_retry(db, client, uploads):
    wav = b"RIFF....WAVEfmt " + b"\x02" * 64
    first = client.post("/api/v1/calls", files={"file": ("a.wav", wav, "audio/wav")}).json()["call_id"]
    db.query(Call).filter(Call.id == first).update({"status": CallStatus.failed})
    db.commit()
    again = client.post("/api/v1/calls", files={"file": ("a.wav", wav, "audio/wav")}).json()
    assert again["duplicate"] is False and again["call_id"] != first
