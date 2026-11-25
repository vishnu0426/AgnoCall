"""form-driven AI evaluation

Adds the columns/index/enum value used by tasks/form_eval.py. Every statement
is idempotent (IF NOT EXISTS), so it is safe on a database that already
received these changes from the legacy startup shim in app/main.py, and on a
fresh one where 0001 already created them.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-25
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # DDL below is PostgreSQL-specific (IF NOT EXISTS, partial index, ALTER TYPE)

    op.execute("ALTER TABLE rec_app_evaluation_forms ADD COLUMN IF NOT EXISTS ai_enabled BOOLEAN NOT NULL DEFAULT false")
    op.execute("ALTER TABLE rec_app_evaluation_forms ADD COLUMN IF NOT EXISTS ai_enabled_by INTEGER")
    op.execute("ALTER TABLE rec_app_evaluation_forms ADD COLUMN IF NOT EXISTS ai_enabled_at TIMESTAMPTZ")
    op.execute("ALTER TABLE rec_app_evaluation_forms ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1")

    op.execute("ALTER TABLE rec_app_evaluation_responses ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'human'")
    op.execute("ALTER TABLE rec_app_evaluation_responses ADD COLUMN IF NOT EXISTS form_version INTEGER")
    op.execute("ALTER TABLE rec_app_evaluation_responses ADD COLUMN IF NOT EXISTS evidence JSONB")
    # One AI evaluation per (call, form).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_eval_response_ai_call_form "
        "ON rec_app_evaluation_responses (call_id, form_id) WHERE source = 'ai'"
    )

    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on older
    # PostgreSQL versions, hence the autocommit block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE jobstage ADD VALUE IF NOT EXISTS 'form_eval'")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS uq_eval_response_ai_call_form")
    for col in ("evidence", "form_version", "source"):
        op.execute(f"ALTER TABLE rec_app_evaluation_responses DROP COLUMN IF EXISTS {col}")
    for col in ("version", "ai_enabled_at", "ai_enabled_by", "ai_enabled"):
        op.execute(f"ALTER TABLE rec_app_evaluation_forms DROP COLUMN IF EXISTS {col}")
    # A Postgres enum value cannot be removed; 'form_eval' is left in place (harmless).
