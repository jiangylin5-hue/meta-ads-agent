"""postgresql database foundation

Revision ID: 0001_pg_db_foundation
Revises:
Create Date: 2026-06-10
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa

from backend.db.schema import metadata


revision = "0001_pg_db_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    metadata.create_all(bind)


def downgrade() -> None:
    if os.getenv("ADS_AGENT_ALLOW_DESTRUCTIVE_MIGRATION") != "yes":
        raise RuntimeError(
            "Downgrade would drop the Stage 03 application schema. "
            "Set ADS_AGENT_ALLOW_DESTRUCTIVE_MIGRATION=yes only for an intentional local reset."
        )
    bind = op.get_bind()
    metadata.drop_all(bind)
