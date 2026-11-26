"""
Who is calling? One place decides, so no route can quietly skip the check.

- `require_auth`: a valid sign-in token (HS256, signed with FORMS_JWT_SECRET) is required.
  It is read from `Authorization: Bearer <token>`. For plain GET/HEAD requests only, the `forms_session`
  cookie is also accepted, because a browser download link (the CSV export) cannot send a header.
  Cookies are never accepted for requests that change data, so another website cannot make a signed-in
  person's browser do that.
- `require_internal_key`: for machine callers (the MinIO webhook). Needs INTERNAL_API_KEY in .env.
"""
import hmac
import time
from typing import Optional

import jwt
from fastapi import Header, HTTPException, Request

from app.core.config import get_settings

SESSION_COOKIE = "forms_session"


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    return authorization.split(" ", 1)[1] if " " in authorization else authorization


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_settings().forms_jwt_secret, algorithms=["HS256"], options={"require": ["exp"]})


def user_from_request(request: Request) -> Optional[dict]:
    """The signed-in user, or None. Never raises."""
    token = _bearer(request.headers.get("authorization"))
    if token is None and request.method in ("GET", "HEAD"):
        token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        return decode_token(token)
    except jwt.PyJWTError:
        return None


def require_auth(request: Request, authorization: str = Header(default=None)) -> dict:
    """401 without a token, 403 when the token is invalid or expired."""
    token = _bearer(authorization)
    if token is None and request.method in ("GET", "HEAD"):
        token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in required")
    try:
        return decode_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=403, detail="Invalid or expired session")


def require_internal_key(authorization: str = Header(default=None), x_internal_key: str = Header(default=None)) -> None:
    """MinIO sends its webhook `auth_token` as `Authorization: Bearer <token>`; other callers may use X-Internal-Key."""
    expected = get_settings().internal_api_key
    if not expected:
        raise HTTPException(status_code=503, detail="INTERNAL_API_KEY is not configured")
    given = x_internal_key or _bearer(authorization) or ""
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Invalid internal key")


# ---- sign-in throttle: slows password guessing (per process, in memory) -------------------------------
_FAILS: dict[str, list[float]] = {}
MAX_FAILS, WINDOW_SECONDS = 8, 300


def login_blocked(key: str) -> bool:
    now = time.time()
    recent = [t for t in _FAILS.get(key, []) if now - t < WINDOW_SECONDS]
    _FAILS[key] = recent
    return len(recent) >= MAX_FAILS


def login_failed(key: str) -> None:
    _FAILS.setdefault(key, []).append(time.time())


def login_succeeded(key: str) -> None:
    _FAILS.pop(key, None)


WEAK_SECRETS = {"form_builder_secret_key", "changeme", "secret", ""}


def secret_problem() -> Optional[str]:
    s = get_settings().forms_jwt_secret
    if s in WEAK_SECRETS or len(s) < 32:
        return "FORMS_JWT_SECRET is the public default or shorter than 32 characters: anyone can forge a sign-in token."
    return None
