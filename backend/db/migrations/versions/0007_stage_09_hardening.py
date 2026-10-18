"""stage 09 backend hardening

Revision ID: 0007_stage_09_hardening
Revises: 0006_stage_09_context_memory
Create Date: 2026-10-18
"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa

from backend.db.schema import agent_turn_locks, agent_turns


revision = "0007_stage_09_hardening"
down_revision = "0006_stage_09_context_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("user_sessions", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("agent_tasks", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    if not context.is_offline_mode():
        agent_turns.create(bind, checkfirst=True)
        agent_turn_locks.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    if not context.is_offline_mode():
        agent_turn_locks.drop(bind, checkfirst=True)
        agent_turns.drop(bind, checkfirst=True)
    op.drop_column("agent_tasks", "version")
    op.drop_column("user_sessions", "version")