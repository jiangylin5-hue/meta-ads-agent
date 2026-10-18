"""meta ads knowledge rag (retired)

Revision ID: 0002_meta_ads_rag
Revises: 0001_pg_db_foundation
Create Date: 2026-06-10
"""

from __future__ import annotations


revision = "0002_meta_ads_rag"
down_revision = "0001_pg_db_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This revision used to create the `meta_ads_knowledge_*` FTS tables for the
    # RAG retrieval layer. That layer was removed (ISSUE-26) and its tables are
    # dropped by 0005. `0001` already creates the full current schema via
    # `metadata.create_all`, so this revision is now a no-op kept only to
    # preserve the revision chain on databases that already applied it.
    pass


def downgrade() -> None:
    pass
