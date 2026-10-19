# Runtime Verification

## Status

- Document status: active verification guide
- Source of truth: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](../00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md)
- Active stage: [STAGE_10_GA4_MEASUREMENT_TOOLS.md](../03-stages/STAGE_10_GA4_MEASUREMENT_TOOLS.md)

## 1. Local Regression

```powershell
$env:OPENAI_API_KEY=""
.venv\Scripts\python.exe -m pytest tests -q
npm.cmd run lint --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run test:smoke --prefix frontend
```

This proves:

- the agent loop handles the Skill catalog, `load_skill`, batched multi-Skill loading up to eight Skills, tool search, tool calls, final answers, ask-user, max steps, and forbidden tools
- five recent conversation rounds are retained and older dialogue is summarized with source message ids
- Memory and task-progress local tools emit persistable structured updates
- fresh MCP result cache hits avoid a second provider call
- account context is compact, metric-aware, and carries freshness/source provenance
- MCP tools outside the active Skill groups are denied by code
- a Skill must be loaded before its references can be read, and reference content is bounded
- MCP arguments are validated against the sanitized JSON Schema for required fields, types, enums, and supported properties before calls
- malformed argument JSON and runtime-only fields are rejected before MCP calls
- required account/date/level/target inputs are checked before MCP calls
- write-like tools require a matching-account force-refreshed live read for the Draft target; optimization current budget, status, sample size, Learning state, and comparison window must match values exposed by that read
- account-scoped Memory is excluded without a selected account, and only current user-message quotes can activate a Memory record
- active Memory recall uses query/task token overlap, confidence, kind priority, and fixed recency decay; candidates are excluded until confirmed
- client retries of the same failed submission reuse the original idempotency key
- SSE events carry the persisted turn id, sequence gaps fail the stream, and worker-start failure releases the turn lease
- the default turn lease follows the configured agent turn deadline plus a bounded release buffer
- four create tools write non-live Draft Mode objects; other write-like tools stage actions and require validated submit_result before local Draft creation
- each active Skill result must pass its own required-field, decision-mode, source-tool, and evidence-field validation
- the model chooses resolved_decision; differing Skill decisions require a conflicts explanation
- the draft response includes evidence and preflight
- the official Meta Ads MCP catalog is discovered; OpenAI uses deferred `tool_search` while DeepSeek uses portable Skill-scoped tool schemas
- only the four permitted create tools call MCP, through Draft Mode; activation and publication never call MCP
- image and video payloads are reduced to bounded metadata
- the API exposes `/api/agent/turn` and no legacy chat route
- execution routes return `410 execution_disabled_in_demo`
- action lifecycle and infrastructure tests still pass
- the single-page frontend type-checks, builds, and works at desktop and mobile viewport sizes
- JSON requests keep the existing response and SSE requests return ordered, sanitized progress events with one terminal event
- POST SSE parsing handles split UTF-8 data, CRLF, multi-line data, heartbeats, unknown events, abort signals, and sequence checks
- tool start/finish pairs, Draft staging, validation, timeout, retryability, replay, and disconnect continuation are covered

It does not prove a live Meta read, a real OpenAI call, or live GA4 account data beyond the configured Property test.

## 2. Real MCP Tool-Search Smoke

```powershell
.venv\Scripts\python.exe scripts\verify_mcp_tool_agent.py --spend-credits
```

The script uses the configured real model provider, the official MCP session handshake, the 98-tool catalog, `load_skill`, optional `read_skill_reference`, the provider-specific tool exposure path, a read-only `ads_get_ad_accounts` call, and `submit_result`.

It proves:

- the MCP catalog is discovered at runtime
- the model loads a project Skill before calling Meta tools
- the model searches for a deferred MCP tool inside the loaded scope
- the selected tool executes through MCP
- the tool observation returns to the model
- the final answer is produced without a write call

It does not prove:

- write execution
- media visual analysis
- the quality of every MCP tool family

## 3. Real Meta Read Check

Use the existing token verifier when a real read check is needed:

```powershell
.venv\Scripts\python.exe scripts\verify_meta_access_token.py --account-limit 10
```

Do not perform a live provider write as part of local verification.

## 4. Credential Check

The project uses a Meta System User token with `expires_at=never` (non-expiring; 永不过期). The token value exists only in `.env`.

```powershell
.venv\Scripts\python.exe scripts\doctor.py
.venv\Scripts\python.exe scripts\verify_meta_access_token.py --account-limit 10
```

`doctor.py` must report the official MCP as reachable and ready. The token verifier must report the readable account count. Token Debugger must report the correct App ID and `expires_at=never`.


## 5. Real GA4 Measurement Check

The GA4 gateway uses a service-account JSON outside the repository and the `analytics.readonly` scope. It validates the numeric Property ID and never accepts a `G-` measurement ID as a reporting property.

Focused verification:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_ga4_tools.py -q
```

Real Agent result:

- Property `<ga4_property_id>` is readable.
- Property timezone is `Asia/Shanghai`; currency is `CNY`; service level is standard.
- Data streams, key events, Google Ads links, and report rows are empty because tracking has not been configured.
- DeepSeek completed in 4 steps and 25.6 seconds.
- `skills_loaded=[]`; the model called GA4 tools directly without `load_skill`.
- Calls: property details, data streams, key events, 365-day report, and realtime report.
- Draft count: zero. No GA4 write method exists in the tool surface.

## Evidence Rules

A quality claim must name the command and the result. Separate local fake-model proof, real OpenAI proof, and real Meta proof.

Do not claim:

- "real account changed" without an execution log
- "Meta data verified" from a fake provider
- "OpenAI path verified" from a fake model
- "execution works" when the route returns 410

## Current Limits

- Preflight is shallow.
- Draft approval records lifecycle approval only.
- Tool selection quality across the official tool catalog needs broader replay coverage.
- MCP result shapes may vary by server version.
- PostgreSQL is the active persistence layer; Redis simplification remains deferred.
- Account and tool cache freshness is TTL-based rather than provider-event based.
- The local model tokenizer was not available, so pre-call budget estimates are conservative and calibrated by actual Responses usage.
- No real OpenAI call was run for this stage.
- SSE streams execution progress; final answer text is delivered in `turn.completed.response`.
