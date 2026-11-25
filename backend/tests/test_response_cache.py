"""Response cache: hits, write invalidation, allow-list, no caching of errors."""
import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.response_cache import ResponseCacheMiddleware


def make_app(ttl=60):
    app = FastAPI()
    app.add_middleware(ResponseCacheMiddleware, ttl_seconds=ttl)
    state = {"n": 0}

    @app.get("/api/v1/dashboard/summary")
    def cached():
        state["n"] += 1
        return {"n": state["n"]}

    @app.get("/api/v1/calls")
    def never_cached():
        state["n"] += 1
        return {"n": state["n"]}

    @app.get("/api/v1/agents")
    def boom():
        state["n"] += 1
        if state["n"] % 2:
            raise HTTPException(500, "fail")
        return {"n": state["n"]}

    @app.post("/api/v1/anything")
    def write():
        return {"ok": True}

    return app, state


def test_repeat_get_is_served_from_cache_and_varies_by_query():
    app, state = make_app()
    c = TestClient(app)
    a = c.get("/api/v1/dashboard/summary?days=7")
    b = c.get("/api/v1/dashboard/summary?days=7")
    other = c.get("/api/v1/dashboard/summary?days=30")
    assert a.json() == b.json() and b.headers["x-cache"] == "HIT" and a.headers["x-cache"] == "MISS"
    assert other.json() != a.json()


def test_write_empties_the_cache():
    app, _ = make_app()
    c = TestClient(app)
    first = c.get("/api/v1/dashboard/summary").json()
    c.post("/api/v1/anything")
    assert c.get("/api/v1/dashboard/summary").json() != first


def test_only_allow_listed_paths_are_cached():
    app, _ = make_app()
    c = TestClient(app)
    assert c.get("/api/v1/calls").json() != c.get("/api/v1/calls").json()


def test_errors_are_not_cached_and_ttl_zero_disables():
    app, _ = make_app()
    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/api/v1/agents").status_code == 500
    assert c.get("/api/v1/agents").status_code == 200       # not served the cached failure
    app0, _ = make_app(ttl=0)
    c0 = TestClient(app0)
    assert c0.get("/api/v1/dashboard/summary").json() != c0.get("/api/v1/dashboard/summary").json()
