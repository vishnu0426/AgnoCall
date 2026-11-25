"""UI-editable settings: validation, overrides reaching their consumers, admin gate, password change."""
import bcrypt
import pytest
from fastapi import HTTPException

pytest.importorskip("celery")

from app.api import calibration, dashboard, settings as sapi  # noqa: E402
from app.core import settings_store as store  # noqa: E402
from app.models.models import FormBuilderUser  # noqa: E402

ADMIN = {"id": 1, "username": "admin", "role": "admin"}


def by_key(items):
    return {i.key: i for i in items}


def test_defaults_come_from_env(db):
    s = by_key(sapi.list_settings(db))
    assert s["qa_target_score"].value == 80 and s["qa_target_score"].is_default
    assert s["calibration_target_reviews"].value == 20


def test_admin_override_reaches_dashboard_and_can_be_reset(db):
    sapi.update_setting("qa_target_score", sapi.SettingIn(value=65), db, ADMIN)
    assert dashboard.dashboard_summary(db).qa_target == 65
    s = by_key(sapi.list_settings(db))["qa_target_score"]
    assert not s.is_default and s.updated_by == "admin"
    sapi.reset_setting("qa_target_score", db, ADMIN)
    assert dashboard.dashboard_summary(db).qa_target == 80


@pytest.mark.parametrize("key,bad", [
    ("qa_target_score", 500), ("qa_target_score", -1), ("qa_target_score", "80"), ("qa_target_score", True),
    ("calibration_target_reviews", 7.5), ("ai_form_eval_enabled", 1), ("review_low_confidence", 0),
])
def test_bad_values_are_rejected(db, key, bad):
    with pytest.raises(HTTPException) as e:
        sapi.update_setting(key, sapi.SettingIn(value=bad), db, ADMIN)
    assert e.value.status_code == 400


def test_unknown_key_404(db):
    with pytest.raises(HTTPException) as e:
        sapi.update_setting("database_url", sapi.SettingIn(value=1), db, ADMIN)
    assert e.value.status_code == 404


def test_only_admin_passes_gate():
    with pytest.raises(HTTPException) as e:
        sapi.require_admin({"id": 2, "role": "agent"})
    assert e.value.status_code == 403
    assert sapi.require_admin(ADMIN) is ADMIN


def test_calibration_target_is_used(db):
    sapi.update_setting("calibration_target_reviews", sapi.SettingIn(value=50), db, ADMIN)
    s = calibration.calibration_summary(db)
    assert s.target_reviews == 50 and "at least 50" in s.verdict_text


def test_effective_does_not_mutate_cached_env_settings(db):
    from app.core.config import get_settings
    sapi.update_setting("ai_form_eval_max_enabled_forms", sapi.SettingIn(value=7), db, ADMIN)
    assert store.effective(db).ai_form_eval_max_enabled_forms == 7
    assert get_settings().ai_form_eval_max_enabled_forms == 3


def test_password_change(db):
    hashed = bcrypt.hashpw(b"oldpassword", bcrypt.gensalt(rounds=4)).decode()
    u = FormBuilderUser(username="admin", password=hashed, role="admin")
    db.add(u)
    db.commit()
    me = {"id": u.id, "username": "admin", "role": "admin"}
    with pytest.raises(HTTPException):   # wrong current
        sapi.change_password(sapi.PasswordIn(current_password="nope", new_password="newpassword1"), db, me)
    with pytest.raises(HTTPException):   # too short
        sapi.change_password(sapi.PasswordIn(current_password="oldpassword", new_password="short"), db, me)
    with pytest.raises(HTTPException):   # unchanged
        sapi.change_password(sapi.PasswordIn(current_password="oldpassword", new_password="oldpassword"), db, me)
    sapi.change_password(sapi.PasswordIn(current_password="oldpassword", new_password="newpassword1"), db, me)
    db.refresh(u)
    assert bcrypt.checkpw(b"newpassword1", u.password.encode())
