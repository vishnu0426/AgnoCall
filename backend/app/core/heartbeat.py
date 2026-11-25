"""
Tiny liveness markers in Redis ("the MinIO webhook fired at T", "the poller ran
at T") so the UI can show whether ingestion is actually healthy. Best-effort
by design: if Redis is unreachable, beating is a silent no-op and reading
returns None -- observability must never break ingestion.
"""
import time
from functools import lru_cache

from app.core.config import get_settings

_PREFIX = "agnocall:heartbeat:"


@lru_cache(maxsize=1)
def _client():
    """One shared client (it owns a connection pool): opening a new connection per call cost
    a TCP handshake -- plus the IPv6 fallback delay on Windows -- every time."""
    import redis
    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=1, socket_connect_timeout=1,
                                decode_responses=True)


def beat(name: str) -> None:
    try:
        _client().set(_PREFIX + name, str(time.time()), ex=7 * 24 * 3600)
    except Exception:
        pass


def last_beat(name: str) -> float | None:
    """Epoch seconds of the last beat, or None if never / Redis unavailable."""
    try:
        value = _client().get(_PREFIX + name)
        return float(value) if value else None
    except Exception:
        return None


def last_beats(*names: str) -> list:
    """Several beats in ONE round trip; each is epoch seconds or None."""
    try:
        values = _client().mget([_PREFIX + n for n in names])
        return [float(v) if v else None for v in values]
    except Exception:
        return [None] * len(names)
