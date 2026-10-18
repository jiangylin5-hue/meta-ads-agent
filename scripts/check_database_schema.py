from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.db.schema import metadata


REQUIRED_TABLES = {
    "organizations",
    "users",
    "clients",
    "external_connections",
    "meta_ad_accounts",
    "meta_account_snapshots",
    "meta_campaigns",
    "meta_adsets",
    "meta_ads",
    "meta_creatives",
    "meta_insight_rows",
    "user_sessions",
    "chat_messages",
    "conversation_memory_chunks",
    "agent_traces",
    "agent_tasks",
    "agent_turns",
    "agent_turn_locks",
    "agent_memory_records",
    "mcp_tool_result_cache",
    "meta_account_directory_cache",
    "meta_account_context_cache",
    "agent_trace_steps",
    "feedback_events",
    "creative_assets",
    "batch_launch_drafts",
    "batch_draft_entities",
    "optimization_action_drafts",
    "action_lifecycle_records",
    "action_preflight_checks",
    "action_approval_events",
    "action_confirmation_events",
    "action_execution_attempts",
    "action_audit_events",
    "action_rollback_notes",
    "approvals",
    "execution_logs",
    "execution_log_entities",
    "rollback_records",
    "audit_reports",
}

REQUIRED_FOREIGN_KEYS = {
    ("clients", "organization_id", "organizations.id"),
    ("external_connections", "organization_id", "organizations.id"),
    ("external_connections", "client_id", "clients.id"),
    ("meta_ad_accounts", "client_id", "clients.id"),
    ("meta_ad_accounts", "connection_id", "external_connections.id"),
    ("meta_account_snapshots", "client_id", "clients.id"),
    ("meta_account_snapshots", "account_id", "meta_ad_accounts.id"),
    ("meta_campaigns", "account_id", "meta_ad_accounts.id"),
    ("meta_campaigns", "last_seen_snapshot_id", "meta_account_snapshots.id"),
    ("meta_adsets", "account_id", "meta_ad_accounts.id"),
    ("meta_adsets", "campaign_id", "meta_campaigns.id"),
    ("meta_adsets", "last_seen_snapshot_id", "meta_account_snapshots.id"),
    ("meta_ads", "account_id", "meta_ad_accounts.id"),
    ("meta_ads", "campaign_id", "meta_campaigns.id"),
    ("meta_ads", "adset_id", "meta_adsets.id"),
    ("meta_ads", "creative_id", "meta_creatives.id"),
    ("meta_ads", "last_seen_snapshot_id", "meta_account_snapshots.id"),
    ("meta_creatives", "account_id", "meta_ad_accounts.id"),
    ("meta_insight_rows", "snapshot_id", "meta_account_snapshots.id"),
    ("meta_insight_rows", "account_id", "meta_ad_accounts.id"),
    ("user_sessions", "user_id", "users.id"),
    ("user_sessions", "client_id", "clients.id"),
    ("user_sessions", "selected_account_id", "meta_ad_accounts.id"),
    ("chat_messages", "session_id", "user_sessions.id"),
    ("conversation_memory_chunks", "session_id", "user_sessions.id"),
    ("conversation_memory_chunks", "message_id", "chat_messages.id"),
    ("conversation_memory_chunks", "client_id", "clients.id"),
    ("conversation_memory_chunks", "account_id", "meta_ad_accounts.id"),
    ("agent_tasks", "session_id", "user_sessions.id"),
    ("agent_turns", "session_id", "user_sessions.id"),
    ("agent_turn_locks", "session_id", "user_sessions.id"),
    ("agent_turn_locks", "turn_id", "agent_turns.id"),
    ("agent_memory_records", "user_id", "users.id"),
    ("agent_memory_records", "source_session_id", "user_sessions.id"),
    ("agent_memory_records", "source_message_id", "chat_messages.id"),
    ("agent_traces", "session_id", "user_sessions.id"),
    ("agent_trace_steps", "trace_id", "agent_traces.trace_id"),
    ("feedback_events", "session_id", "user_sessions.id"),
    ("creative_assets", "account_id", "meta_ad_accounts.id"),
    ("batch_launch_drafts", "client_id", "clients.id"),
    ("batch_launch_drafts", "account_id", "meta_ad_accounts.id"),
    ("batch_launch_drafts", "session_id", "user_sessions.id"),
    ("batch_draft_entities", "draft_id", "batch_launch_drafts.id"),
    ("optimization_action_drafts", "client_id", "clients.id"),
    ("optimization_action_drafts", "account_id", "meta_ad_accounts.id"),
    ("optimization_action_drafts", "session_id", "user_sessions.id"),
    ("action_lifecycle_records", "account_id", "meta_ad_accounts.id"),
    ("action_lifecycle_records", "created_by", "users.id"),
    ("action_preflight_checks", "action_id", "action_lifecycle_records.id"),
    ("action_approval_events", "action_id", "action_lifecycle_records.id"),
    ("action_approval_events", "approver", "users.id"),
    ("action_confirmation_events", "action_id", "action_lifecycle_records.id"),
    ("action_confirmation_events", "confirmed_by", "users.id"),
    ("action_execution_attempts", "action_id", "action_lifecycle_records.id"),
    ("action_audit_events", "action_id", "action_lifecycle_records.id"),
    ("action_audit_events", "actor", "users.id"),
    ("action_rollback_notes", "action_id", "action_lifecycle_records.id"),
    ("action_rollback_notes", "created_by", "users.id"),
    ("approvals", "actor_user_id", "users.id"),
    ("execution_logs", "client_id", "clients.id"),
    ("execution_logs", "account_id", "meta_ad_accounts.id"),
    ("execution_logs", "actor_user_id", "users.id"),
    ("execution_logs", "before_snapshot_id", "meta_account_snapshots.id"),
    ("execution_logs", "after_snapshot_id", "meta_account_snapshots.id"),
    ("execution_log_entities", "execution_id", "execution_logs.id"),
    ("rollback_records", "execution_id", "execution_logs.id"),
    ("rollback_records", "actor_user_id", "users.id"),
    ("audit_reports", "client_id", "clients.id"),
    ("audit_reports", "account_id", "meta_ad_accounts.id"),
    ("audit_reports", "snapshot_id", "meta_account_snapshots.id"),
}

REQUIRED_UNIQUES = {
    "uq_users_email",
    "uq_clients_org_name",
    "uq_external_connections_client_provider_user",
    "uq_meta_ad_accounts_client_provider_account",
    "uq_meta_campaigns_account_provider_id",
    "uq_meta_adsets_account_provider_id",
    "uq_meta_ads_account_provider_id",
    "uq_meta_creatives_account_provider_id",
    "uq_batch_draft_entities_draft_ref",
    "uq_agent_traces_trace_id",
    "uq_agent_turns_session_idempotency",
    "uq_mcp_tool_result_cache_key",
    "uq_meta_account_context_cache_account",
    "uq_action_lifecycle_account_entity_operation_active",
    "uq_action_execution_attempts_idempotency",
}

REQUIRED_INDEXES = {
    "ix_meta_account_snapshots_account_date",
    "ix_meta_insight_rows_account_entity_date",
    "ix_chat_messages_session_created",
    "ix_conversation_memory_session_type_created",
    "ix_conversation_memory_client_account_created",
    "ix_conversation_memory_embedding",
    "ix_agent_tasks_session_status_updated",
    "ix_agent_turns_session_status_updated",
    "ix_agent_memory_scope_status_updated",
    "ix_agent_memory_account_kind_updated",
    "ix_mcp_tool_result_account_tool_expiry",
    "ix_meta_account_context_expiry",
    "ix_agent_trace_steps_trace_created",
    "ix_feedback_events_session_type_created",
    "ux_creative_assets_account_meta_asset",
    "ix_action_lifecycle_account_status_updated",
    "ix_action_lifecycle_workspace_created",
    "ix_action_preflight_action_checked",
    "ix_action_approval_events_action_created",
    "ix_action_confirmation_events_action_created",
    "ix_action_execution_attempts_idempotency",
    "ix_action_execution_attempts_action_created",
    "ix_action_audit_events_action_created",
    "ix_action_rollback_notes_action_created",
    "ix_approvals_target_created",
    "ix_execution_logs_source",
    "ix_execution_logs_client_account_created",
    "ix_audit_reports_account_type_created",
}


def check_schema() -> list[str]:
    errors: list[str] = []
    missing_tables = sorted(REQUIRED_TABLES.difference(metadata.tables))
    errors.extend([f"missing table: {name}" for name in missing_tables])

    actual_fks = {
        (table.name, column.name, fk.target_fullname)
        for table in metadata.tables.values()
        for column in table.columns
        for fk in column.foreign_keys
    }
    for item in sorted(REQUIRED_FOREIGN_KEYS.difference(actual_fks)):
        errors.append(f"missing foreign key: {item[0]}.{item[1]} -> {item[2]}")

    actual_unique_names = {
        constraint.name
        for table in metadata.tables.values()
        for constraint in table.constraints
        if constraint.name
    }
    for name in sorted(REQUIRED_UNIQUES.difference(actual_unique_names)):
        errors.append(f"missing unique constraint: {name}")
    actual_index_names = {
        index.name
        for table in metadata.tables.values()
        for index in table.indexes
        if index.name
    }
    for name in sorted(REQUIRED_INDEXES.difference(actual_index_names)):
        errors.append(f"missing index: {name}")
    return errors


def main() -> int:
    errors = check_schema()
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"Database schema check passed: {len(metadata.tables)} tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
