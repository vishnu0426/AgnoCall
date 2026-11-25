import time

from sqlalchemy import create_engine, event
from sqlalchemy.exc import DisconnectionError
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import get_settings

settings = get_settings()

# No pool_pre_ping: it pings the database on EVERY checkout, and when the database is a network hop
# away that is a wasted round trip per request. See `_ping_if_idle` below for the cheaper equivalent.
_engine_kwargs = {"pool_pre_ping": False, "future": True}
if not settings.database_url.startswith("sqlite"):
    # Sized pool + recycling: avoids per-request connection setup and stale
    # connections after a DB/proxy idle timeout. (SQLite, used only in tests,
    # doesn't take these arguments.)
    _engine_kwargs.update(pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow,
                          pool_recycle=600)
engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

# A connection that has been idle this long is checked before use (it may have been dropped by the
# database, a proxy or a firewall). A busy connection is not pinged: that was the wasted round trip.
IDLE_PING_SECONDS = 30


@event.listens_for(engine, "checkout")
def _ping_if_idle(dbapi_connection, connection_record, connection_proxy):
    now = time.monotonic()
    last = connection_record.info.get("last_checkout")
    connection_record.info["last_checkout"] = now
    if last is None or now - last < IDLE_PING_SECONDS:
        return
    try:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SELECT 1")
        finally:
            cursor.close()
        # The ping opened a transaction. End it before the connection is handed out: a read-only
        # (AUTOCOMMIT) session cannot switch a connection that is still inside one, and fails with
        # "can't change 'autocommit' now: connection in transaction status INTRANS".
        dbapi_connection.rollback()
    except Exception as exc:                 # dead connection: the pool discards it and opens a new one
        raise DisconnectionError() from exc


# Read-only requests (every GET) use AUTOCOMMIT: no BEGIN before the first statement and no
# ROLLBACK when the connection goes back to the pool. Each is a network round trip, so a
# one-query request used to cost three. It shares the same pool. Trade-off: the statements of one
# request no longer share a snapshot, which is irrelevant for dashboards and lists.
read_engine = engine.execution_options(isolation_level="AUTOCOMMIT")
ReadSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=read_engine, future=True)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_read_db():
    """For GET endpoints that never write (see ReadSessionLocal)."""
    db = ReadSessionLocal()
    try:
        yield db
    finally:
        db.close()
