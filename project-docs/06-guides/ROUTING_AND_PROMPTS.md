# Agent Tools And Tool Search

## Status

- Document status: active guide
- Source of truth: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](../00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md)
- Runtime reference: [AGENT_WORKFLOW.md](../02-architecture/AGENT_WORKFLOW.md)

## Routing Decision

There is no separate business-intent router. The model sees:

- the `meta_ads` namespace
- `tool_search`
- `ask_user`
- selected-account context

The model searches for the MCP tools needed by the current question.

## Tool Loading

All MCP function definitions use `defer_loading=true`. The Responses request includes `tool_search`, so full definitions enter context only when selected. Tool names are preserved.

The model can request a namespace or query; the trace records the search and the loaded tool names.

## Prompt Surface

One short system prompt lives in `backend/agent/prompts.py`.

Prompt rules:

- use tool search before specialized tasks
- use tools before account-specific claims
- separate facts, assumptions, and missing data
- collect current state and evidence before a write-like tool
- write-like tools create drafts and never execute
- omit raw media data
- ask at most one focused question
- keep the final answer short

## Write Boundary

The model may see names such as `update_campaign`, but the registry routes them to local drafts. The model schemas require evidence, recommendation, and risk level.

`AGENTS.md` documents the rule. The code enforces it.

## Context Budget

- deferred MCP schemas
- 16,000-character general result cap
- 4,000-character media result cap
- no raw base64 or data URLs

## Validation

```powershell
.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py tests\test_project_boundaries.py -q
.venv\Scripts\python.exe -m pytest tests -q
npm.cmd run lint --prefix frontend
npm.cmd run test:smoke --prefix frontend
```
