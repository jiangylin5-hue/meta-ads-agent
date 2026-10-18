"""stage 06 action contracts

Revision ID: 0004_stage_06_action_contracts
Revises: 0003_conversation_memory
Create Date: 2026-06-28
"""

from __future__ import annotations

from alembic import context, op

from backend.db.schema import (
    action_approval_events,
    action_audit_events,
    action_confirmation_events,
    action_execution_attempts,
    action_lifecycle_records,
    action_preflight_checks,
    action_rollback_notes,
)


revision = "0004_stage_06_action_contracts"
down_revision = "0003_conversation_memory"
branch_labels = None
depends_on = None


ACTION_TABLES = [
    action_lifecycle_records,
    action_preflight_checks,
    action_approval_events,
    action_confirmation_events,
    action_execution_attempts,
    action_audit_events,
    action_rollback_notes,
]


def upgrade() -> None:
    bind = op.get_bind()
    if not context.is_offline_mode():
        for table in ACTION_TABLES:
            table.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(ACTION_TABLES):
        table.drop(bind, checkfirst=True)
