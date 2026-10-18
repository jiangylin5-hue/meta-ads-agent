# Code Boundaries

## Status

- Document status: active architecture contract
- Source of truth: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](IMPLEMENTATION_SOURCE_OF_TRUTH.md)
- Runtime reference: [AGENT_WORKFLOW.md](../02-architecture/AGENT_WORKFLOW.md)
- Active stage: [STAGE_09_CONTEXT_AND_AGENT_MEMORY.md](../03-stages/STAGE_09_CONTEXT_AND_AGENT_MEMORY.md)

## Backend Boundaries

### Routes

`backend/routes/` binds URLs to handlers. The agent turn route selects JSON or SSE and delegates execution to `AgentTurnExecution`; it contains no prompts, tool decisions, or loop logic.

### Route Handlers

`backend/route_handlers/` performs HTTP orchestration:

- validate request shape
- load session state
- invoke the agent runtime or a service
- assemble a response envelope

Route handlers must not own tool execution, trace redaction, model calls, or action decisions. The agent turn route owns transport and turn-lease orchestration only: it acquires the lease, calls `AgentTurnExecution`, completes or fails the persisted turn, and always releases the lease.

### Agent Core

`backend/agent/` owns the ReAct loop:

- `runtime.py`: model step loop and stop conditions
- `tools.py`: MCP discovery, deferred namespace, result budgets, and write drafting
- `skills.py`: closed 12-Skill catalog, SKILL.md loading, reference resolution, tool-group resolution, and scope rules
- `../skills/<skill_id>/`: `SKILL.md`, `contract.json`, and on-demand `references/`
- `policy.py`: tool allowlist and write-tool rejection
- `prompts.py`: the system prompt
- `context.py`: token estimation, five-round selection, summary prompt/parsing, and same-turn observation compaction
- `state.py`: step, trace, draft, Memory/task updates, and context manifest state

The agent core must not import route handlers or provider write methods.

### Services

Services own stable capabilities:

- `account_gateway.py`: Meta read gateway
- `performance_dashboard.py`: compact metric shaping
- `action_drafts.py`: optimization draft records
- `action_operations.py`: lifecycle, preflight, and approval events
- `session_store.py`: visible history, five-round continuity, summary checkpoint, active task id, and optimistic state versions
- `task_state.py`: current task goal, progress, blockers, active Skills, tool ledger, and optimistic versions
- `agent_turn_service.py`: shared JSON/SSE execution path for session preparation, runtime invocation, Memory, task, trace, and response assembly
- `agent_sse.py`: SSE queue, heartbeat, sequence encoding, replay, and public failure payloads
- `turn_control.py`: per-session turn lease, idempotent replay, request fingerprint, and conflict codes
- `long_term_memory.py`: typed user/account Memory, scope validation, candidate promotion, and deletion
- `account_cache.py`: account directory, prompt-ready account context, and bounded MCP result caches
- `trace_service.py`: trace persistence and redaction

Action lifecycle code may prepare approval. It must not expose a model-callable write tool.

### Integrations

`backend/integrations/` is an external adapter layer. It normalizes provider calls and does not route requests or make business decisions.

## Tool Boundary

`backend/agent/tools.py` discovers MCP tools with `tools/list` and exposes them under the `meta_ads` namespace. The model loads the short Skill catalog with `load_skill`, reads references with `read_skill_reference` when needed, then loads relevant definitions with `tool_search`. Code resolves reference paths, validates MCP arguments against the sanitized JSON Schema, checks machine-readable input gates, allows four create tools through MCP Draft Mode and stages other write-like calls only when a matching-account, target-bound `force_refresh=true` live read exists and optimization `current_state` values match the bounded live-read result, and denies MCP tools outside the active Skill groups. Active Skills submit per-skill results; `submit_result` validates each Skill contract and evidence separately. The model chooses `resolved_decision` and must explain differing Skill decisions.

Tool classes:

```text
local:    ask_user, load_skill, read_skill_reference, submit_result, save_memory, update_task
read:     any discovered MCP tool in an active Skill read group
direct:   ads_create_campaign, ads_create_ad_set, ads_create_ad, ads_create_creative (MCP Draft Mode)
draft:    other write-like MCP tools in an active Skill Draft group
```

Write-like names:

```text
create_campaign
create_adset
create_ad
create_ad_creative
create_budget_schedule
update_campaign
update_adset
update_ad
update_ad_creative
upload_ad_image
```

Only `ads_create_campaign`, `ads_create_ad_set`, `ads_create_ad`, and `ads_create_creative` call MCP; they use Draft Mode and return non-live Draft objects. Other write-like tools become local drafts with evidence, recommendation, risk, lifecycle, and preflight. Activation and publication are rejected.

The following are forbidden direct execution paths:

```text
execute_action
publish_batch_draft
execute_rollback
provider write methods
```

Model-supplied `access_token` fields are removed. The runtime injects the configured token internally.

Image and video content is reduced to metadata. Raw base64, data URLs, and provider media bytes never enter model context or trace.

## Frontend Boundaries

- `frontend/app/` owns the route shell.
- `frontend/features/workbench/` composes the single page.
- `frontend/features/chat/`, `accounts/`, and `workspace/` own focused panels.
- `frontend/lib/api/` owns HTTP calls.
- `frontend/lib/types/` owns API types.

The frontend calls `POST /api/agent/turn` for chat and the approval endpoint for draft approval. It does not call `/api/chat`, `/api/intent`, or a batch launch route.

## Context Hygiene

Never send the model:

- route handler source
- old workflow implementations
- large documentation
- raw provider payloads
- tokens, cookies, credentials, or data URLs
- full draft records when a compact summary is enough

Prefer short prompts, structured payloads, and compact observations. Account data is an external-state cache with `fetched_at`, `expires_at`, `stale`, and `as_of` fields. Long-term Memory is user/account scope data and never becomes a system instruction. Current provider reads outrank both.

## Framework Baseline

- Backend: FastAPI with route / handler / service separation.
- Agent runtime: plain Python loop plus the OpenAI Responses API.
- Frontend: Next.js App Router with the existing React and component conventions.
- Data access: Meta read gateway for reads; approval-gated action records for drafts.
- Tests: pytest for backend and static boundaries; Playwright for frontend smoke.

Framework replacements require an active-stage update and explicit user confirmation.
