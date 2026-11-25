"""Settings page API: read effective values, change them (admin only), change own password."""
import logging
from typing import Any, List, Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.forms import require_auth
from app.core import settings_store as store
from app.core.database import get_db, get_read_db
from app.models.models import AppSetting, FormBuilderUser

log = logging.getLogger("agnocall.settings")
router = APIRouter(prefix="/settings", tags=["Settings"])
account_router = APIRouter(prefix="/account", tags=["Account"])


class SettingOut(BaseModel):
    key: str
    group: str
    label: str
    help: str
    kind: str
    unit: str
    minimum: Optional[float]
    maximum: Optional[float]
    value: Any
    default: Any
    is_default: bool
    updated_by: Optional[str] = None
    updated_at: Optional[str] = None


class SettingIn(BaseModel):
    value: Any


class PasswordIn(BaseModel):
    current_password: str
    new_password: str


def require_admin(user: dict = Depends(require_auth)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Only administrators can change settings.")
    return user


def _default(key: str) -> Any:
    from app.core.config import get_settings
    return getattr(get_settings(), key, store.DEFAULTS_NOT_ON_SETTINGS.get(key))


def _out(db: Session) -> List[SettingOut]:
    rows = {r.key: r for r in db.query(AppSetting).all()}
    ov = store.overrides(db)
    items = []
    for d in store.REGISTRY.values():
        row = rows.get(d.key)
        default = _default(d.key)
        items.append(SettingOut(
            key=d.key, group=d.group, label=d.label, help=d.help, kind=d.kind, unit=d.unit,
            minimum=d.minimum, maximum=d.maximum,
            value=ov.get(d.key, default), default=default, is_default=d.key not in ov,
            updated_by=row.updated_by if row and d.key in ov else None,
            updated_at=row.updated_at.isoformat() if row and row.updated_at and d.key in ov else None,
        ))
    return items


@router.get("", response_model=List[SettingOut])
def list_settings(db: Session = Depends(get_read_db)):
    return _out(db)


@router.put("/{key}", response_model=List[SettingOut])
def update_setting(key: str, payload: SettingIn, db: Session = Depends(get_db), user: dict = Depends(require_admin)):
    d = store.REGISTRY.get(key)
    if d is None:
        raise HTTPException(404, "Unknown setting")
    try:
        value = store.coerce(d, payload.value)
    except ValueError as e:
        raise HTTPException(400, str(e))
    who = user.get("username") or "unknown"
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    old = row.value if row else _default(key)
    if row:
        row.value, row.updated_by = value, who
    else:
        db.add(AppSetting(key=key, value=value, updated_by=who))
    db.commit()
    store.invalidate()
    log.info("setting_changed key=%s old=%r new=%r by=%s", key, old, value, who)
    return _out(db)


@router.delete("/{key}", response_model=List[SettingOut])
def reset_setting(key: str, db: Session = Depends(get_db), user: dict = Depends(require_admin)):
    if key not in store.REGISTRY:
        raise HTTPException(404, "Unknown setting")
    db.query(AppSetting).filter(AppSetting.key == key).delete()
    db.commit()
    store.invalidate()
    log.info("setting_reset key=%s by=%s", key, user.get("username"))
    return _out(db)


@account_router.post("/change-password")
def change_password(payload: PasswordIn, db: Session = Depends(get_db), user: dict = Depends(require_auth)):
    if len(payload.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters.")
    if payload.new_password == payload.current_password:
        raise HTTPException(400, "New password must be different from the current one.")
    row = db.query(FormBuilderUser).filter(FormBuilderUser.id == user.get("id")).first()
    if not row or not row.password or not bcrypt.checkpw(payload.current_password.encode(), row.password.encode()):
        raise HTTPException(400, "Current password is incorrect.")
    row.password = bcrypt.hashpw(payload.new_password.encode(), bcrypt.gensalt(rounds=10)).decode()
    db.commit()
    log.info("password_changed user=%s", row.username)
    return {"ok": True}
