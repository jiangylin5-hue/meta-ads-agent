# Quality Evidence

## Status

- Document status: active evidence record
- Source of truth: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](../00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md)
- Verification boundary: [RUNTIME_VERIFICATION.md](RUNTIME_VERIFICATION.md)

## Stage 07 Gate (historical baseline)

Date: public snapshot

Scope:

- bounded ReAct tool loop
- five-tool allowlist
- no legacy fixed pipeline
- draft evidence, risk, and preflight in the UI
- approval without execution
- single-page frontend

Local evidence:

- `.venv\Scripts\python.exe -m pytest tests -q`: `107 passed, 1 skipped`
- `.venv\Scripts\python.exe -m pytest tests\test_docs_quality.py -q`: `10 passed`
- `npm.cmd run lint --prefix frontend`: passed
- `npm.cmd run build --prefix frontend`: passed
- `npm.cmd run test:smoke --prefix frontend`: `2 passed`

Real OpenAI evidence:

- `.venv\Scripts\python.exe scripts\verify_agent_loop.py --spend-credits`: passed
- The configured `gpt-6-luna` model called `list_accounts` through the Responses API.
- The tool returned `count=2`.
- The model answered that two readable Meta ad accounts were available.
- Stop reason: `final`; recorded steps: 2.
- The configured reasoning effort was applied in the same request as the function tools.

A first live attempt with `gpt-5.4` through Chat Completions failed because that endpoint rejects function tools with a non-`none` reasoning effort. The runtime was moved to the Responses API and re-verified live.

Not proven:

- real Meta reads through the model in this gate
- live write execution
- quality of longer multi-step media-buyer analysis

## Stage 08 MCP-native Gate

Date: public snapshot

Scope:

- Official Meta Ads MCP discovery with 98 tools
- deferred `meta_ads` namespace and `tool_search`
- write-like tool interception
- bounded media results

Recorded results:

- Focused agent, gateway, API, docs, and boundary tests: `38 passed`
- Full backend and docs suite: `113 passed, 1 skipped`
- `scripts/verify_mcp_tool_agent.py --spend-credits`: passed
- Real model: `gpt-6-luna`
- Search loaded eight relevant tool definitions
- Model called `meta_ads.ads_get_ad_accounts` with `limit=3`
- MCP returned three readable accounts
- Stop reason: `final`; recorded steps: 2
- `get_ad_image` returned 293 characters of metadata for a 198,904-character image payload; raw base64 was omitted
- frontend lint, production build, and desktop/mobile smoke passed

Safety evidence:

- Ten write-like tool names are mapped to local drafts.
- A focused test proves `update_campaign` creates a draft and makes zero MCP calls.
- All deferred schemas remove model-supplied `access_token`.
- Media content is represented by MIME type, character count, estimated bytes, and source ids.

## Stage 08 Skill Runtime Gate

Date: public snapshot

Scope:

- 12 project Skill folders in `backend/skills/` with `SKILL.md`, `contract.json`, and on-demand references
- model-selected `load_skill` with batch loading up to four Skills and `read_skill_reference` for on-demand details
- code-enforced tool-group scope before MCP execution
- `skills_loaded` and Skill trace summaries
- Draft-only behavior for write-like tools

Local evidence:

- `.venv\Scripts\python.exe -m pytest tests -q`: `131 passed, 1 skipped`
- `npm.cmd run lint --prefix frontend`: passed
- `npm.cmd run build --prefix frontend`: passed
- `npm.cmd run test:smoke --prefix frontend`: `2 passed`
- Schema tests cover required-field/type rejection, runtime-only field rejection, and malformed JSON fail-closed behavior.
- Skill tests cover 12 unique IDs, SKILL.md catalog loading, on-demand references, input gates, concrete evidence fields and source tools, current-state gates, staged write actions, deferred Draft creation, per-Skill output validation, model-resolved decision conflicts, batch loading, scope denial, and a four-Skill ceiling.

Not proven:

- real OpenAI selection of Skill IDs across a multi-intent replay set
- a live MCP `tools/list` pass during the latest implementation run; it returned HTTP 401, so the previously saved 98-tool snapshot was used for static validation
- execution of live Meta writes

## Safety Evidence

- `backend/agent/policy.py` rejects `execute_action`, `publish_batch_draft`, and `execute_rollback`.
- Tool schemas expose only read, draft, and ask-user tools.
- `/api/actions/drafts/{draft_id}/execute` returns `410 execution_disabled_in_demo`.
- Approval records a lifecycle event and does not call a provider write method.
- Trace redaction removes secrets, cookies, credentials, data URLs, and large payload text.

## Legacy Pipeline Removal

The fixed chat pipeline, prompt registry, intent router, memory compiler, query rewrite, multi-role runtime, old verification scripts, and their tests were removed after dependency checks. A static boundary test prevents the deleted route and core files from returning.


## Stage 09 Context And Agent Memory Gate

Date: public snapshot

Scope:

- five-round context window and structured older-dialogue summary
- typed long-term Memory and short-term task progress
- active Skill carry-forward and bounded tool ledger
- account directory, account context, and MCP result caches
- Context workspace tab with budget, task, freshness, and Memory controls

Local evidence:

- `.venv\Scripts\python.exe -m pytest tests -q`: `144 passed, 1 skipped`
- `scripts/check_database_schema.py`: passed, 38 tables
- Alembic current: `0006_stage_09_context_memory (head)`
- `npm.cmd run lint --prefix frontend`: passed
- `npm.cmd run build --prefix frontend`: passed outside the sandbox after sandbox `spawn EPERM`
- `npm.cmd run test:smoke --prefix frontend`: `2 passed`

Not proven:

- real model-generated summary quality over a broad Chinese replay set
- provider tokenizer accuracy against the conservative local estimate
- live MCP cache hit rates under real network conditions
- live Meta writes


## Stage 09 Backend Hardening Gate

Date: public snapshot

Scope:

- one active agent turn per session through a database lease
- idempotent turn replay and payload mismatch rejection
- retry dedupe for user/assistant messages and task ledger updates
- optimistic version checks for session and task persistence
- explicit 409 conflict responses

Local evidence:

- `.venv\Scripts\python.exe -m pytest tests -q`: `158 passed, 1 skipped`
- `scripts/check_database_schema.py`: passed, 40 tables
- Alembic current: `0007_stage_09_hardening (head)`
- Database turn-control smoke: passed (turn creation, completion, idempotent replay, lock release, cleanup)
- `npm.cmd run lint --prefix frontend`: passed

Not proven:

- real multi-process contention under a live model
- crash recovery under database failover
- model or live provider evaluation


## Stage 09 SSE Streaming Gate

Date: public snapshot

Scope:

- POST SSE on the existing `/api/agent/turn` route
- ordered turn, step, tool, Skill, Draft, validation, completion, and failure events
- worker queue, 15-second heartbeat, turn deadline, and disconnect continuation
- fetch-based SSE parser and workbench streaming state

Local evidence:

- `.venv\Scripts\python.exe -m pytest tests -q`: `177 passed, 1 skipped`
- SSE tests cover JSON compatibility, response headers, monotonic sequence, one terminal event, tool pairing, sanitized arguments, Draft staging before completion, heartbeat, timeout, retryability after validation, and worker continuation after consumer close
- `npm.cmd run lint --prefix frontend`: passed
- `npm.cmd run build --prefix frontend`: passed outside the sandbox after sandbox `spawn EPERM`
- `npm.cmd run test:smoke --prefix frontend`: `18 passed`
- Playwright parser tests cover split UTF-8 chunks, CRLF, heartbeats, multi-line data, unknown events, and invalid payloads

Not proven:

- real Responses API token streaming
- live MCP progress while the provider executes `tool_search`
- browser or proxy disconnect behavior against production infrastructure

## Stage 09 Targeted Hardening Gate

Date: public snapshot

Scope:

- account-scoped Memory isolation when no account is selected
- current-user quote authority for Memory activation
- account, target, and force-refresh binding for Draft live-read evidence
- optimization `current_state` semantic verification against the bounded live-read result
- same-key retry after a failed client submission
- turn lease derived from the configured turn deadline
- persisted turn identity in SSE events, start-failure cleanup, and contiguous browser sequence validation
- query-aware active Memory recall, fixed recency decay, and candidate confirmation/rejection

Local evidence:

- `.venv\Scripts\python.exe -m pytest tests -q`: `177 passed, 1 skipped`
- `.venv\Scripts\python.exe -m pytest tests\test_docs_quality.py -q`: `10 passed`
- `npm.cmd run lint --prefix frontend`: passed
- `npm.cmd run build --prefix frontend`: passed outside the sandbox after sandbox `spawn EPERM`
- `npm.cmd run test:smoke --prefix frontend`: `18 passed`

Not proven:

- provider field-name and budget-unit variants outside the covered optimization state fields
- real provider behavior for every write-tool schema variant
- a real OpenAI or live Meta call in this hardening pass


## Stage 09 Meta Credential Gate

Date: public snapshot

Scope:

- non-expiring Meta System User token
- official Meta Ads MCP connectivity
- readable account verification

Recorded results:

- Token Debugger: valid, correct App ID, `expires_at=never`
- `scripts/doctor.py`: official MCP reachable and ready, 98 tools
- `scripts/verify_meta_access_token.py --account-limit 10`: passed, 4 readable accounts
- Token value is stored only in `.env` and is not present in documentation, source, Memory, cache, trace, or logs

Not proven:

- live Meta writes
- E2E model behavior on inactive accounts


## Stage 09 Real Small-Batch E2E

Date: public snapshot

Scope:

- real OpenAI Responses API
- official Meta Ads MCP and real ad accounts
- account brief with no recent performance data
- Draft attempt on an active Campaign with insufficient evidence

Recorded results:

- OpenAI connection check: `gpt-6-luna` returned `OPENAI_OK` (13 input, 18 output tokens).
- Meta credential: valid System User token, `expires_at=never`, 4 readable accounts.
- Official MCP: reachable and ready, 98 tools.
- Empty-account brief: HTTP 200, 11 steps, actual usage 20,627 input / 483 output tokens; reported zero last-7-day spend and unavailable metrics.
- Draft attempt: HTTP 200, 11 steps, actual usage 27,945 input / 800 output tokens; resolved `INVESTIGATE`, zero Drafts, no live write.
- Active Campaign state observed: daily budget 30 USD, status ACTIVE, last-7-day spend 0 USD, impressions/clicks/results unavailable, Learning state and comparison evidence missing.
- A separate continuation turn hit the 90-second deadline; the Draft investigation completed with a 180-second deadline.

Observed problems:

- Both completed turns consumed 11 of the 12 allowed steps.
- `submit_result` was rejected multiple times because evidence fields were placed below `evidence` instead of the required top level.
- Latency is close to the configured turn deadline for real, tool-heavy turns.

Not proven:

- successful Draft generation from a Campaign with sufficient current performance evidence
- multi-turn continuation within a 90-second deadline
- live Meta write execution


## Stage 09 Direct Draft Mode Gate

Date: public snapshot

Scope:

- direct creation through the official Meta Ads MCP Draft Mode
- activation and publication blocking
- execution logging

Recorded results:

- `ads_create_campaign` created Draft object `<campaign_draft_id>`.
- Draft readback returned `ad_object_type=campaign`, action `add`, draft status `EDITING`, validation status `VALIDATED`, source `mcp_campaign_creation`.
- The live campaign list did not include the Draft object.
- Execution log `<execution_log_id>` recorded source `direct_draft:<campaign_draft_id>` with status `succeeded`.
- Group hierarchy Draft creation succeeded: Campaign `<campaign_draft_id>` -> Ad Set `<ad_set_draft_id>` -> Ad `<ad_draft_id>`.
- Ad Set readback: `ad_object_type=adset`, parent Campaign ID matches, status `EDITING`, validation `VALIDATED`.
- Ad readback: `ad_object_type=ad`, parent Ad Set ID matches, status `EDITING`, validation `VALIDATED`.
- Ad Draft reused existing Creative `<creative_id>`; no new Creative was created.
- A first Ad attempt without Creative exposed a provider-result error handling bug. No Ad was created; the code now treats MCP `error_message` payloads as failures. The successful retry used the existing Creative.
- Activation, update, delete, and publish tools remain blocked.
- Local suite: `183 passed, 1 skipped`; frontend lint/build and 18 Playwright smoke tests passed.

Not proven:

- full campaign/ad set/ad/creative Draft creation with real creative assets
- publication or activation behavior


## Stage 09 DeepSeek Provider Gate

Date: public snapshot

Scope:

- DeepSeek OpenAI-compatible Chat Completions provider
- portable Skill-scoped tool exposure without `tool_search`
- default model `deepseek-flash` with `high` reasoning effort

Recorded results:

- DeepSeek model catalog: `deepseek-flash`, `deepseek-v4-pro`
- Function calling probe: `deepseek-v4-pro` returned an `echo` tool call with valid JSON arguments.
- `deepseek-v4.1-flash` is not an API model ID; the supported alias is `deepseek-flash`.
- Real Agent turn through `POST /api/agent/turn`: HTTP 200, 5 steps, `account_brief` loaded and submitted, 11,335 input / 1,116 output tokens.
- The provider used portable tool exposure; no OpenAI `tool_search` call was required.
- OpenAI remains available by setting `LLM_PROVIDER=openai`.
- Local verification: `184 passed, 1 skipped`; frontend lint/build and 18 Playwright smoke tests passed.
- A 7-turn context-window E2E completed with historical Campaign data: Case 1 account brief, Case 2 performance diagnosis, Case 3 optimization-draft investigation, plus context recall.
- Skills hit: `account_brief`, `performance_diagnosis`, `optimization_draft`.
- Turn 7 context manifest: recent messages 10, older messages 2, summary tokens 556, Memory records 1, active Skills 3. Progressive disclosure and summary compaction were observed in a real turn.
- Real MCP tools exercised included `ads_get_ad_entities`, `ads_get_field_context`, `ads_get_errors`, `ads_account_get_activity_logs`, and `ads_insights_performance_trend`.
- No OpenAI provider request was made. A DeepSeek provider hang was resolved by disabling the SDK's inner retry layer; the retry then completed.
- Actual input tokens per completed turn ranged from 12,218 to 53,160. The configured 36,000-token estimate is not yet enforced as a hard provider-call cap because active Skill tool schemas can exceed the model budget.

Not proven:

- DeepSeek behavior across the full Chinese media-buyer case set
- DeepSeek with every official MCP tool group
- live activation/publication


## Stage 09 Network Reachability Check

Date: public snapshot

- VPN disabled on the test host.
- `scripts/doctor.py`: official Meta Ads MCP unreachable, `WinError 10060` connection timeout, 0 tools.
- `scripts/verify_meta_access_token.py --account-limit 3`: Meta Graph API unreachable, `WinError 10060`.
- DeepSeek provider remains independently reachable.
- Current conclusion: real Meta Skill evaluation requires the VPN/proxy path or a deployment network with outbound HTTPS access to `mcp.facebook.com` and `graph.facebook.com`.
