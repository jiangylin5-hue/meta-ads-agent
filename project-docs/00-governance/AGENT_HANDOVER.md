# Agent Handover

## Status

- Document status: active handover reference
- Updated: public-snapshot
- Active stage: [STAGE_09_CONTEXT_AND_AGENT_MEMORY.md](../03-stages/STAGE_09_CONTEXT_AND_AGENT_MEMORY.md)
- Source of truth: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](IMPLEMENTATION_SOURCE_OF_TRUTH.md)

## Thirty Second Summary

This repository is a small Meta ads copilot demo. One Next.js page sends a user message to `POST /api/agent/turn`. `AgentRuntime` runs a bounded ReAct-style loop. The model discovers MCP tools with `tool_search`, reads Meta data, and prepares action drafts. It cannot execute a live write.

The demo is intentionally smaller than the earlier SaaS and multi-role versions of the project.

## Actual Repository State

- The primary chat runtime is `backend/agent/runtime.py`.
- Official Meta Ads MCP tools are discovered at runtime from `https://mcp.facebook.com/ads` and exposed as deferred `meta_ads` tools.
- Four create tools write non-live Meta Draft Mode objects in `backend/agent/tools.py`; all other write-like tools create local drafts or are rejected.
- The only chat route is `/api/agent/turn`.
- The old fixed pipeline and its prompt, memory, intent, and feedback modules are removed.
- Context keeps five conversation rounds, summarizes older dialogue, carries active Skills and task progress, and injects typed Memory plus a compact account cache.
- Account directory, account context, and MCP read results use persistent TTL caches. Draft creation still requires a live read.
- Session history, task state, Memory, cache, and trace persistence remain small shared services.
- The action lifecycle remains, but execution returns `410 execution_disabled_in_demo`.
- PostgreSQL and Redis remain in the infrastructure layer. Their simplification is deferred.

## Product Boundary

- Meta only.
- Copilot only.
- Draft approval is not execution.
- Missing data remains visible.
- A real account change requires an execution log. This demo does not execute.

## Runtime Map

```text
frontend workbench
-> POST /api/agent/turn
-> backend/routes/agent_routes.py
-> backend/agent/runtime.py
-> five-round context + summary + Memory + task/account cache
-> tool_search + meta_ads namespace
-> MCP reads / Draft Mode create tools / local staging for other writes
-> action lifecycle
-> trace service
-> reply + steps + drafts
```

## Read Next

1. [AGENT_WORKFLOW.md](../02-architecture/AGENT_WORKFLOW.md)
2. [CODE_BOUNDARIES.md](CODE_BOUNDARIES.md)
3. [RUNTIME_VERIFICATION.md](../05-quality/RUNTIME_VERIFICATION.md)
4. [STAGE_09_CONTEXT_AND_AGENT_MEMORY.md](../03-stages/STAGE_09_CONTEXT_AND_AGENT_MEMORY.md)
