"""scheduled email reports

Adds the report_schedules table. Idempotent (checkfirst), so it is safe after create_all() already made it.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-26
"""
from alembic import op

from app.models.models import ReportSchedule

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ReportSchedule.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    ReportSchedule.__table__.drop(op.get_bind(), checkfirst=True)
