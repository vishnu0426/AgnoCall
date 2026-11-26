"""No data is served without a sign-in. Fails when a route is added without a check."""
import time

import jwt
import pytest
from fastapi.routing import APIRoute

pytest.importorskip("celery")

from fastapi.testclient import TestClient  # noqa: E402

from app.core import auth  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

# (method, path) that a signed-out visitor may call. Keep this list short and justified.
PUBLIC = {
    ("POST", "/api/v1/auth/login"),     # how you sign in
    ("GET", "/health"),                  # liveness probe, returns nothing sensitive
}
# Guarded by their own scheme, not by a user token.
MACHINE = {
    ("POST", "/api/v1/internal/minio-webhook"),
    ("POST", "/api/v1/internal/backfill-insights"),
    ("POST", "/api/v1/internal/backfill-playback"),
}
# One endpoint for every GraphQL operation; each operation is checked by the RequireSignIn schema extension
# (tested below and in test_form_eval_graphql.py).
GRAPHQL = {("GET", "/api/v1/graphql"), ("POST", "/api/v1/graphql")}


def _guards(route: APIRoute) -> set:
    found, stack = set(), [route.dependant]
    while stack:
        d = stack.pop()
        if d.call is not None:
            found.add(d.call)
        stack.extend(d.dependencies)
    return found


def _routes():
    for r in app.routes:
        if isinstance(r, APIRoute):
            for m in r.methods - {"HEAD", "OPTIONS"}:
                yield m, r.path, r


def test_every_route_has_a_sign_in_check():
    open_routes = []
    for method, path, route in _routes():
        if (method, path) in PUBLIC | GRAPHQL:
            continue
        guards = _guards(route)
        if auth.require_auth in guards:
            continue
        if (method, path) in MACHINE and auth.require_internal_key in guards:
            continue
        open_routes.append(f"{method} {path}")
    assert not open_routes, "Routes without a sign-in check: " + ", ".join(sorted(open_routes))


def _token(role="admin", exp=600, secret=None):
    return jwt.encode({"id": 1, "username": "t", "role": role, "exp": int(time.time()) + exp},
                      secret or get_settings().forms_jwt_secret, algorithm="HS256")


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("path", ["/api/v1/calls", "/api/v1/dashboard/summary", "/api/v1/analytics/overview",
                                  "/api/v1/agents", "/api/v1/settings", "/api/v1/calls/export.csv",
                                  "/api/v1/report-schedules", "/api/v1/forms", "/api/v1/auth/me"])
def test_signed_out_requests_are_refused(client, path):
    assert client.get(path).status_code == 401


def test_bad_expired_and_forged_tokens_are_refused(client):
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nonsense"}).status_code == 403
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {_token(exp=-5)}"}).status_code == 403
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {_token(secret='x' * 40)}"}).status_code == 403
    no_exp = jwt.encode({"id": 1}, get_settings().forms_jwt_secret, algorithm="HS256")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {no_exp}"}).status_code == 403


def test_a_valid_token_gets_through(client):
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200 and r.json()["username"] == "t"


def test_cookie_works_for_reads_but_never_for_changes(client):
    client.cookies.set(auth.SESSION_COOKIE, _token())
    assert client.get("/api/v1/auth/me").status_code == 200
    # A cookie alone cannot change anything (another website could trigger such a request).
    assert client.put("/api/v1/settings/qa_target", json={"value": 1}).status_code == 401
    assert client.post("/api/v1/report-schedules/x/send-now").status_code == 401


def test_register_needs_an_administrator(client):
    body = {"username": "new", "password": "password123", "email": "a@b.co", "first_name": "A", "last_name": "B"}
    assert client.post("/api/v1/auth/register", json=body).status_code == 401
    r = client.post("/api/v1/auth/register", json=body, headers={"Authorization": f"Bearer {_token(role='agent')}"})
    assert r.status_code == 403


def test_internal_webhook_needs_the_key(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "")
    get_settings.cache_clear()
    assert client.post("/api/v1/internal/minio-webhook", json={}).status_code == 503      # not configured: closed
    monkeypatch.setenv("INTERNAL_API_KEY", "k" * 32)
    get_settings.cache_clear()
    assert client.post("/api/v1/internal/minio-webhook", json={}).status_code == 403
    assert client.post("/api/v1/internal/minio-webhook", json={},
                       headers={"Authorization": "Bearer wrong"}).status_code == 403
    get_settings.cache_clear()


def test_api_docs_are_off_by_default(client):
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(p).status_code == 404


def test_graphql_is_closed_to_signed_out_visitors(client):
    r = client.post("/api/v1/graphql", json={"query": "{ getEvaluationForms { id } }"})
    assert r.json().get("errors") and not (r.json().get("data") or {}).get("getEvaluationForms")
    assert client.post("/api/v1/graphql", json={"query": "{ __schema { types { name } } }"}).json().get("errors")


def test_sign_in_is_throttled(client):
    key = "testclient|nobody"
    for _ in range(auth.MAX_FAILS):
        auth.login_failed(key)
    assert auth.login_blocked(key)
    auth.login_succeeded(key)
    assert not auth.login_blocked(key)


def test_weak_signing_secret_is_detected(monkeypatch):
    monkeypatch.setenv("FORMS_JWT_SECRET", "form_builder_secret_key")
    get_settings.cache_clear()
    assert auth.secret_problem()
    monkeypatch.setenv("FORMS_JWT_SECRET", "x" * 40)
    get_settings.cache_clear()
    assert auth.secret_problem() is None
    get_settings.cache_clear()
