# Stage 09 Context And Agent Memory

## Status

- Stage status: active
- Document status: active stage file
- Source of truth: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](../00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md)
- Previous stage: private development history (not included in this public snapshot)
- Opened: public snapshot by explicit user confirmation

## Goal

Keep the agent context bounded and auditable while preserving task continuity. The runtime uses a five-round sliding window, a structured summary for older dialogue, long-term memory for stable user and account knowledge, short-term task progress, and TTL-based account data caches.

```text
current message
-> task state + active Skills + relevant Memory
-> current account context from cache or one refresh
-> latest five complete conversation rounds
-> structured summary of older rounds
-> bounded current-turn tool observations
-> Responses ReAct loop
```

## Why This Stage Exists

Private history is durable, but the old runtime silently dropped messages after a fixed count and only used the latest eight messages. It had no summary, task continuity, durable typed Memory, or account data cache. Repeated Meta reads increased latency and token usage, especially with many accounts and unreliable network access.

## Scope

- Add a token-budgeted ContextAssembler with five recent conversation rounds.
- Keep the complete instructions of active task Skills and allow progressive loading of additional Skills.
- Keep current-turn tool call arguments and observations; keep a bounded task-level tool ledger.
- Add model-generated structured summaries for conversation older than the five-round window, with a deterministic fallback.
- Add long-term Memory for explicit preferences, habits, confirmed decisions, account profiles, and outcomes.
- Add short-term task state with goal, progress, next step, blockers, active Skills, and tool ledger.
- Add persistent caches for account directory, account context, and MCP read results with TTL and stale fallback.
- Add minimal UI for context usage, task progress, Memory in use, freshness, and Memory deletion.
- Add an SSE execution-progress stream on the existing chat route while preserving JSON responses.
- Keep one chat route and the existing ReAct loop.

## Non-Goals

- No live Meta writes or execution.
- No non-Meta channels.
- No multi-tenant workspace or role system.
- No vector search or embedding dependency in this stage.
- No bypass of current-state reads before Draft creation.
- No raw provider payload, token, cookie, data URL, or media bytes in Memory, cache, model context, or trace.

## Context Contract

- Recent conversation window: five complete user/assistant rounds.
- Input budget: 36,000 estimated tokens; output reserve: 4,000 tokens.
- Soft compression threshold: 80% of the input budget.
- Active Skill contents: full instructions for Skills loaded by the current task, up to the existing four-Skill limit.
- References: only references explicitly loaded by the model.
- Tool calls: current-turn arguments and results remain complete within result budgets; the task ledger keeps bounded structured summaries and evidence references.
- Memory: user-scope preferences and account-scope decisions/profiles; only active records are injected.
- Account data: selected-account compact context; fresh cache is reused, stale cache is labeled, Draft creation still requires a live read.
- Summary: source message ids, checkpoint, account references, and explicit fact/hypothesis separation.

## Storage

```text
user_sessions.compressed_context_json  session rolling summary and checkpoint
agent_tasks                            active task, progress, Skills, tool ledger
agent_memory_records                   typed long-term Memory with supersession
mcp_tool_result_cache                  bounded read-tool result cache with TTL
meta_account_directory_cache           account selector directory cache
meta_account_context_cache             prompt-ready selected-account cache
```

Existing Meta entity and insight tables remain the normalized data source when snapshot persistence is used.

## Local Tools

Add two local tools:

```text
save_memory   save a typed user/account Memory candidate
update_task   update current goal, progress, next step, blockers, and constraints
```

Both tools are schema-validated and never accept filesystem paths or provider tokens.

## Tasks

| Task | Status | Scope |
| --- | --- | --- |
| S9-T1 | complete | Stage plan, governance, boundaries, acceptance |
| S9-T2 | complete | ContextAssembler, token budget, five-round window, structured summary |
| S9-T3 | complete | Task state, progress, active Skill carry-forward, tool ledger |
| S9-T4 | complete | Long-term Memory schema, write validation, retrieval, deletion API |
| S9-T5 | complete | Account directory, account context, MCP result caches with TTL and stale fallback |
| S9-T6 | complete | Runtime integration, Memory/task local tools, trace and minimal UI |
| S9-T7 | complete | Focused tests, full verification, quality evidence |
| S9-T8 | complete | Backend hardening: session turn lease, request idempotency, optimistic versions |
| S9-T9 | complete | Conflict-path tests and hardening verification |
| S9-T10 | complete | SSE turn event stream, shared JSON/SSE orchestration, timeout and disconnect policy |
| S9-T11 | complete | SSE protocol, parser, UI state, and end-to-end verification |
| S9-T12 | complete | Targeted hardening: Memory scope/source, Draft live-read binding, retry key reuse, lease alignment |
| S9-T13 | complete | Optimization Draft current_state semantic verification against live-read evidence |
| S9-T14 | complete | SSE turn identity, start-failure cleanup, and contiguous sequence hardening |
| S9-T15 | complete | Simple query-aware Memory recall, recency decay, and candidate confirmation |
| S9-T16 | complete | Rotate Meta System User token and document non-expiring credential policy |
| S9-T17 | complete | Real OpenAI and Meta MCP small-batch E2E on inactive accounts |
| S9-T18 | complete | Raise default ReAct step and turn deadline budgets |
| S9-T19 | complete | Allow direct Meta Draft Mode creation tools with activation blocked |
| S9-T20 | complete | Add DeepSeek Chat Completions provider with portable Skill-scoped tools |

## Acceptance Criteria

- The model receives at most five complete recent conversation rounds plus the current message.
- Older dialogue is represented by a structured summary with source message ids.
- The full context is estimated against a 36,000-token input budget; tool observations have a current-turn cumulative cap.
- Active task Skills remain available in full on later turns without reloading every Skill catalog entry.
- Task goal, progress, next step, blockers, and tool ledger survive across turns.
- Long-term Memory is scoped to user or account and injected only when relevant; user deletion works.
- Account directory and prompt-ready account context are cached; a cached MCP read avoids provider access while fresh.
- Stale cached account data is visibly labeled and can answer analysis questions when the network fails.
- Draft creation still requires a successful live read in the current turn.
- Draft evidence must match the selected account and target entity, and the matching read must use `force_refresh=true`.
- Optimization Draft `current_state` values must match fields present in the matching live read; unverifiable or mismatched values fail closed.
- Memory context never includes account-scoped records when no account is selected.
- Active Memory recall uses query/task lexical relevance, bounded time decay, and a per-kind selection limit.
- Only user confirmation promotes a candidate Memory to active; rejection removes it from the pending set.
- Only a quote from the current user message can activate a model-written Memory record.
- Client retries reuse the original idempotency key.
- The turn lease defaults to the configured turn deadline plus a bounded release buffer.
- Existing draft-only and execution-disabled safety boundaries remain intact.
- `POST /api/agent/turn` returns SSE when `Accept` includes `text/event-stream` and keeps the JSON response otherwise.
- SSE events are ordered, numbered, sanitized, emitted during execution, and end with exactly one terminal event.
- SSE event `turn_id` matches the persisted turn id, sequence numbers are contiguous, and stream-start failure releases the turn lease.
- Browser code parses POST SSE safely and replaces temporary streaming state with the final JSON-compatible response.
- Backend, frontend lint/build/smoke, and documentation checks pass.

## Verification

```powershell
$env:OPENAI_API_KEY=""
.venv\Scripts\python.exe -m pytest tests -q
npm.cmd run lint --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run test:smoke --prefix frontend
```

## Current Progress

- public-snapshot: Stage opened by explicit user confirmation after Stage 08 closure.
- public-snapshot: Added ContextAssembler, five-round window, 36k input budget, structured summary and deterministic fallback.
- public-snapshot: Added task state, active Skill carry-forward, task tool ledger, typed Memory, save/delete API and minimal context UI.
- public-snapshot: Added account directory, account context, and MCP read-result caches with TTL and stale fallback.
- public-snapshot: Applied migration 0006 to local PostgreSQL.
- public-snapshot: Added S9-T10/T11 after user approval of the SSE implementation review; existing S9-T8/T9 hardening work remains active and unchanged.
- public-snapshot: Added runtime event callbacks, sanitized tool events, turn deadline checks, SSE worker queue, heartbeat, replay, and failure mapping.
- public-snapshot: Added POST SSE parsing and workbench streaming state with result validation and disconnect handling.
- public-snapshot: Verified SSE event order, tool pairs, Draft staging, timeout, retryable failure, and disconnect continuation.
- public-snapshot: Opened S9-T12 for the user-selected Memory, Draft evidence, retry-key, and lease hardening items.
- public-snapshot: Completed S9-T12. Account-scoped Memory is excluded without a selected account, only current user quotes can activate Memory, Draft live-read evidence is account/target/force-refresh bound, retries reuse the pending key, and the lease follows the turn deadline.
- public-snapshot: Opened S9-T13 to verify optimization Draft current_state values against the bounded live-read result.
- public-snapshot: Completed S9-T13. Optimization Drafts now compare budget, status, sample size, learning state, and comparison window against the matching force-refresh live read, reject mismatches or missing fields, and stage the code-verified state.
- public-snapshot: Opened S9-T14 for the focused SSE audit findings.
- public-snapshot: Completed S9-T14. SSE events use the persisted turn id, worker-start failure runs turn failure and lease cleanup, and the browser rejects non-contiguous event sequences.
- public-snapshot: Opened S9-T15 for simple Memory recall and candidate lifecycle closure.
- public-snapshot: Completed S9-T15. Active Memory is ranked by query/task token overlap, confidence, kind, and fixed recency decay; candidates can be confirmed or rejected from the Context panel.
- public-snapshot: Completed S9-T16. Replaced the expired Meta credential with a non-expiring System User token, updated both environment variables, verified 98 MCP tools and 4 readable accounts, and documented the credential policy without storing the token value.
- public-snapshot: Completed S9-T17. Ran a small real OpenAI/Meta E2E: an empty account brief completed in 11 steps with zero spend and unavailable metrics; an active Campaign with a $30 daily budget but no last-7-day performance evidence returned INVESTIGATE with zero Drafts. No live Meta write or execution occurred.
- public-snapshot: Completed S9-T18. Default runtime budget is 16 model-decision steps, hard ceiling 24, and 600 seconds per turn.
- public-snapshot: Completed S9-T19. Four official create tools use Meta Draft Mode directly; activation/publish/update/delete remain blocked and each direct Draft writes an execution log.

## S9-T15 Scope

- Rank active Memory with simple English/CJK token overlap against the current message and task state.
- Add kind-specific recency decay and a per-kind selection limit without new dependencies or schema fields.
- Add confirm/reject actions for candidate Memory and display them in the Context panel.

## S9-T14 Scope

- Tag SSE events with the persisted turn id instead of the trace id.
- Run turn failure and lease release when the SSE worker thread cannot start.
- Require contiguous client sequence numbers and cover a missing-event response.

## S9-T13 Scope

- Store a compact whitelisted state snapshot in each successful live-read evidence record.
- Verify optimization Draft budget, status, sample size, learning state, and comparison window against that snapshot.
- Reject mismatched or unverifiable required state before staging the Draft.

## S9-T12 Scope

- Exclude account-scoped Memory when the request has no selected account.
- Restrict active Memory quotes to the current user message and keep the source role explicit.
- Record successful live reads as structured evidence and match Draft account, target, and refresh mode.
- Reuse the same client idempotency key for retries of the same pending submission.
- Derive the default turn lease from the configured agent turn timeout.

## SSE Streaming Scope

- Keep `POST /api/agent/turn` as the only chat entry point.
- Stream execution events with a 15-second heartbeat; final answer text remains in `turn.completed.response`.
- Share session, Memory, Task, Draft, trace, idempotency, and response assembly between JSON and SSE.
- Continue and persist a turn after the browser disconnects; the client does not retry automatically.
- Enforce per-call provider timeouts plus a configurable 300-second turn deadline.
- Exclude provider-internal `tool_search` from live start/finish events; it remains in the final compact trace.
- Send one `turn.failed` event after streaming begins and never send `turn.completed` for the same turn.

## Verification Record

- Backend: `.venv\Scripts\python.exe -m pytest tests -q` -> `184 passed, 1 skipped`.
- Database schema: `scripts/check_database_schema.py` passed with 40 tables; Alembic is at `0007_stage_09_hardening`.
- Database turn-control smoke: passed (create turn, complete, replay completed response, release lock, cleanup temporary rows).
- Frontend lint passed.
- Frontend production build passed outside the sandbox after the sandbox returned `spawn EPERM`.
- Desktop and mobile Playwright and SSE parser smoke passed (`18 passed` after S9-T14).
- Documentation quality after S9-T12: `10 passed`.
- Real OpenAI/Meta small-batch E2E was completed after the credential rotation; live activation/publication was not executed.
- public-snapshot: Backend hardening started after user direction; evaluation remains deferred.
- public-snapshot: Added session turn leases, request idempotency, turn response replay, message/task retry dedupe, and optimistic session/task versions.
- public-snapshot: Applied migration `0007_stage_09_hardening` to local PostgreSQL.
- public-snapshot: SSE route, parser, workbench, timeout, failure, replay, and disconnect tests passed.
- public-snapshot: Meta credential check passed after S9-T16: MCP reachable and ready with 98 tools; token valid for App <META_APP_ID> with `expires_at=never`; 4 readable accounts returned.

## Hardening Scope

- Allow one active agent turn per session through a renewable database lease.
- Replay a completed idempotent turn instead of running the model twice.
- Reject the same idempotency key when the request payload differs.
- Add optimistic version checks to session and task persistence.
- Return an explicit conflict instead of silently overwriting state.
- Keep frontend work limited to supplying and reusing an idempotency key for the same pending submission.

## Remaining Risks

- Token estimation without a provider tokenizer is approximate and must be calibrated with actual usage.
- Automatic Memory writes can preserve incorrect inferences; inferred records remain candidates until confirmed.
- Account data cache freshness varies by tool family and can lag provider state.
- Summary and Memory quality still require later model evaluation.
- Final turn writes use per-domain transactions; message and task writes are retry-idempotent, but a process crash can still leave a recoverable partial turn.
- The account directory endpoint returns an empty stale fallback when the first provider read fails; UI error presentation remains basic.
- Optimization Draft semantic checks cover the five required state fields; provider field-name and budget-unit variants still need real Meta replay coverage, and non-optimization Draft state remains shape-validated plus target-bound.
- SSE remains progress streaming with one thread per connection and no Last-Event-ID resume.
- Memory recall uses lightweight lexical overlap rather than embeddings; ranking weights and half-lives still need replay calibration.
- SSE streams execution progress, not provider answer tokens; final answer text arrives in `turn.completed`.
- Provider-internal `tool_search` is visible in the final trace but has no live start/finish event.
- A browser disconnect continues the backend turn; the client reports the interruption and does not retry automatically.
- Real E2E used 11 of 12 steps for both the empty-account brief and the Draft investigation, at roughly 100 seconds per completed turn.
- The model needed repeated `submit_result` attempts to place evidence fields at the contract's required top level.
- A 90-second deadline interrupted a continuation turn; the separate Draft-attempt turn completed with a 180-second deadline.
- Three of four readable accounts had no Campaigns; one account had a single active Campaign with zero last-7-day spend and unavailable performance metrics.
- A real Campaign Draft Mode object was created as Draft `<campaign_draft_id>`; readback showed draft action `add`, draft status `EDITING`, no live Campaign entry, and execution log `<execution_log_id>`.
- The real-agent direct Draft turn could not complete because OpenAI returned APIConnectionError/TLS EOF; the direct Draft registry path and execution log were verified separately.
- DeepSeek `deepseek-flash` with high reasoning had one provider hang before the first tool call. After disabling the SDK retry layer, the retry completed and the full 7-turn E2E passed. Provider latency remains variable.
- DeepSeek `deepseek-v4-pro` function calling was verified with a minimal tool call.
- Completed S9-T20. Added the DeepSeek Chat Completions adapter, set `deepseek-flash` with `high` reasoning effort as the default, and added portable Skill-scoped tool exposure.
- A real DeepSeek agent turn completed in 5 steps with `account_brief`, 11,335 input / 1,116 output tokens, and no OpenAI dependency.
- Completed the 3-case, 7-turn context-window E2E on the historical campaign. Skills hit: `account_brief`, `performance_diagnosis`, `optimization_draft`. Real MCP reads included campaign/account/adset/ad entities, field context, errors, activity logs, and performance trend.
- Context window verification passed on turn 7: 10 recent messages, 2 older messages, 556 summary tokens, 1 active Memory record, and all three Skills carried forward.
- No OpenAI provider request was made. The failed DeepSeek provider attempts did not create or modify any Meta object during the context test.
- The five-round window and summary are real, but actual input usage reached 53,160 tokens in the optimization-draft turn and 46,483 in the final summary turn. The 36,000 estimated input budget is not yet a hard provider-call cap; Skill-scoped tool schemas are the main expansion source.
- Network check with VPN disabled: both `mcp.facebook.com/ads` and `graph.facebook.com` timed out with `WinError 10060`. DeepSeek remained reachable. Real Meta Skill evaluation requires a proxy/VPN or a deployment network with Meta egress access.
- DeepSeek waits were caused by an OpenAI SDK retry layer stacked on the adapter retry loop. SDK retries are now disabled with `max_retries=0`; adapter retries remain bounded and configurable.
- The default runtime budget is raised from 12 to 16 model-decision steps and from 300 to 600 seconds per turn.
- Direct Meta Draft creation is enabled only for `ads_create_campaign`, `ads_create_ad_set`, `ads_create_ad`, and `ads_create_creative`. Official Draft Mode created Campaign draft `<campaign_draft_id>` with draft status `EDITING`; the live campaign list remained unchanged. Activation, updates, deletes, and publication remain blocked.
- Direct Draft creation wrote execution log `<execution_log_id>`.
- Group hierarchy Draft creation succeeded: Campaign `<campaign_draft_id>` -> Ad Set `<ad_set_draft_id>` -> Ad `<ad_draft_id>`, all read back as `EDITING` Draft objects. The Ad reused existing Creative `<creative_id>`; no activation or publication occurred.
