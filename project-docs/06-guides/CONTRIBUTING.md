# Contributing

## Status

- Document status: active contribution guide
- Source of truth: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](../00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md)

## Branches

- Keep `main` runnable.
- Use `feature/*` for product or agent changes.
- Use `fix/*` for quality, safety, encoding, and regression fixes.

## Local Checks

```powershell
$env:OPENAI_API_KEY=""
.venv\Scripts\python.exe -m pytest tests -q
npm.cmd run lint --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run test:smoke --prefix frontend
```

Real OpenAI or Meta checks require explicit intent. They are not part of the default test suite.

## Agent Rules

- Keep one bounded ReAct loop.
- Keep tools read-only or draft-only.
- Keep draft approval separate from execution.
- Keep trace summaries compact and redacted.
- Do not add SaaS, non-Meta channels, batch publishing, or a second chat route.
- Add focused tests with each agent or tool change.
