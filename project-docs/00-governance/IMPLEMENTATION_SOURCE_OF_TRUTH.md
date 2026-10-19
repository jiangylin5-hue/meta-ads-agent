# Implementation Source Of Truth

## Status

- Document status: active
- Active Stage: Stage 09 - Context And Agent Memory
- Active stage file: [STAGE_09_CONTEXT_AND_AGENT_MEMORY.md](../03-stages/STAGE_09_CONTEXT_AND_AGENT_MEMORY.md)
- Product charter: [PROJECT_CHARTER.md](../01-product/PROJECT_CHARTER.md)
- Functional outline: [FUNCTIONAL_OUTLINE.md](../01-product/FUNCTIONAL_OUTLINE.md)

## Operating Rule

Read this file and the active stage document before implementation. Work must stay inside the active stage. Record out-of-scope work as a `next-stage candidate`.

Plan, task split, acceptance criteria, and progress states go into the active stage document before implementation.

## Active Runtime Rules

- One chat entry point: `POST /api/agent/turn`
- One bounded ReAct loop: `backend/agent/runtime.py`
- The same `POST /api/agent/turn` route returns ordered SSE execution events when `Accept` includes `text/event-stream`; JSON stays compatible
- Official Meta Ads MCP tools are discovered from `https://mcp.facebook.com/ads` and registered in a `meta_ads` namespace
- OpenAI Responses mode uses deferred loading and `tool_search`; DeepSeek portable mode exposes only active Skill tools
- The model sees only the short Skill catalog first, loads at most four Skills per turn, and may call only tools in the loaded Skill groups
- 12 project-level Skill folders live in `backend/skills/`; each has `SKILL.md`, `contract.json`, and references
- The model loads Skill bodies with `load_skill` and references with `read_skill_reference` only when needed
- Code enforces machine-readable Skill input gates before MCP calls and requires a successful read before write-like drafts
- Active Skills submit per-skill results; code validates each output contract and evidence, while the model chooses `resolved_decision` and explains differing decisions
- Official `ads_create_campaign`, `ads_create_ad_set`, `ads_create_ad`, and `ads_create_creative` create non-published Meta Draft objects through Draft Mode; never activate or publish
- All other official `ads_*` write-like tools remain local staging or forbidden; activation/publication is code-blocked
- No model-callable path executes a Meta write
- Live execution remains disabled (`410 execution_disabled_in_demo`)
- Context keeps five recent conversation rounds and a structured summary of older dialogue
- The context budget is 36,000 estimated input tokens with a 4,000 output reserve; active Skill instructions are carried forward
- The runtime defaults to 16 model-decision steps, hard ceiling 24, and a 600-second turn deadline
- The default configured model is DeepSeek `deepseek-flash` with `high` reasoning effort; OpenAI remains an optional provider
- Long-term Memory is scoped to user or account; short-term task state stores progress and a structured tool ledger
- Account directory, prompt-ready account context, and MCP read results use persistent TTL caches; Draft creation still requires a live current-state read with `force_refresh=true`
- One active agent turn is allowed per session through a database lease
- A completed `idempotency_key` replays its stored response; a different payload with the same key is rejected
- Session and task state writes use optimistic version checks and return explicit conflicts instead of silent overwrites
- Meta access uses a non-expiring System User token (`expires_at=never`; 永不过期) stored only in `.env`; token values never enter docs, prompts, Memory, cache, trace, or source

## Current Stage

Stage 09 adds bounded context management and agent Memory. The runtime keeps five recent conversation rounds, summarizes older dialogue, carries task progress and active Skills, persists typed long-term Memory, and caches account data with TTL. The Stage 08 MCP-native Skill runtime and draft-only safety boundary remain active.

Database simplification, Redis removal, vector retrieval, and live execution design remain deferred.

## Stage Lifecycle

1. Open: scope, non-goals, acceptance criteria.
2. Plan: tasks, dependencies, progress states.
3. Implement: active-stage scope only.
4. Progress update: update `Current Progress` after each task.
5. Verify: record commands, results, and risks.
6. Close: require explicit user confirmation before switching stages.

## Next Stage Rule

The next stage starts only after Stage 09 closure and explicit user confirmation. Its plan must state why it exists, what is allowed, what is excluded, acceptance criteria, verification commands, and required document updates.
