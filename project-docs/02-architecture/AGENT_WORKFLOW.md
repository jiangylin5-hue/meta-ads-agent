# Agent Workflow

## Status

- Document status: active runtime reference
- Source of truth: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](../00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md)
- Active stage: [STAGE_10_GA4_MEASUREMENT_TOOLS.md](../03-stages/STAGE_10_GA4_MEASUREMENT_TOOLS.md)
- Verification: [RUNTIME_VERIFICATION.md](../05-quality/RUNTIME_VERIFICATION.md)

## Main Flow

```text
user message
-> load five recent conversation rounds + older structured summary
-> load active task state, active Skill instructions, relevant Memory, and selected-account cache
-> AgentRuntime
-> model sees the 12-Skill catalog
-> model calls load_skill for one or more relevant contracts (up to four)
-> load_skill returns SKILL.md instructions, evidence requirements, tool groups, and a reference index
-> model calls read_skill_reference only when a reference is needed
-> code gates account/date/level inputs and the required read evidence
-> provider exposes Meta tools inside the loaded Skill groups plus global read-only GA4 tools
-> selected Meta MCP tools or GA4 Admin/Data API tools call their read gateways
-> plan-first confirmation unlocks four create tools; explicit draft_only reads unlock Draft update/delete; other write-like tools stage locally
-> compact observations return to the model
-> submit_result validates output and commits selected local staged actions
-> emit sanitized step, tool, Skill, Draft, and validation events to the SSE worker queue
-> stop on final, ask_user, or max steps
```

There is one ReAct loop. The model chooses tools. Code validates tool names and arguments against the sanitized JSON Schema, removes model-supplied tokens, enforces result budgets, and intercepts every write-like tool. Only the four permitted create tools reach MCP, through Draft Mode. Malformed argument JSON fails before execution.

## Entry Points

```text
backend/routes/agent_routes.py   HTTP orchestration and JSON/SSE response selection
backend/agent/runtime.py          ReAct loop, context package and Responses input items
backend/agent/context.py          token estimation, five-round window and summary schema
backend/agent/tools.py            Meta MCP discovery plus global GA4 tool routing and result cache
backend/agent/ga4_tools.py        Global read-only GA4 tool schemas
backend/services/ga4_gateway.py   GA4 Admin/Data API gateway
backend/agent/skills.py           closed Skill catalog, contract loading, tool-group scope
backend/skills/<skill_id>/       SKILL.md, contract.json, and references/
backend/agent/policy.py           tool classification and allowlist
backend/agent/prompts.py          short system prompt
backend/services/session_store.py recent history and rolling summary
backend/services/task_state.py    current task, progress and tool ledger
backend/services/long_term_memory.py typed user/account Memory
backend/services/account_cache.py account context and MCP result TTL caches
backend/services/trace_service.py redacted trace persistence
backend/services/agent_turn_service.py shared turn execution and response assembly
backend/services/agent_sse.py     SSE queue, heartbeat, encoding, and failure payloads
```

## Loop Contract

- Default maximum: 16 model-decision steps; hard ceiling: 24. The default turn deadline is 600 seconds.
- The model sees only the short 12-Skill catalog. It calls `load_skill` before Meta tools and may load at most eight Skills per turn.
- Each loaded Skill returns SKILL.md instructions, its evidence requirements, allowed read/Draft groups, and a reference index. Meta tools outside the union of loaded groups are denied by code; configured read-only GA4 tools are global.
- `read_skill_reference` reads only a reference from a Skill already loaded in the same turn. Reference paths and IDs are resolved by code.
- Every MCP call is validated against its sanitized JSON Schema for required fields, types, enums, and supported properties; runtime-only fields and malformed JSON are rejected. Input gates add missing account, date-window, entity-level, target, catalog, or search checks. Write-like tools require a matching-account `force_refresh=true` live read with the Draft target id in the bounded result plus a non-empty `current_state`; optimization additionally requires current budget, status, sample size, Learning state, and comparison window, and those values must match the bounded live-read result.
- Each active Skill submits its own result through `submit_result`. Code validates required fields, allowed decision/verdict modes, real source tools, and evidence fields per Skill. The model chooses `resolved_decision`; if Skill decisions differ, `conflicts` must explain the resolution. Plain final text is rejected until validation passes.
- OpenAI uses deferred Meta and GA4 schemas with `tool_search`. DeepSeek receives active Skill tools plus the global GA4 tools directly and does not depend on provider-native tool search.
- Tool search and `load_skill` calls are visible in trace.
- SSE event `turn_id` is the persisted turn id; sequence numbers are contiguous. Stream-start failure marks the turn failed and releases its lease.
- Every function call records step, namespace-qualified tool, compact arguments, and compact result.
- Parsed Responses output items are preserved in the next request.
- The loop stops on a final answer, `ask_user`, or max steps. Direct Draft Mode creation records an execution log and never activates or publishes.
- Hidden reasoning is not stored or returned.

## MCP Tool Namespace

The runtime initializes a session with the official Meta Ads MCP (`https://mcp.facebook.com/ads`), reads `tools/list`, and registers all discovered tools under:

```text
meta_ads
```

Examples:

```text
ads_get_ad_accounts
ads_get_ad_entities
ads_insights_performance_trend
ads_insights_anomaly_signal
ads_get_opportunity_score
ads_account_get_activity_logs
ads_get_creatives
ads_get_datasets
ads_experiment_list_tests
ads_library_search
```

Tool schemas remove model-supplied `access_token` and official MCP metadata fields. The runtime injects the bearer token, conversation id, request text, and job classification internally.


## GA4 Measurement Tools

GA4 is a global model tool family, not a project Skill. The model may call `ga4_*` tools without `load_skill`, including when no Meta Skill is active. The gateway uses a service-account JSON path from `GOOGLE_APPLICATION_CREDENTIALS`, obtains the `analytics.readonly` scope, and calls only GA4 Admin/Data API read methods.

Supported reads cover account/property discovery, property details, data streams, key events, Google Ads links, metadata, core reports, realtime reports, and funnel reports. Credentials never enter tool arguments, prompts, Memory, cache, or trace. Meta attribution, GA4 observations, and CRM outcomes remain separate evidence classes.

## Write Boundary

The following tool names are write-like:

```text
ads_create_campaign
ads_create_ad_set
ads_create_ad
ads_create_creative
ads_update_entity
ads_activate_entity
ads_delete_custom_audience
ads_catalog_create
ads_pixel_event_create
ads_creative_upload_media
```

Their model schemas require evidence, recommendation, and risk level. The runtime creates a local optimization draft, lifecycle record, and preflight result. It does not forward the call to MCP.

`AGENTS.md` states the behavior rule. `backend/agent/tools.py` and `backend/agent/policy.py` enforce it.

## Media Budget

`ads_get_ad_images`, `ads_get_ad_videos`, and screenshot tools return bounded metadata. Raw base64, data URLs, image data, and video bytes are omitted. The adapter keeps ids, MIME type, character count, estimated bytes, and source ids when available.

## Context Budget

The runtime keeps five complete conversation rounds. Older dialogue is passed through a structured model summary with source message ids and a deterministic fallback. The default estimated input budget is 256,000 tokens with a 16,384-token output reserve; compression starts at roughly 80%.

Active task Skills are carried forward with full instructions. References remain on demand. Current-turn tool parameters and observations remain structured; the task ledger keeps the latest twelve compact entries. MCP observations are bounded per result and compacted across the turn. Media results stay limited to 4,000 characters.

Long-term Memory is injected as data, not instructions. Active records are ranked with query/task lexical overlap, confidence, kind priority, and bounded recency decay; candidate records require user confirmation. Task state, account cache freshness, and prior tool evidence are separate context sections so current provider data can outrank historical context.

## Prompt Hygiene

Never send:

- route source
- raw provider payloads
- model-supplied access tokens
- base64 image/video data
- large documentation
- full draft payloads
