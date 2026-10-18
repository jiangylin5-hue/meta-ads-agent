# Development Guide

## Status

- Document status: active development guide
- Source of truth: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](../00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md)
- Runtime reference: [AGENT_WORKFLOW.md](../02-architecture/AGENT_WORKFLOW.md)

## Directory Responsibilities

### `backend/agent/`

Owns the bounded tool loop, tool schemas, tool policy, system prompt, and state. Keep the loop readable in one file and put tool implementations in `tools.py`.

### `backend/routes/`

URL registration only.

### `backend/route_handlers/`

HTTP parsing, session loading, runtime invocation, and response shaping. Do not move loop logic into a handler.

### `backend/services/`

Stable capabilities such as Meta reads, metric shaping, session history, trace persistence, and action lifecycle.

### `backend/integrations/`

External API adapters. They do not decide intent or approve actions.

### `frontend/`

Next.js App Router, feature modules, API client, and UI types. Keep the single-page product surface.

## Adding A Tool

MCP tools are discovered from `tools/list`, so a normal server tool needs no hand-written wrapper.

When adding a local tool or changing MCP routing:

1. Add the handler to `backend/agent/tools.py`.
2. Add the schema to `schemas()` or extend the MCP namespace conversion.
3. Classify the tool in `backend/agent/policy.py`.
4. Add a fake-model and registry test.
5. Confirm write-like tools never call MCP.

## Prompt Rules

- Use one short system prompt unless the active stage proves a need for more.
- Use tools before account-specific claims.
- Keep missing data explicit.
- Ask at most one question.
- Keep final answers short.

## Verification

```powershell
$env:OPENAI_API_KEY=""
.venv\Scripts\python.exe -m pytest tests -q
npm.cmd run lint --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run test:smoke --prefix frontend
```
