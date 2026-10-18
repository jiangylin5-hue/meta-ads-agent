"""conversation memory foundation

Revision ID: 0003_conversation_memory
Revises: 0002_meta_ads_rag
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa

from backend.db.schema import conversation_memory_chunks


revision = "0003_conversation_memory"
down_revision = "0002_meta_ads_rag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    if not context.is_offline_mode():
        conversation_memory_chunks.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    conversation_memory_chunks.drop(bind, checkfirst=True)
