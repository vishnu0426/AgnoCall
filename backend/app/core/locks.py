"""
Best-effort Redis locks for periodic jobs.

Used so a 1-second beat schedule can never stack: if one poll tick is still
running (slow MinIO / DB), the next ticks see the lock and return immediately
instead of piling up. Fails OPEN: if Redis is unreachable we run anyway (a
duplicate tick is harmless -- ingestion claims are atomic in the database),
because skipping work would be the worse failure.
"""
from app.core.config import get_settings

_PREFIX = "agnocall:lock:"


def _client():
    import redis
    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=1, socket_connect_timeout=1)


def acquire(name: str, ttl_seconds: int) -> bool:
    try:
        return bool(_client().set(_PREFIX + name, "1", nx=True, ex=max(1, int(ttl_seconds))))
    except Exception:
        return True


def release(name: str) -> None:
    try:
        _client().delete(_PREFIX + name)
    except Exception:
        pass
