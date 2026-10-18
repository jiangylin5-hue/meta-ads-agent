"""drop dead schema

Revision ID: 0005_drop_dead_schema
Revises: 0004_stage_06_action_contracts
Create Date: 2026-10-16

Drops tables that no runtime code ever read or wrote (ISSUE-09, ISSUE-10, ISSUE-26):
- meta_ads_knowledge_sources / _chunks / _rules: backed the removed RAG retrieval layer.
- organization_memberships / account_permissions: multi-tenant and permission skeleton (abandoned).
- connection_secrets: unused encrypted-secret store.
- meta_sync_jobs: declared background-sync table with no scheduler.
- workspace_artifacts: unused workspace artifact store.
- db_migration_audit: redundant migration ledger (alembic_version already tracks revisions).

Also removes the now-orphaned `meta_account_snapshots.sync_job_id` foreign key column.
"""

from __future__ import annotations

from alembic import op


revision = "0005_drop_dead_schema"
down_revision = "0004_stage_06_action_contracts"
branch_labels = None
depends_on = None


DROP_TABLES_IN_ORDER = (
    "meta_ads_knowledge_rules",
    "meta_ads_knowledge_chunks",
    "meta_ads_knowledge_sources",
    "connection_secrets",
    "account_permissions",
    "organization_memberships",
    "workspace_artifacts",
    "meta_sync_jobs",
    "db_migration_audit",
)


def upgrade() -> None:
    # `meta_account_snapshots.sync_job_id` referenced `meta_sync_jobs`; drop it before the table.
    op.execute("ALTER TABLE IF EXISTS meta_account_snapshots DROP COLUMN IF EXISTS sync_job_id")
    for table_name in DROP_TABLES_IN_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")


def downgrade() -> None:
    raise RuntimeError(
        "0005_drop_dead_schema is irreversible: the dropped tables served no runtime purpose "
        "and cannot be reconstructed from application data."
    )
