from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import UserDefinedType


metadata = MetaData()


class Vector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_kw: object) -> str:
        return f"vector({self.dimensions})"

organizations = Table(
    "organizations",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("status", String, nullable=False, default="active"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

users = Table(
    "users",
    metadata,
    Column("id", String, primary_key=True),
    Column("email", String, nullable=False),
    Column("display_name", String, nullable=False, default=""),
    Column("status", String, nullable=False, default="active"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("email", name="uq_users_email"),
)

clients = Table(
    "clients",
    metadata,
    Column("id", String, primary_key=True),
    Column("organization_id", ForeignKey("organizations.id"), nullable=False),
    Column("name", String, nullable=False),
    Column("status", String, nullable=False, default="active"),
    Column("metadata_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("organization_id", "name", name="uq_clients_org_name"),
)

external_connections = Table(
    "external_connections",
    metadata,
    Column("id", String, primary_key=True),
    Column("organization_id", ForeignKey("organizations.id"), nullable=False),
    Column("client_id", ForeignKey("clients.id"), nullable=False),
    Column("provider", String, nullable=False),
    Column("provider_user_id", String, nullable=False, default=""),
    Column("provider_user_name", String, nullable=False, default=""),
    Column("status", String, nullable=False),
    Column("scopes_json", JSONB, nullable=False, default=list),
    Column("token_fingerprint_json", JSONB, nullable=False, default=dict),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("client_id", "provider", "provider_user_id", name="uq_external_connections_client_provider_user"),
)

meta_ad_accounts = Table(
    "meta_ad_accounts",
    metadata,
    Column("id", String, primary_key=True),
    Column("client_id", ForeignKey("clients.id"), nullable=False),
    Column("connection_id", ForeignKey("external_connections.id"), nullable=True),
    Column("provider_account_id", String, nullable=False),
    Column("name", String, nullable=False, default=""),
    Column("currency", String, nullable=False, default=""),
    Column("timezone_name", String, nullable=False, default=""),
    Column("business_id", String, nullable=False, default=""),
    Column("business_name", String, nullable=False, default=""),
    Column("status", String, nullable=False, default="active"),
    Column("last_synced_at", DateTime(timezone=True), nullable=True),
    Column("raw_payload_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("client_id", "provider_account_id", name="uq_meta_ad_accounts_client_provider_account"),
)

meta_account_snapshots = Table(
    "meta_account_snapshots",
    metadata,
    Column("id", String, primary_key=True),
    Column("client_id", ForeignKey("clients.id"), nullable=False),
    Column("account_id", ForeignKey("meta_ad_accounts.id"), nullable=False),
    Column("provider", String, nullable=False),
    Column("date_preset", String, nullable=False),
    Column("account_json", JSONB, nullable=False, default=dict),
    Column("campaigns_json", JSONB, nullable=False, default=list),
    Column("adsets_json", JSONB, nullable=False, default=list),
    Column("ads_json", JSONB, nullable=False, default=list),
    Column("creatives_json", JSONB, nullable=False, default=list),
    Column("insights_json", JSONB, nullable=False, default=dict),
    Column("breakdowns_json", JSONB, nullable=False, default=dict),
    Column("data_quality_json", JSONB, nullable=False, default=list),
    Column("row_counts_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_meta_account_snapshots_account_date", meta_account_snapshots.c.account_id, meta_account_snapshots.c.date_preset, meta_account_snapshots.c.created_at)

meta_campaigns = Table(
    "meta_campaigns",
    metadata,
    Column("id", String, primary_key=True),
    Column("account_id", ForeignKey("meta_ad_accounts.id"), nullable=False),
    Column("provider_campaign_id", String, nullable=False),
    Column("name", String, nullable=False, default=""),
    Column("objective", String, nullable=False, default=""),
    Column("status", String, nullable=False, default=""),
    Column("effective_status", String, nullable=False, default=""),
    Column("daily_budget", Numeric, nullable=True),
    Column("last_seen_snapshot_id", ForeignKey("meta_account_snapshots.id"), nullable=True),
    Column("raw_payload_json", JSONB, nullable=False, default=dict),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("account_id", "provider_campaign_id", name="uq_meta_campaigns_account_provider_id"),
)

meta_adsets = Table(
    "meta_adsets",
    metadata,
    Column("id", String, primary_key=True),
    Column("account_id", ForeignKey("meta_ad_accounts.id"), nullable=False),
    Column("campaign_id", ForeignKey("meta_campaigns.id"), nullable=True),
    Column("provider_adset_id", String, nullable=False),
    Column("name", String, nullable=False, default=""),
    Column("status", String, nullable=False, default=""),
    Column("effective_status", String, nullable=False, default=""),
    Column("optimization_goal", String, nullable=False, default=""),
    Column("billing_event", String, nullable=False, default=""),
    Column("daily_budget", Numeric, nullable=True),
    Column("targeting_json", JSONB, nullable=False, default=dict),
    Column("last_seen_snapshot_id", ForeignKey("meta_account_snapshots.id"), nullable=True),
    Column("raw_payload_json", JSONB, nullable=False, default=dict),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("account_id", "provider_adset_id", name="uq_meta_adsets_account_provider_id"),
)

meta_creatives = Table(
    "meta_creatives",
    metadata,
    Column("id", String, primary_key=True),
    Column("account_id", ForeignKey("meta_ad_accounts.id"), nullable=False),
    Column("provider_creative_id", String, nullable=False),
    Column("name", String, nullable=False, default=""),
    Column("media_type", String, nullable=False, default=""),
    Column("thumbnail_url", Text, nullable=False, default=""),
    Column("image_url", Text, nullable=False, default=""),
    Column("object_story_id", String, nullable=False, default=""),
    Column("raw_payload_json", JSONB, nullable=False, default=dict),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("account_id", "provider_creative_id", name="uq_meta_creatives_account_provider_id"),
)

meta_ads = Table(
    "meta_ads",
    metadata,
    Column("id", String, primary_key=True),
    Column("account_id", ForeignKey("meta_ad_accounts.id"), nullable=False),
    Column("campaign_id", ForeignKey("meta_campaigns.id"), nullable=True),
    Column("adset_id", ForeignKey("meta_adsets.id"), nullable=True),
    Column("creative_id", ForeignKey("meta_creatives.id"), nullable=True),
    Column("provider_ad_id", String, nullable=False),
    Column("name", String, nullable=False, default=""),
    Column("status", String, nullable=False, default=""),
    Column("effective_status", String, nullable=False, default=""),
    Column("last_seen_snapshot_id", ForeignKey("meta_account_snapshots.id"), nullable=True),
    Column("raw_payload_json", JSONB, nullable=False, default=dict),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("account_id", "provider_ad_id", name="uq_meta_ads_account_provider_id"),
)

meta_insight_rows = Table(
    "meta_insight_rows",
    metadata,
    Column("id", String, primary_key=True),
    Column("snapshot_id", ForeignKey("meta_account_snapshots.id"), nullable=False),
    Column("account_id", ForeignKey("meta_ad_accounts.id"), nullable=False),
    Column("entity_level", String, nullable=False),
    Column("entity_id", String, nullable=False),
    Column("date_start", String, nullable=False, default=""),
    Column("date_stop", String, nullable=False, default=""),
    Column("spend", Float, nullable=True),
    Column("impressions", Integer, nullable=True),
    Column("clicks", Integer, nullable=True),
    Column("conversions", Float, nullable=True),
    Column("purchase_value", Float, nullable=True),
    Column("ctr", Float, nullable=True),
    Column("cpc", Float, nullable=True),
    Column("cpm", Float, nullable=True),
    Column("cpa", Float, nullable=True),
    Column("roas", Float, nullable=True),
    Column("breakdown_json", JSONB, nullable=False, default=dict),
    Column("actions_json", JSONB, nullable=False, default=list),
    Column("raw_payload_json", JSONB, nullable=False, default=dict),
)
Index("ix_meta_insight_rows_account_entity_date", meta_insight_rows.c.account_id, meta_insight_rows.c.entity_level, meta_insight_rows.c.entity_id, meta_insight_rows.c.date_start)

user_sessions = Table(
    "user_sessions",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=True),
    Column("client_id", ForeignKey("clients.id"), nullable=True),
    Column("selected_account_id", ForeignKey("meta_ad_accounts.id"), nullable=True),
    Column("status", String, nullable=False, default="active"),
    Column("version", Integer, nullable=False, default=1, server_default="1"),
    Column("state_json", JSONB, nullable=False, default=dict),
    Column("compressed_context_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("reset_at", DateTime(timezone=True), nullable=True),
)

chat_messages = Table(
    "chat_messages",
    metadata,
    Column("id", String, primary_key=True),
    Column("session_id", ForeignKey("user_sessions.id"), nullable=False),
    Column("role", String, nullable=False),
    Column("content", Text, nullable=False),
    Column("metadata_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_chat_messages_session_created", chat_messages.c.session_id, chat_messages.c.created_at)

conversation_memory_chunks = Table(
    "conversation_memory_chunks",
    metadata,
    Column("id", String, primary_key=True),
    Column("session_id", ForeignKey("user_sessions.id"), nullable=False),
    Column("message_id", ForeignKey("chat_messages.id"), nullable=True),
    Column("client_id", ForeignKey("clients.id"), nullable=True),
    Column("account_id", ForeignKey("meta_ad_accounts.id"), nullable=True),
    Column("memory_type", String, nullable=False),
    Column("source_role", String, nullable=False, default=""),
    Column("content_summary", Text, nullable=False),
    Column("embedding", Vector(1536), nullable=False),
    Column("embedding_model", String, nullable=False, default="deterministic-local"),
    Column("embedding_dimensions", Integer, nullable=False, default=1536),
    Column("metadata_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("archived_at", DateTime(timezone=True), nullable=True),
)
Index("ix_conversation_memory_session_type_created", conversation_memory_chunks.c.session_id, conversation_memory_chunks.c.memory_type, conversation_memory_chunks.c.created_at)
Index("ix_conversation_memory_client_account_created", conversation_memory_chunks.c.client_id, conversation_memory_chunks.c.account_id, conversation_memory_chunks.c.created_at)
Index(
    "ix_conversation_memory_embedding",
    conversation_memory_chunks.c.embedding,
    postgresql_using="ivfflat",
    postgresql_ops={"embedding": "vector_cosine_ops"},
    postgresql_with={"lists": 100},
)

agent_tasks = Table(
    "agent_tasks",
    metadata,
    Column("id", String, primary_key=True),
    Column("session_id", ForeignKey("user_sessions.id"), nullable=False),
    Column("account_id", String, nullable=False, default=""),
    Column("goal", Text, nullable=False, default=""),
    Column("status", String, nullable=False, default="active"),
    Column("progress_json", JSONB, nullable=False, default=dict),
    Column("constraints_json", JSONB, nullable=False, default=list),
    Column("tool_ledger_json", JSONB, nullable=False, default=list),
    Column("active_skill_ids_json", JSONB, nullable=False, default=list),
    Column("metadata_json", JSONB, nullable=False, default=dict),
    Column("version", Integer, nullable=False, default=1, server_default="1"),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("ix_agent_tasks_session_status_updated", agent_tasks.c.session_id, agent_tasks.c.status, agent_tasks.c.updated_at)

agent_turns = Table(
    "agent_turns",
    metadata,
    Column("id", String, primary_key=True),
    Column("session_id", ForeignKey("user_sessions.id"), nullable=False),
    Column("idempotency_key", String, nullable=True),
    Column("request_hash", String, nullable=False, default=""),
    Column("status", String, nullable=False, default="in_progress"),
    Column("response_json", JSONB, nullable=False, default=dict),
    Column("error_text", Text, nullable=False, default=""),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("session_id", "idempotency_key", name="uq_agent_turns_session_idempotency"),
)
Index("ix_agent_turns_session_status_updated", agent_turns.c.session_id, agent_turns.c.status, agent_turns.c.updated_at)

agent_turn_locks = Table(
    "agent_turn_locks",
    metadata,
    Column("session_id", ForeignKey("user_sessions.id"), primary_key=True),
    Column("turn_id", ForeignKey("agent_turns.id"), nullable=False),
    Column("acquired_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)

agent_memory_records = Table(
    "agent_memory_records",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False),
    Column("scope_type", String, nullable=False),
    Column("scope_id", String, nullable=False),
    Column("account_id", String, nullable=False, default=""),
    Column("kind", String, nullable=False),
    Column("content", Text, nullable=False),
    Column("confidence", Float, nullable=False, default=0.5),
    Column("status", String, nullable=False, default="candidate"),
    Column("source_session_id", ForeignKey("user_sessions.id"), nullable=True),
    Column("source_message_id", ForeignKey("chat_messages.id"), nullable=True),
    Column("source_quote", Text, nullable=False, default=""),
    Column("supersedes_id", String, nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("metadata_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("ix_agent_memory_scope_status_updated", agent_memory_records.c.user_id, agent_memory_records.c.scope_type, agent_memory_records.c.scope_id, agent_memory_records.c.status, agent_memory_records.c.updated_at)
Index("ix_agent_memory_account_kind_updated", agent_memory_records.c.account_id, agent_memory_records.c.kind, agent_memory_records.c.updated_at)

mcp_tool_result_cache = Table(
    "mcp_tool_result_cache",
    metadata,
    Column("id", String, primary_key=True),
    Column("cache_key", String, nullable=False),
    Column("tool_name", String, nullable=False),
    Column("account_id", String, nullable=False, default=""),
    Column("arguments_json", JSONB, nullable=False, default=dict),
    Column("result_json", JSONB, nullable=False, default=dict),
    Column("source", String, nullable=False, default="mcp"),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("cache_key", name="uq_mcp_tool_result_cache_key"),
)
Index("ix_mcp_tool_result_account_tool_expiry", mcp_tool_result_cache.c.account_id, mcp_tool_result_cache.c.tool_name, mcp_tool_result_cache.c.expires_at)

meta_account_directory_cache = Table(
    "meta_account_directory_cache",
    metadata,
    Column("id", String, primary_key=True),
    Column("accounts_json", JSONB, nullable=False, default=list),
    Column("source", String, nullable=False, default="mcp"),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("last_error", Text, nullable=False, default=""),
)

meta_account_context_cache = Table(
    "meta_account_context_cache",
    metadata,
    Column("id", String, primary_key=True),
    Column("account_id", String, nullable=False),
    Column("context_json", JSONB, nullable=False, default=dict),
    Column("source_tools_json", JSONB, nullable=False, default=list),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("last_error", Text, nullable=False, default=""),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("account_id", name="uq_meta_account_context_cache_account"),
)
Index("ix_meta_account_context_expiry", meta_account_context_cache.c.expires_at)
agent_traces = Table(
    "agent_traces",
    metadata,
    Column("id", String, primary_key=True),
    Column("session_id", ForeignKey("user_sessions.id"), nullable=True),
    Column("trace_id", String, nullable=False),
    Column("workflow_id", String, nullable=False, default=""),
    Column("runtime", String, nullable=False, default=""),
    Column("source", String, nullable=False, default=""),
    Column("status", String, nullable=False, default="active"),
    Column("metadata_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("trace_id", name="uq_agent_traces_trace_id"),
)

agent_trace_steps = Table(
    "agent_trace_steps",
    metadata,
    Column("id", String, primary_key=True),
    Column("trace_id", ForeignKey("agent_traces.trace_id"), nullable=False),
    Column("agent", String, nullable=False, default=""),
    Column("title", String, nullable=False),
    Column("detail", Text, nullable=False, default=""),
    Column("status", String, nullable=False, default=""),
    Column("data_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_agent_trace_steps_trace_created", agent_trace_steps.c.trace_id, agent_trace_steps.c.created_at)

feedback_events = Table(
    "feedback_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("session_id", ForeignKey("user_sessions.id"), nullable=False),
    Column("event_type", String, nullable=False),
    Column("summary", Text, nullable=False),
    Column("data_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_feedback_events_session_type_created", feedback_events.c.session_id, feedback_events.c.event_type, feedback_events.c.created_at)

creative_assets = Table(
    "creative_assets",
    metadata,
    Column("id", String, primary_key=True),
    Column("account_id", ForeignKey("meta_ad_accounts.id"), nullable=False),
    Column("source", String, nullable=False),
    Column("media_type", String, nullable=False),
    Column("name", String, nullable=False, default=""),
    Column("preview_url", Text, nullable=False, default=""),
    Column("meta_asset_id", String, nullable=False, default=""),
    Column("existing_creative_id", String, nullable=False, default=""),
    Column("validation_status", String, nullable=False, default="valid"),
    Column("warnings_json", JSONB, nullable=False, default=list),
    Column("raw_payload_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("ux_creative_assets_account_meta_asset", creative_assets.c.account_id, creative_assets.c.meta_asset_id, unique=True, postgresql_where=creative_assets.c.meta_asset_id != "")

batch_launch_drafts = Table(
    "batch_launch_drafts",
    metadata,
    Column("id", String, primary_key=True),
    Column("client_id", ForeignKey("clients.id"), nullable=True),
    Column("account_id", ForeignKey("meta_ad_accounts.id"), nullable=False),
    Column("session_id", ForeignKey("user_sessions.id"), nullable=True),
    Column("status", String, nullable=False),
    Column("brief_json", JSONB, nullable=False, default=dict),
    Column("estimated_counts_json", JSONB, nullable=False, default=dict),
    Column("validation_issues_json", JSONB, nullable=False, default=list),
    Column("approved_at", DateTime(timezone=True), nullable=True),
    Column("active_publish_confirmed", Boolean, nullable=False, default=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

batch_draft_entities = Table(
    "batch_draft_entities",
    metadata,
    Column("id", String, primary_key=True),
    Column("draft_id", ForeignKey("batch_launch_drafts.id"), nullable=False),
    Column("entity_type", String, nullable=False),
    Column("entity_ref", String, nullable=False),
    Column("parent_ref", String, nullable=False, default=""),
    Column("payload_json", JSONB, nullable=False, default=dict),
    Column("sort_order", Integer, nullable=False, default=0),
    UniqueConstraint("draft_id", "entity_ref", name="uq_batch_draft_entities_draft_ref"),
)

optimization_action_drafts = Table(
    "optimization_action_drafts",
    metadata,
    Column("id", String, primary_key=True),
    Column("client_id", ForeignKey("clients.id"), nullable=True),
    Column("account_id", ForeignKey("meta_ad_accounts.id"), nullable=False),
    Column("session_id", ForeignKey("user_sessions.id"), nullable=True),
    Column("source", String, nullable=False),
    Column("status", String, nullable=False),
    Column("action_json", JSONB, nullable=False, default=dict),
    Column("draft_payload_json", JSONB, nullable=False, default=dict),
    Column("safety_json", JSONB, nullable=False, default=dict),
    Column("notes_json", JSONB, nullable=False, default=list),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

action_lifecycle_records = Table(
    "action_lifecycle_records",
    metadata,
    Column("id", String, primary_key=True),
    Column("workspace_id", String, nullable=False, default=""),
    Column("account_id", ForeignKey("meta_ad_accounts.id"), nullable=False),
    Column("entity_type", String, nullable=False),
    Column("entity_id", String, nullable=False),
    Column("operation", String, nullable=False),
    Column("status", String, nullable=False),
    Column("risk_level", String, nullable=False),
    Column("created_by", ForeignKey("users.id"), nullable=False, default="local_user"),
    Column("evidence_json", JSONB, nullable=False, default=list),
    Column("assumptions_json", JSONB, nullable=False, default=list),
    Column("missing_data_json", JSONB, nullable=False, default=list),
    Column("current_value_json", JSONB, nullable=False, default=dict),
    Column("proposed_value_json", JSONB, nullable=False, default=dict),
    Column("metadata_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("account_id", "entity_type", "entity_id", "operation", "status", name="uq_action_lifecycle_account_entity_operation_active"),
)
Index("ix_action_lifecycle_account_status_updated", action_lifecycle_records.c.account_id, action_lifecycle_records.c.status, action_lifecycle_records.c.updated_at)
Index("ix_action_lifecycle_workspace_created", action_lifecycle_records.c.workspace_id, action_lifecycle_records.c.created_at)

action_preflight_checks = Table(
    "action_preflight_checks",
    metadata,
    Column("id", String, primary_key=True),
    Column("action_id", ForeignKey("action_lifecycle_records.id"), nullable=False),
    Column("result", String, nullable=False),
    Column("blocked_reasons_json", JSONB, nullable=False, default=list),
    Column("missing_data_json", JSONB, nullable=False, default=list),
    Column("feature_flags_json", JSONB, nullable=False, default=dict),
    Column("stale_fields_json", JSONB, nullable=False, default=list),
    Column("checked_at", DateTime(timezone=True), nullable=False),
)
Index("ix_action_preflight_action_checked", action_preflight_checks.c.action_id, action_preflight_checks.c.checked_at)

action_approval_events = Table(
    "action_approval_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("action_id", ForeignKey("action_lifecycle_records.id"), nullable=False),
    Column("approver", ForeignKey("users.id"), nullable=False),
    Column("approval_status", String, nullable=False),
    Column("risk_summary", Text, nullable=False, default=""),
    Column("scope_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_action_approval_events_action_created", action_approval_events.c.action_id, action_approval_events.c.created_at)

action_confirmation_events = Table(
    "action_confirmation_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("action_id", ForeignKey("action_lifecycle_records.id"), nullable=False),
    Column("confirmed_by", ForeignKey("users.id"), nullable=False),
    Column("confirmation_text", Text, nullable=False),
    Column("confirmation_version", String, nullable=False, default="v1"),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_action_confirmation_events_action_created", action_confirmation_events.c.action_id, action_confirmation_events.c.created_at)

action_execution_attempts = Table(
    "action_execution_attempts",
    metadata,
    Column("id", String, primary_key=True),
    Column("action_id", ForeignKey("action_lifecycle_records.id"), nullable=False),
    Column("attempt_id", String, nullable=False),
    Column("idempotency_key", String, nullable=False),
    Column("provider_mode", String, nullable=False, default="simulator"),
    Column("result", String, nullable=False, default="pending"),
    Column("error_class", String, nullable=False, default=""),
    Column("trace_id", String, nullable=False, default=""),
    Column("request_summary_json", JSONB, nullable=False, default=dict),
    Column("provider_response_summary_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("idempotency_key", name="uq_action_execution_attempts_idempotency"),
)
Index("ix_action_execution_attempts_idempotency", action_execution_attempts.c.idempotency_key)
Index("ix_action_execution_attempts_action_created", action_execution_attempts.c.action_id, action_execution_attempts.c.created_at)

action_audit_events = Table(
    "action_audit_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("action_id", ForeignKey("action_lifecycle_records.id"), nullable=False),
    Column("from_status", String, nullable=False, default=""),
    Column("to_status", String, nullable=False, default=""),
    Column("actor", ForeignKey("users.id"), nullable=False, default="local_user"),
    Column("event_type", String, nullable=False),
    Column("metadata_summary_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_action_audit_events_action_created", action_audit_events.c.action_id, action_audit_events.c.created_at)

action_rollback_notes = Table(
    "action_rollback_notes",
    metadata,
    Column("id", String, primary_key=True),
    Column("action_id", ForeignKey("action_lifecycle_records.id"), nullable=False),
    Column("original_values_json", JSONB, nullable=False, default=dict),
    Column("recommended_manual_recovery", Text, nullable=False),
    Column("created_by", ForeignKey("users.id"), nullable=False, default="local_user"),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_action_rollback_notes_action_created", action_rollback_notes.c.action_id, action_rollback_notes.c.created_at)

approvals = Table(
    "approvals",
    metadata,
    Column("id", String, primary_key=True),
    Column("target_type", String, nullable=False),
    Column("target_id", String, nullable=False),
    Column("actor_user_id", ForeignKey("users.id"), nullable=True),
    Column("decision", String, nullable=False),
    Column("note", Text, nullable=False, default=""),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_approvals_target_created", approvals.c.target_type, approvals.c.target_id, approvals.c.created_at)

execution_logs = Table(
    "execution_logs",
    metadata,
    Column("id", String, primary_key=True),
    Column("client_id", ForeignKey("clients.id"), nullable=True),
    Column("account_id", ForeignKey("meta_ad_accounts.id"), nullable=True),
    Column("source_type", String, nullable=False),
    Column("source_id", String, nullable=False),
    Column("actor_user_id", ForeignKey("users.id"), nullable=False, default="local_user"),
    Column("status", String, nullable=False),
    Column("before_snapshot_id", ForeignKey("meta_account_snapshots.id"), nullable=True),
    Column("after_snapshot_id", ForeignKey("meta_account_snapshots.id"), nullable=True),
    Column("request_summary_json", JSONB, nullable=False, default=dict),
    Column("result_json", JSONB, nullable=False, default=dict),
    Column("error", Text, nullable=False, default=""),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_execution_logs_source", execution_logs.c.source_type, execution_logs.c.source_id)
Index("ix_execution_logs_client_account_created", execution_logs.c.client_id, execution_logs.c.account_id, execution_logs.c.created_at)

execution_log_entities = Table(
    "execution_log_entities",
    metadata,
    Column("id", String, primary_key=True),
    Column("execution_id", ForeignKey("execution_logs.id"), nullable=False),
    Column("entity_type", String, nullable=False),
    Column("entity_ref", String, nullable=False, default=""),
    Column("provider_entity_id", String, nullable=False, default=""),
    Column("status", String, nullable=False),
    Column("error", Text, nullable=False, default=""),
    Column("payload_json", JSONB, nullable=False, default=dict),
)

rollback_records = Table(
    "rollback_records",
    metadata,
    Column("id", String, primary_key=True),
    Column("execution_id", ForeignKey("execution_logs.id"), nullable=False),
    Column("actor_user_id", ForeignKey("users.id"), nullable=False, default="local_user"),
    Column("status", String, nullable=False),
    Column("plan_json", JSONB, nullable=False, default=dict),
    Column("result_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("executed_at", DateTime(timezone=True), nullable=True),
)

audit_reports = Table(
    "audit_reports",
    metadata,
    Column("id", String, primary_key=True),
    Column("client_id", ForeignKey("clients.id"), nullable=True),
    Column("account_id", ForeignKey("meta_ad_accounts.id"), nullable=False),
    Column("snapshot_id", ForeignKey("meta_account_snapshots.id"), nullable=True),
    Column("report_type", String, nullable=False),
    Column("language", String, nullable=False, default=""),
    Column("report_json", JSONB, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_audit_reports_account_type_created", audit_reports.c.account_id, audit_reports.c.report_type, audit_reports.c.created_at)
