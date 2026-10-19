# Architecture

## Status

- Document status: active architecture overview
- Source of truth: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](../00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md)
- Active stage: [STAGE_10_GA4_MEASUREMENT_TOOLS.md](../03-stages/STAGE_10_GA4_MEASUREMENT_TOOLS.md)

## Current Shape

```text
Next.js single-page workbench
  -> FastAPI route
    -> AgentRuntime
       -> Responses API
          -> tool_search
          -> deferred meta_ads tools
       -> Meta MCP read tools
       -> global GA4 Admin/Data API read tools
       -> local write-draft interception
    -> reply + trace + draft
```

The backend discovers the MCP catalog at runtime. The model loads only the tool definitions relevant to the current task.

## Backend Modules

```text
backend/agent/runtime.py       provider-neutral loop, context package and tool trace
backend/agent/deepseek.py      DeepSeek Chat Completions provider adapter
backend/agent/context.py       five-round window, token budget, summary contract
backend/agent/tools.py         Meta MCP discovery plus global GA4 routing, budgets, draft routing, result cache
backend/agent/ga4_tools.py     global read-only GA4 tool schemas
backend/services/ga4_gateway.py GA4 Admin/Data API read gateway
backend/agent/policy.py        local/read/draft classification
backend/agent/prompts.py       short system policy
backend/services/account_gateway.py  Meta MCP and local provider
backend/services/account_cache.py    account directory/context and tool-result caches
backend/services/task_state.py       task progress and tool ledger
backend/services/turn_control.py      turn lease, idempotency and replay control
backend/services/agent_turn_service.py shared JSON/SSE session, Memory, task, trace and response assembly
backend/services/long_term_memory.py typed long-term Memory
backend/services/trace_service.py    redacted trace persistence
```

## Tool Surface

The MCP tools are registered under the `meta_ads` namespace with `defer_loading=true`. The request includes `tool_search`. The model can inspect account, campaign, ad set, ad, creative, insights, audience, geo, image, and video capabilities without receiving every schema on every step.

Four create tools may call MCP in Draft Mode and return non-live Draft objects. All other write-like tools are virtualized as local drafts or rejected; activation and publication are blocked.


## GA4 Tool Surface

Configured GA4 tools are globally available to the model and do not require a Skill. They expose property discovery, metadata, data streams, key events, Google Ads links, core reports, realtime reports, and funnels. The gateway is read-only, validates numeric property IDs, never exposes credentials, and returns timezone, currency, row count, quota, and missing-data metadata.

## Media Results

`ads_get_ad_images`, `ads_get_ad_videos`, and screenshot tools return bounded metadata. Raw base64, image data, video bytes, and data URLs are omitted.

## API Surface

```text
POST /api/agent/turn
GET  /api/config
GET  /api/accounts/mcp/diagnostics
GET  /api/meta/status
GET  /api/meta/adaccounts
POST /api/actions/drafts
GET  /api/actions/drafts/{draft_id}
POST /api/actions/drafts/{draft_id}/preflight
POST /api/actions/drafts/{draft_id}/approve
POST /api/actions/drafts/{draft_id}/execute
```

## Removed Runtime

- fixed intent router and planner chain
- prompt registry and per-role prompt files
- fixed memory compiler and untyped semantic memory in the request path
- graph framework
- hand-written five-tool-only adapter
- provisional skills and performance analyzer pending redesign
- launch builder and batch launch flow

## Deferred Infrastructure

- PostgreSQL schema simplification
- Redis queue removal or replacement
- live execution design
