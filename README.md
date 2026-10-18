# Meta Ads Agent

## Status

- Document status: public portfolio README
- Project documentation: [project-docs/README.md](project-docs/README.md)
- Active implementation stage: [STAGE_09_CONTEXT_AND_AGENT_MEMORY.md](project-docs/03-stages/STAGE_09_CONTEXT_AND_AGENT_MEMORY.md)

A portfolio snapshot of a bounded Meta Ads copilot built around the official Meta Ads MCP, project-level Skills, DeepSeek/OpenAI-compatible model providers, durable context, and approval-aware Draft workflows.

> This is a curated public release snapshot. Internal development history, operational logs, credentials, and customer account identifiers are intentionally excluded. It represents the final engineered state rather than the private iteration log.

## What It Demonstrates

- A bounded ReAct loop with explicit step, time, token, and tool budgets.
- Progressive disclosure: a short Skill catalog is visible first; only active Skill tools are exposed.
- 12 project Skills covering account briefs, diagnosis, audits, creative, optimization, planning, tracking, audience, catalog, competitive research, experiments, and policy review.
- Official Meta Ads MCP discovery with provider-neutral tool execution.
- DeepSeek `deepseek-flash` with high reasoning as the default provider; OpenAI Responses remains optional.
- Five recent conversation rounds plus structured summary compaction.
- Long-term user/account Memory and resumable task state.
- Account directory, account context, and MCP read-result caches with TTL and stale fallback.
- Idempotent turns, per-session leases, optimistic state versions, and conflict responses.
- Direct Meta Draft Mode creation for campaign, ad set, ad, and creative objects.
- Activation, updates, deletes, and publication are code-blocked.
- Execution logs for direct Draft creation.

## Architecture

```text
Next.js workbench
  -> POST /api/agent/turn (JSON or SSE)
  -> turn lease + idempotency + version checks
  -> context assembler
       - five recent rounds
       - rolling summary
       - active Skills
       - task progress
       - long-term Memory
       - selected-account cache
  -> bounded ReAct loop
       - DeepSeek Chat Completions or OpenAI Responses
       - Skill-scoped Meta MCP tools
       - structured observations
  -> final answer / local action record / non-live Meta Draft
```

Core implementation:

- `backend/agent/runtime.py`: ReAct loop and provider-neutral tool handling
- `backend/agent/deepseek.py`: DeepSeek Chat Completions adapter
- `backend/agent/tools.py`: MCP discovery, budgets, Draft routing, activation blocking
- `backend/agent/context.py`: five-round window, summary contract, token estimates
- `backend/services/turn_control.py`: turn leases, idempotency, replay
- `backend/services/long_term_memory.py`: typed Memory
- `backend/services/task_state.py`: task progress and tool ledger
- `backend/services/account_cache.py`: account and MCP result caches
- `backend/skills/`: 12 project Skills with contracts and on-demand references
- `frontend/`: single-page account, chat, context, trace, and action workspace

## Safety Boundary

- All Meta credentials stay in environment variables and never enter prompts, Memory, caches, traces, or source.
- Only four create tools may reach MCP: `ads_create_campaign`, `ads_create_ad_set`, `ads_create_ad`, `ads_create_creative`.
- Official Draft Mode returns non-live Draft objects.
- `ads_activate_entity`, update, delete, and publish paths are unavailable to the model.
- Draft approval is not execution.
- Live execution returns `410 execution_disabled_in_demo`.

## Run Locally

```powershell
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements.txt
docker compose up -d postgres
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8010
npm.cmd install --prefix frontend
npm.cmd run dev --prefix frontend
```

Open `http://127.0.0.1:3000/app`.

Copy `.env.example` to `.env` and provide your own credentials. Never commit `.env`.

## Verification

```powershell
$env:OPENAI_API_KEY=""
.venv\Scripts\python.exe -m pytest tests -q
npm.cmd run lint --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run test:smoke --prefix frontend
```

The local verification suite covers the ReAct loop, 12 Skill contracts, progressive tool exposure, context compaction, Memory/task state, account caches, turn leasing/idempotency, SSE, Draft safety, and frontend flows.

## Known Constraints

- Meta Graph API and the official Meta Ads MCP require outbound HTTPS access to Meta; some networks require a VPN or proxy.
- Meta account data can be empty or historical. The agent must surface missing and stale data instead of inventing current facts.
- Token estimates are conservative and may require calibration against provider usage.
- Multi-Skill tool schemas can still raise actual provider input beyond the configured estimate; hard budget enforcement remains an area for further calibration.

## Development Journey

See [DEVELOPMENT_JOURNEY.md](DEVELOPMENT_JOURNEY.md) for the five-stage engineering journey. The public snapshot intentionally omits exact development dates and private iteration history.

## Documentation

- `project-docs/01-product/`: product scope and functional behavior
- `project-docs/02-architecture/`: runtime, MCP, data, and workflow design
- `project-docs/03-stages/STAGE_09_CONTEXT_AND_AGENT_MEMORY.md`: active implementation contract
- `project-docs/05-quality/`: verification and quality evidence
