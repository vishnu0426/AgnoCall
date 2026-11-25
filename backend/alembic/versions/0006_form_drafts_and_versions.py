"""form drafts and published-version history

Adds the draft columns to rec_app_evaluation_forms and the rec_app_evaluation_form_versions table.
Idempotent, so it is safe after the legacy startup shim already added them.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

DRAFT_COLUMNS = (
    ("draft_content", "JSONB"),
    ("draft_title", "VARCHAR(255)"),
    ("draft_ai_enabled", "BOOLEAN"),
    ("draft_updated_at", "TIMESTAMPTZ"),
    ("draft_updated_by", "INTEGER"),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for name, ddl in DRAFT_COLUMNS:
        op.execute(f"ALTER TABLE rec_app_evaluation_forms ADD COLUMN IF NOT EXISTS {name} {ddl}")
    if "rec_app_evaluation_form_versions" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "rec_app_evaluation_form_versions",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True),
            sa.Column("form_id", sa.String(255), nullable=False),
            sa.Column("version", sa.Integer, nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("form_content", JSONB, nullable=False),
            sa.Column("published_by", sa.Integer, nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("form_id", "version", name="uq_form_version"),
        )
        op.create_index("ix_form_versions_form_id", "rec_app_evaluation_form_versions", ["form_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS rec_app_evaluation_form_versions")
    for name, _ in DRAFT_COLUMNS:
        op.execute(f"ALTER TABLE rec_app_evaluation_forms DROP COLUMN IF EXISTS {name}")
