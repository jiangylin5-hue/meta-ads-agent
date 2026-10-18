# Project AGENTS.md

## Status

- Document status: active agent instructions
- Source of truth: `project-docs/00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md`
- Active stage: `project-docs/03-stages/STAGE_09_CONTEXT_AND_AGENT_MEMORY.md`

This file is the implementation entry point for agents working in this repository. It defines required reading, stage boundaries, runtime rules, and verification expectations.

## Read First

Before implementation, read:

1. `project-docs/00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md`
2. The active stage document referenced by the source of truth
3. `project-docs/01-product/PROJECT_CHARTER.md`
4. `project-docs/01-product/FUNCTIONAL_OUTLINE.md`
5. `project-docs/02-architecture/AGENT_WORKFLOW.md`
6. `project-docs/00-governance/CODE_BOUNDARIES.md`
7. `project-docs/05-quality/RUNTIME_VERIFICATION.md`
8. `project-docs/05-quality/QUALITY_EVIDENCE.md`

For documentation-only work, also confirm that the active stage permits the change.

## Stage Rule

- Work proceeds in stages.
- Plan, task split, acceptance criteria, and progress updates go into the active stage document before implementation.
- Implementation must stay inside the active stage scope.
- Record out-of-scope work as a `next-stage candidate`.
- Update `Current Progress` after each completed task.
- Record verification commands, results, and remaining risks before closing a stage.
- Stage closure and active-stage changes require explicit user confirmation.

## Documentation Standard

- One active implementation source of truth: `project-docs/00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md`.
- One active stage file.
- Keep plans, records, audits, contracts, and registries separate.
- Keep active documents short. Move superseded implementation history to `project-docs/archive/legacy/`; keep current records in `project-docs/04-records/`.
- Every important document needs a status header and links to its source.
- Do not feed large documentation files to the model.

## Product Boundary

- The product is a Meta ads copilot demo.
- The scope is one page, one account selector, one chat surface, one visible tool trace, and approval-gated action drafts.
- Do not add non-Meta channels, SaaS navigation, billing, multi-tenant workspaces, or batch publishing.
- Do not claim that a live Meta account changed unless an execution log exists.
- Keep missing data visible. Do not turn assumptions into facts.

## Runtime Boundary

- `POST /api/agent/turn` is the only chat entry point.
- `POST /api/agent/turn` returns ordered SSE progress events when `Accept` includes `text/event-stream`; requests without it keep the JSON response. Final text is delivered in `turn.completed.response`.
- One agent turn is active per session. The turn lease, idempotency key, and session/task version checks live in backend code; conflicts return 409.
- A completed idempotency key replays the stored response. The same key with a different message or account is rejected.
- `backend/agent/runtime.py` owns the bounded ReAct-style tool loop.
- The model chooses tool calls. Code validates tool names, arguments against JSON Schema, step limits, and permissions. Runtime-only fields are rejected, and malformed argument JSON fails closed.
- There is no separate intent router, fixed multi-role pipeline, or graph framework.
- The runtime exposes 12 project Skill folders under `backend/skills/`. The model sees each `SKILL.md` name and description, calls `load_skill`, and may load at most four Skills per turn. Each Skill can expose references that the model reads only when needed with `read_skill_reference`.
- Active task Skills are carried forward with full instructions. The context keeps five recent conversation rounds, summarizes older dialogue, and estimates a 36,000-token input budget with a 4,000-token output reserve.
- The runtime defaults to 16 model-decision steps with a hard ceiling of 24 and a 600-second turn deadline.
- Long-term Memory is typed and scoped to user or account. Short-term task state stores the current goal, progress, next step, blockers, active Skill ids, and a bounded structured tool ledger.
- Account directory, prompt-ready account context, and MCP read results use persistent TTL caches. Stale cache may support analysis with an explicit `as_of`; before a write-like Draft, the relevant read must use `force_refresh=true` so the cache is bypassed and current state is read live.
- Loaded skill contracts define allowed MCP tool groups and machine-checkable input/evidence gates. OpenAI Responses mode loads schemas with `tool_search`; DeepSeek portable mode exposes only the active Skill tool schemas directly. Tools outside the active scope or missing required account/date/level inputs are denied by code. Evidence requirements validate successful source tools and required evidence fields; optimization Drafts require current budget, status, sample size, Learning state, and comparison window in `current_state`.
- When Skills are active, each Skill submits its own result through `submit_result`. Code validates each result against its own contract; the model chooses `resolved_decision`, and differing Skill decisions require a `conflicts` explanation.
- The three GitHub projects are method and reference sources only. Their full 379-skill trees, CLIs, MCP servers, scripts, and write paths do not enter the runtime.
- Official Meta Ads MCP tools are discovered from `https://mcp.facebook.com/ads` and registered under the `meta_ads` namespace.
- OpenAI Responses mode uses deferred tools and `tool_search`. DeepSeek Chat Completions mode uses portable Skill-scoped tool exposure and does not depend on provider-native tool search.
- The default provider is selected by `LLM_PROVIDER`. `openai` uses `OpenAIResponsesClient`; `deepseek` uses the OpenAI-compatible Chat Completions adapter with model `deepseek-flash` and reasoning effort `high`.
- Route handlers stay thin. Business logic belongs in agent modules or services.
- Trace helpers live in `backend/services/trace_service.py`.

## Safety Boundary

Local agent tools:

```text
ask_user
load_skill
read_skill_reference
submit_result
save_memory
update_task
```

All discovered `meta_ads.*` read tools may be loaded by the model. Official `ads_*` tools outside the read allowlist are write-like and are intercepted by code. Representative names:

```text
ads_create_campaign
ads_create_ad_set
ads_create_ad
ads_create_creative
ads_creative_upload_local_image
ads_creative_upload_media
ads_update_entity
ads_activate_entity
ads_delete_custom_audience
ads_catalog_create
ads_pixel_event_create
```

Forbidden direct execution paths:

```text
execute_action
publish_batch_draft
execute_rollback
provider write methods
```

- Before a write-like tool, read the current entity state and collect evidence.
- Direct Draft creation and remaining local write-like tool names must carry `evidence`, `recommendation`, `risk_level`, and a non-empty `current_state`.
- `backend/agent/tools.py` forwards only the four Draft creation tools to MCP. Every other write-like call is staged locally or rejected. Official Draft Mode returns non-live draft objects; `ads_activate_entity` remains forbidden.
- Every direct Draft creation records an execution log with the account, tool, created entity id, and provider result summary.
- Draft approval is not execution.
- Live execution is disabled in this demo and returns `410 execution_disabled_in_demo`.
- A prompt rule is guidance, not a permit. Code enforcement is required for every write boundary.
- `load_skill`, `read_skill_reference`, `submit_result`, `save_memory`, and `update_task` are local tools with closed IDs or schema-validated objects; they never accept a model-supplied file path.
- Memory records and account caches never store provider tokens, cookies, raw provider payloads, data URLs, or media bytes. Account-scoped Memory is filtered by stable provider account id.
- Each Skill folder contains `SKILL.md`, `contract.json`, and `references/`; the catalog exposes names and descriptions before detailed instructions.

- The configured Meta credential is one non-expiring System User token (`expires_at=never`; 永不过期), stored only in `.env` as `META_ACCESS_TOKEN` and `ADS_MCP_API_TOKEN`.
- Do not expose model-supplied Meta access tokens or copy the configured token into docs, prompts, Memory, cache, trace, logs, or source files.
- Image and video results must omit raw bytes and stay within the media result budget.
- Do not send tokens, cookies, raw provider payloads, data URLs, route source, or large documents to the model or trace.

## Coding Standard

- Follow the existing FastAPI route / route_handler / service layering.
- Keep the Next.js app / feature / component / lib boundaries.
- Prefer small explicit modules over generic frameworks or abstractions.
- Reuse existing services and tests where they still match the current architecture.
- Avoid unrelated refactors. Remove dead code only when the dependency scan proves it is unused.
- Keep user-facing text short and direct.
- Add focused tests for new behavior.

## Verification

Documentation-only changes:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_docs_quality.py -q
```

Runtime or product changes:

```powershell
.venv\Scripts\python.exe -m pytest tests -q
npm.cmd run lint --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run test:smoke --prefix frontend
```

Real OpenAI tool-call smoke, only when explicitly intended:

```powershell
.venv\Scripts\python.exe scripts\verify_mcp_tool_agent.py --spend-credits
```

If a command cannot run, report why, its impact, and the alternative evidence used.

## Final Response

Report:

- changed files
- verification commands and results
- skipped tests
- remaining risks or next-stage candidates
