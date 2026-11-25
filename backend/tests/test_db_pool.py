"""The idle-connection ping must leave the connection clean, or read-only (AUTOCOMMIT) sessions fail."""
import pytest
from sqlalchemy.exc import DisconnectionError

from app.core import database


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql):
        if self.conn.dead:
            raise RuntimeError("server closed the connection")
        self.conn.events.append(("execute", sql))
        self.conn.in_transaction = True      # psycopg opens a transaction on the first statement

    def close(self):
        self.conn.events.append(("close",))


class FakeConn:
    def __init__(self, dead=False):
        self.dead, self.events, self.in_transaction = dead, [], False

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.events.append(("rollback",))
        self.in_transaction = False


class Record:
    def __init__(self):
        self.info = {}


def _idle(monkeypatch):
    monkeypatch.setattr(database.time, "monotonic", lambda: database.IDLE_PING_SECONDS + 5.0)


def test_busy_connection_is_not_pinged():
    conn, rec = FakeConn(), Record()
    database._ping_if_idle(conn, rec, None)          # first checkout of a new connection
    database._ping_if_idle(conn, rec, None)          # reused straight away
    assert conn.events == []


def test_idle_connection_is_pinged_and_handed_out_outside_a_transaction(monkeypatch):
    conn, rec = FakeConn(), Record()
    rec.info["last_checkout"] = 0.0                  # idle for ages
    _idle(monkeypatch)
    database._ping_if_idle(conn, rec, None)
    assert ("execute", "SELECT 1") in conn.events
    assert conn.in_transaction is False, "left in a transaction: AUTOCOMMIT sessions would fail with INTRANS"


def test_dead_idle_connection_is_discarded(monkeypatch):
    conn, rec = FakeConn(dead=True), Record()
    rec.info["last_checkout"] = 0.0
    _idle(monkeypatch)
    with pytest.raises(DisconnectionError):
        database._ping_if_idle(conn, rec, None)
