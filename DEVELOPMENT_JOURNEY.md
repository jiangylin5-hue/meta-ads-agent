# Development Journey

This public repository is a curated release snapshot. Exact development dates, private iteration commits, operational logs, and customer identifiers are intentionally excluded. The engineering progression is represented by five stages.

## Stage 1: Product Boundary And Bounded Loop

Defined a narrow Meta Ads copilot for one account, one chat surface, a visible trace, and reviewable action records. Built a provider-neutral ReAct loop with explicit step, time, observation, and output budgets. Code owns authority; the model chooses only from exposed tools.

## Stage 2: Official MCP And Project Skills

Moved to the official Meta Ads MCP and added dynamic tool discovery, authentication isolation, bounded observations, and deferred or portable tool exposure. Introduced 12 project Skills with `SKILL.md`, machine-readable contracts, evidence gates, and on-demand references. The model starts with a compact Skill catalog and receives only the active Skill tool scope.

## Stage 3: Context, Memory And Task Continuity

Added a five-round conversation window, structured summary compaction, active Skill carry-forward, resumable task progress, and a structured tool ledger. Long-term Memory stores explicit preferences, habits, decisions, account profiles, and outcomes. Account directories, account context, and MCP read results use TTL caches with visible freshness.

## Stage 4: Safety, Consistency And Draft Workflow

Added per-session turn leases, idempotent replay, optimistic versions, retry-safe persistence, and explicit conflict responses. Only four create tools can reach Meta Draft Mode: campaign, ad set, ad, and creative. Activation, updates, deletes, and publication remain code-blocked. Direct Draft creation is execution-logged and never presented as live.

## Stage 5: Provider Portability And End-to-End Validation

Added ordered SSE progress events while retaining JSON responses. Added a DeepSeek OpenAI-compatible provider with high-reasoning configuration, bounded retries, portable Skill-scoped tools, and provider/model context metadata. Validated real Meta MCP reads and multi-turn behavior across historical account analysis, performance diagnosis, optimization-draft investigation, Memory persistence, Skill carry-forward, and summary compaction.

## Engineering Principles

- Code decides authority, budgets, permissions, and persistence.
- Models select from exposed tools; they do not bypass host policy.
- Missing and stale data stay visible.
- Current provider data outranks cache and historical Memory.
- Every write-like transition has a code-enforced non-live boundary.
