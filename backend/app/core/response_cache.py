"""
Short-lived response cache for the read-only summary endpoints.

Why: the database is a network hop away and every statement costs ~75 ms, so a dashboard
or analytics page spends ~1 s just asking the same questions again each time someone
switches page. Identical GETs inside a few seconds are answered from memory instead.

Safety rules:
  * only an allow-list of read-only GET endpoints is ever cached (never the call list or the
    live ingestion status);
  * only 200 responses are stored, bounded in size and count;
  * ANY write (POST/PUT/PATCH/DELETE) empties the cache first, so what a person just did
    (retry, review, rename, change a setting) is visible on their next page view;
  * the data is not per-user, so one shared entry per URL is correct;
  * staleness is bounded by the TTL (`RESPONSE_CACHE_SECONDS`, 0 = off). Each API process has its
    own cache, so with several workers another worker can lag by at most the TTL.
"""
import time
from typing import Dict, Tuple

CACHEABLE_PREFIXES = (
    "/api/v1/dashboard/summary",
    "/api/v1/dashboard/ai-evaluation",
    "/api/v1/analytics/overview",
    "/api/v1/compliance/summary",
    "/api/v1/calibration/summary",
    "/api/v1/calibration/sample",
    "/api/v1/review/queue",
    "/api/v1/failures/summary",
    "/api/v1/agents",
    "/api/v1/settings",
)
MAX_ENTRIES = 300
MAX_BODY_BYTES = 512 * 1024


class ResponseCacheMiddleware:
    def __init__(self, app, ttl_seconds: float):
        self.app = app
        self.ttl = ttl_seconds
        self._store: Dict[str, Tuple[float, int, list, bytes]] = {}

    def clear(self) -> None:
        self._store.clear()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.ttl <= 0:
            return await self.app(scope, receive, send)

        method = scope["method"]
        if method not in ("GET", "HEAD"):
            self._store.clear()                    # a write happened: never serve what it may have changed
            return await self.app(scope, receive, send)

        path = scope["path"]
        if method != "GET" or not path.startswith(CACHEABLE_PREFIXES):
            return await self.app(scope, receive, send)

        key = path + "?" + scope.get("query_string", b"").decode("latin-1")
        hit = self._store.get(key)
        now = time.monotonic()
        if hit and now - hit[0] < self.ttl:
            _, status, headers, body = hit
            await send({"type": "http.response.start", "status": status,
                        "headers": headers + [(b"x-cache", b"HIT")]})
            await send({"type": "http.response.body", "body": body})
            return

        captured = {"status": 0, "headers": [], "body": bytearray(), "ok": True}

        async def capture(message):
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
                captured["headers"] = list(message.get("headers", []))
                message = {**message, "headers": captured["headers"] + [(b"x-cache", b"MISS")]}
            elif message["type"] == "http.response.body":
                captured["body"].extend(message.get("body", b""))
                if message.get("more_body") or len(captured["body"]) > MAX_BODY_BYTES:
                    captured["ok"] = False         # streamed / too large: pass through, don't store
            await send(message)

        await self.app(scope, receive, capture)

        if captured["ok"] and captured["status"] == 200:
            if len(self._store) >= MAX_ENTRIES:
                self._store.clear()
            self._store[key] = (now, 200, captured["headers"], bytes(captured["body"]))
