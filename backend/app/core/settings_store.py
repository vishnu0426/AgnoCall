"""
Runtime settings editable from the UI.

`.env` stays the default; a row in `app_settings` overrides it without a restart. Only keys in
REGISTRY can be stored, each with a type and range, so a bad value is rejected at the door.
"""
import time
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.models import AppSetting


@dataclass(frozen=True)
class Def:
    key: str            # also the attribute name on Settings
    group: str
    label: str
    help: str
    kind: str           # "float" | "int" | "bool"
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    unit: str = ""


REGISTRY: dict[str, Def] = {d.key: d for d in [
    Def("qa_target_score", "Quality targets", "QA score target",
        "Average QA score the team should reach. Shown on the dashboard.", "float", 0, 100, "points"),
    Def("compliance_target_percent", "Quality targets", "Compliance target",
        "Share of calls with no compliance flag the team should reach.", "float", 0, 100, "%"),
    Def("review_low_confidence", "Quality targets", "Low AI confidence below",
        "Calls where the AI's average confidence is under this appear in 'Needs review'.", "float", 0.05, 0.95, "0-1"),
    Def("calibration_target_reviews", "Quality targets", "Reviews needed for calibration",
        "How many hand-scored calls before the calibration numbers are treated as reliable.", "int", 5, 200, "calls"),
    Def("analytics_min_words", "Analytics", "Real conversation: minimum words",
        "Calls with fewer spoken words (IVR surveys, 'hello?' calls) are left out of the averages and counted separately.",
        "int", 0, 500, "words"),
    Def("analytics_min_seconds", "Analytics", "Real conversation: minimum length",
        "Calls shorter than this are left out of the averages and counted separately.", "int", 0, 300, "seconds"),
    Def("ai_form_eval_enabled", "AI evaluation", "AI form evaluation",
        "Master switch. Off stops all AI form scoring immediately.", "bool"),
    Def("ai_form_eval_max_enabled_forms", "AI evaluation", "Max AI-enabled forms",
        "Every enabled form adds one AI call to every recording, so this caps cost.", "int", 1, 10, "forms"),
    Def("ai_form_eval_require_admin", "AI evaluation", "Only signed-in admins can enable / run AI",
        "Turn on once everyone who needs it can sign in.", "bool"),
]}


def coerce(d: Def, raw: Any) -> Any:
    """Validate a submitted value; raises ValueError with a message safe to show."""
    if d.kind == "bool":
        if isinstance(raw, bool):
            return raw
        raise ValueError(f"{d.label} must be on or off.")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{d.label} must be a number.")
    val = int(raw) if d.kind == "int" else float(raw)
    if d.kind == "int" and float(raw) != val:
        raise ValueError(f"{d.label} must be a whole number.")
    if (d.minimum is not None and val < d.minimum) or (d.maximum is not None and val > d.maximum):
        raise ValueError(f"{d.label} must be between {d.minimum:g} and {d.maximum:g}.")
    return val


_cache: dict = {"at": 0.0, "value": None}
CACHE_SECONDS = 5.0


def invalidate() -> None:
    """Call after a write so this process sees it immediately (other processes lag <= CACHE_SECONDS)."""
    _cache["value"] = None


def overrides(db: Session) -> dict[str, Any]:
    """Stored overrides. Cached briefly: almost every dashboard request reads them, and each read
    is a database round trip."""
    now = time.monotonic()
    if _cache["value"] is not None and now - _cache["at"] < CACHE_SECONDS:
        return dict(_cache["value"])
    value = _load_overrides(db)
    _cache.update(at=now, value=value)
    return dict(value)


def _load_overrides(db: Session) -> dict[str, Any]:
    out = {}
    for row in db.query(AppSetting).all():
        d = REGISTRY.get(row.key)
        if d is None:
            continue
        try:
            out[row.key] = coerce(d, row.value)
        except ValueError:      # a hand-edited bad row must not break the app: fall back to .env
            continue
    return out


def effective(db: Session) -> Settings:
    """The `.env` settings with any UI overrides applied (a copy; the cached original is untouched)."""
    base = get_settings()
    ov = overrides(db)
    # settings that are not on Settings yet fall through via the helper below
    known = {k: v for k, v in ov.items() if k in Settings.model_fields}
    return base.model_copy(update=known) if known else base


def value_of(db: Session, key: str) -> Any:
    """One setting's effective value, including ones that only exist in the registry."""
    ov = overrides(db)
    if key in ov:
        return ov[key]
    return getattr(get_settings(), key, DEFAULTS_NOT_ON_SETTINGS.get(key))


DEFAULTS_NOT_ON_SETTINGS = {"review_low_confidence": 0.6, "calibration_target_reviews": 20}
