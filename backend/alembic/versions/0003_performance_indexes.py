"""performance indexes (foreign keys + hot filters)

PostgreSQL does not index foreign keys automatically; the calls list, dashboard
and per-call pages join `calls` to ~17 result tables by call_id. The index list
lives in app/core/indexes.py (shared with the dev startup shim). Idempotent.

NOTE: on a large production database build these during a quiet window, or
replace with CREATE INDEX CONCURRENTLY (plain CREATE INDEX blocks writes).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-25
"""
from alembic import op

from app.core.indexes import INDEXES, ensure_indexes

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_indexes(op.get_bind())


def downgrade() -> None:
    for name, _table, _cols in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
