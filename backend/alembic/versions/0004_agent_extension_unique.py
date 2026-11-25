"""one agent per PBX extension (unique partial index)

Adds uq_agents_external_agent_id via the shared index list (app/core/indexes.py). Idempotent. If
existing data already has duplicate external_agent_id values the index is skipped with a warning
(resolve the duplicates, then re-run `alembic upgrade head`).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-25
"""
from alembic import op

from app.core.indexes import UNIQUE_INDEXES, ensure_indexes

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_indexes(op.get_bind())


def downgrade() -> None:
    for name, _table, _cols, _where in UNIQUE_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
