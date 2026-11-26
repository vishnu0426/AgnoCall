"""keep the speaker (channel / diarization cluster) apart from the resolved role

Adds transcript_segments.speaker_id. Idempotent.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-26
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE transcript_segments ADD COLUMN IF NOT EXISTS speaker_id VARCHAR")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE transcript_segments DROP COLUMN IF EXISTS speaker_id")
