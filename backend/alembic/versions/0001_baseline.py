"""baseline: schema as created by Base.metadata.create_all()

Until now the schema was created by create_all() at app startup (plus a few
ad-hoc ALTERs). This revision adopts that schema:

  * EXISTING database (created by the app):  alembic stamp 0001
  * EMPTY database:                          alembic upgrade head
    (creates every table at the current model definition, then 0002 is a no-op)

Revision ID: 0001
Revises:
Create Date: 2026-11-25
"""
from alembic import op

from app.core.database import Base
from app.models import models  # noqa: F401

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    raise NotImplementedError("The baseline is never downgraded; restore from backup instead.")
