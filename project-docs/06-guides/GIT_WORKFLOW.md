# Git Workflow

## Status

- Document status: active workflow reference
- Source of truth: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](../00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md)

## Branch Policy

- `main` should stay runnable and locally verifiable.
- Use short-lived `feature/*` or `fix/*` branches for planned work.
- Keep commits grouped by behavior or boundary, not by file type alone.

## Safety

- Do not commit `.env`, runtime reports, local databases, caches, build output, or browser artifacts.
- Keep line endings LF-normalized through `.gitattributes`.
- Do not use destructive history rewrites on shared branches.
- Do not commit generated `.next` changes.

## Required Evidence

Agent loop or tool change:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_agent_loop.py tests\test_project_boundaries.py -q
```

Backend change:

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

Frontend behavior change:

```powershell
npm.cmd run lint --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run test:smoke --prefix frontend
```

Documentation or repository hygiene:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_docs_quality.py tests\test_git_hygiene.py -q
```

Real OpenAI tool-call smoke:

```powershell
.venv\Scripts\python.exe scripts\verify_mcp_tool_agent.py --spend-credits
```

Name the command and result in the delivery note. Separate fake-model, real OpenAI, and real Meta evidence.

## Review Checklist

- one chat route
- no separate intent router or fixed role pipeline
- no model-callable write tool
- draft approval separate from execution
- trace and error summaries compact
- no secrets or raw provider payloads in prompts or traces
