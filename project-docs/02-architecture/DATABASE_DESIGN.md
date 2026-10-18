# PostgreSQL Database Design

本文档是 Stage 03 的数据库设计说明。目标是替换旧 SQLite payload store 和模块级内存业务存储，建立适合 Meta ads copilot 的 PostgreSQL 主库。

## Status

- Document status: active design reference
- Related stage: Stage 03 - PostgreSQL Database Foundation
- Current implementation source: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](../00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md)
- Runtime boundary: [CODE_BOUNDARIES.md](../00-governance/CODE_BOUNDARIES.md)

## Service Layer

- `backend/db/connection.py`: owns `DATABASE_URL`, engine creation, transactions, and health checks.
- `backend/db/schema.py`: owns SQLAlchemy table metadata for the public application schema.
- `backend/db/migrations/`: owns Alembic environment and versioned migrations. Runtime code must not create or mutate schema directly.
- `backend/repositories/`: owns table access by domain: tenant, Meta data, sessions, drafts, and execution.
- `backend/services/persistent_store.py`: remains only as a compatibility facade while delegating to repositories.

## Database Layer

- Primary database: PostgreSQL.
- Local service: `docker compose up -d postgres` starts the `ads_agent` database defined in `docker-compose.yml`.
- Operations: `.venv\Scripts\python.exe scripts\db_ops.py check-schema`, `.venv\Scripts\python.exe scripts\db_ops.py offline-sql`, `.venv\Scripts\python.exe scripts\db_ops.py migrate`, `.venv\Scripts\python.exe scripts\db_ops.py current`, `.venv\Scripts\python.exe scripts\db_ops.py history`, and `.venv\Scripts\python.exe scripts\db_ops.py health`.
- `check-schema` and `offline-sql` are offline governance commands. `migrate`, `current`, `history`, and `health` require a running PostgreSQL service and must fail loudly if `DATABASE_URL` is unreachable.
- Destructive local reset is intentionally guarded: `.venv\Scripts\python.exe scripts\db_ops.py downgrade` refuses to run unless `--allow-destructive-local-reset` is supplied.
- Required extension: `pgcrypto` for `gen_random_uuid()` when native database IDs are needed.
- Required extension: `vector` for pgvector-backed conversation memory embeddings.
- Required migration records: `alembic_version`.
- JSONB is used only for raw provider payloads, variable evidence, safety metadata, and UI artifacts. Query-critical fields must be structured columns.

## Table Relationships

Tenancy:

- `organizations.id` is the root tenant key.
- `users.email` is unique.
- `clients.organization_id -> organizations.id`; unique `(organization_id, name)`.

Connections and accounts:

- `external_connections.client_id -> clients.id`; unique `(client_id, provider, provider_user_id)`.
- `meta_ad_accounts.client_id -> clients.id`; `connection_id -> external_connections.id`; unique `(client_id, provider_account_id)`.

Meta data:

- `meta_account_snapshots.client_id -> clients.id`; `account_id -> meta_ad_accounts.id`.
- `meta_campaigns.account_id -> meta_ad_accounts.id`; unique `(account_id, provider_campaign_id)`.
- `meta_adsets.account_id -> meta_ad_accounts.id`; `campaign_id -> meta_campaigns.id`; unique `(account_id, provider_adset_id)`.
- `meta_creatives.account_id -> meta_ad_accounts.id`; unique `(account_id, provider_creative_id)`.
- `meta_ads.account_id -> meta_ad_accounts.id`; `campaign_id -> meta_campaigns.id`; `adset_id -> meta_adsets.id`; `creative_id -> meta_creatives.id`; unique `(account_id, provider_ad_id)`.
- `meta_insight_rows.snapshot_id -> meta_account_snapshots.id`; `account_id -> meta_ad_accounts.id`; indexed by `(account_id, entity_level, entity_id, date_start)`.

User usage and workspace:

- `user_sessions.user_id -> users.id`; `client_id -> clients.id`; `selected_account_id -> meta_ad_accounts.id`.
- `chat_messages.session_id -> user_sessions.id`; index `(session_id, created_at)`.
- `conversation_memory_chunks.session_id -> user_sessions.id`; optional `message_id -> chat_messages.id`, `client_id -> clients.id`, and `account_id -> meta_ad_accounts.id`; indexes `(session_id, memory_type, created_at)`, `(client_id, account_id, created_at)`, and pgvector ANN over `embedding`.
- `user_sessions.version` and `agent_tasks.version` support optimistic updates.
- `agent_tasks.session_id -> user_sessions.id`; indexed by `(session_id, status, updated_at)`.
- `agent_turns.session_id -> user_sessions.id`; unique `(session_id, idempotency_key)`; stores turn status, request fingerprint, and completed response.
- `agent_turn_locks.session_id -> user_sessions.id` and `turn_id -> agent_turns.id`; one lease per session.
- `agent_memory_records.user_id -> users.id`; optional `source_session_id` and `source_message_id`; indexed by scope/status and account/kind.
- `mcp_tool_result_cache` stores bounded read-tool results by cache key with `fetched_at` and `expires_at`.
- `meta_account_directory_cache` and `meta_account_context_cache` store account selector and prompt-ready account data with TTL.
- `agent_traces.session_id -> user_sessions.id`; unique `trace_id`.
- `agent_trace_steps.trace_id -> agent_traces.trace_id`; index `(trace_id, created_at)`.
- `feedback_events.session_id -> user_sessions.id`; index `(session_id, event_type, created_at)`.

Drafts, approvals, and execution:

- `creative_assets.account_id -> meta_ad_accounts.id`; partial unique `(account_id, meta_asset_id)` when `meta_asset_id` is not null.
- `batch_launch_drafts.client_id -> clients.id`; `account_id -> meta_ad_accounts.id`; `session_id -> user_sessions.id`.
- `batch_draft_entities.draft_id -> batch_launch_drafts.id`; unique `(draft_id, entity_ref)`.
- `optimization_action_drafts.client_id -> clients.id`; `account_id -> meta_ad_accounts.id`; `session_id -> user_sessions.id`.
- `approvals.actor_user_id -> users.id`; index `(target_type, target_id, created_at)`.
- `execution_logs.client_id -> clients.id`; `account_id -> meta_ad_accounts.id`; `actor_user_id -> users.id`; index `(source_type, source_id)`.
- `execution_log_entities.execution_id -> execution_logs.id`.
- `rollback_records.execution_id -> execution_logs.id`.
- `audit_reports.client_id -> clients.id`; `account_id -> meta_ad_accounts.id`; `snapshot_id -> meta_account_snapshots.id`; index `(account_id, report_type, created_at)`.

## Sensitive Data Rules

- Live access tokens are never persisted in the database. Only non-reversible fingerprints are stored in `external_connections.token_fingerprint_json`; the actual Meta token is supplied at call time from runtime configuration.
- Normal JSONB payloads must not contain access tokens, cookies, MCP tokens, data URLs, or raw creative binaries.
- `raw_payload_json` must be sanitized before insert.
- Conversation memory chunks store compact summaries, not raw provider payloads. The embedding input and `metadata_json` must be scrubbed with the same sensitive-key rules before insert.

## Conversation Memory Rules

- User-visible history is durable raw history in `chat_messages`. Session detail routes default to the latest 50 messages and support pagination for older rows.
- LLM short-term context keeps the latest five complete conversation rounds plus a structured summary of older dialogue.
- `user_sessions.compressed_context_json` stores the summary checkpoint, source message ids, current goal, constraints, confirmed decisions, open questions, completed work, and account references.
- `agent_tasks` stores the current goal, progress, blockers, active Skill ids, and a bounded structured tool ledger.
- `agent_memory_records` stores typed user/account preferences, habits, decisions, account profiles, and outcomes. Inferred records may remain candidates until a source quote or user confirmation promotes them.
- `conversation_memory_chunks` remains a legacy table from the removed memory compiler and is not used by the current runtime.
- Account cache records carry `fetched_at`, `expires_at`, source tools, and stale/error metadata. Current Meta data outranks cached and recalled historical context.

## Transaction Rules

- OAuth connection plus account binding is one transaction.
- Snapshot plus campaigns, ad sets, ads, creatives, and insights is one transaction.
- Draft create, update, approve, and final confirmation each run in one transaction.
- Execution log plus created entity rows plus draft status update is one transaction.
- Rollback plan creation is one transaction and never deletes the original execution log.

## Maintenance Rules

- Do not hard-delete `execution_logs`, `execution_log_entities`, `rollback_records`, `approvals`, `meta_account_snapshots`, or `audit_reports`.
- Use soft archive, archive tables, or retention jobs for old chat and insight rows.
- Add composite indexes for high-frequency account, date, entity, report, and session queries before relying on them in product routes.
- Every schema change must be a migration with an audit record.
- Alembic revision IDs must remain 32 characters or shorter because Alembic's default `alembic_version.version_num` column is `VARCHAR(32)`.
- Before merging database changes, run `.venv\Scripts\python.exe scripts\check_database_schema.py` so relation and uniqueness drift is caught without needing a live database.
