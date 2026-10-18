"""stage 09 context and agent memory

Revision ID: 0006_stage_09_context_memory
Revises: 0005_drop_dead_schema
Create Date: 2026-10-18
"""

from __future__ import annotations

from alembic import context, op

from backend.db.schema import (
    agent_memory_records,
    agent_tasks,
    mcp_tool_result_cache,
    meta_account_context_cache,
    meta_account_directory_cache,
)


revision = "0006_stage_09_context_memory"
down_revision = "0005_drop_dead_schema"
branch_labels = None
depends_on = None

CONTEXT_TABLES = [
    agent_tasks,
    agent_memory_records,
    mcp_tool_result_cache,
    meta_account_directory_cache,
    meta_account_context_cache,
]


def upgrade() -> None:
    bind = op.get_bind()
    if not context.is_offline_mode():
        for table in CONTEXT_TABLES:
            table.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(CONTEXT_TABLES):
        table.drop(bind, checkfirst=True)