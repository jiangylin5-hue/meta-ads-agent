# Functional Outline

## Status

- Document status: active functional outline
- Product source: [PROJECT_CHARTER.md](PROJECT_CHARTER.md)
- Runtime source: [AGENT_WORKFLOW.md](../02-architecture/AGENT_WORKFLOW.md)
- Boundary source: [CODE_BOUNDARIES.md](../00-governance/CODE_BOUNDARIES.md)

## Account Connection

The user selects one readable Meta ad account. Account, campaign, and insight reads go through the account gateway. The UI does not claim a connection is healthy unless the status route says it is configured.

## Agent Turn

`POST /api/agent/turn` accepts the message, session id, selected account id, and small frontend context. The runtime loads recent history, runs the bounded tool loop, and returns:

- short reply
- visible steps
- compact trace
- optional drafts
- DecisionCard metadata
- `runtime: react`

## Tool Loop

The runtime discovers Meta MCP tools from `tools/list` and registers them under the `meta_ads` namespace. Tool definitions are deferred and loaded with `tool_search`.

The model can use account, campaign, ad set, ad, creative, insights, audience, geo, image, and video tools. Local tools are:

```text
ask_user
load_skill
read_skill_reference
submit_result
save_memory
update_task
```

The context keeps five recent conversation rounds, a structured summary of older dialogue, active task Skills, current task progress, relevant Memory, and a compact selected-account view. The loop stops on a final answer, a focused question, or the configured step limit (default 16).

Only one turn can be active in a session. A client-provided idempotency key replays a completed response; a concurrent or mismatched request returns `409`. Session and task writes reject stale versions.

## Workspace Evidence

The workspace shows:

- account dashboard data when a read produced compact metrics
- agent tool steps under Trace
- action drafts under Actions
- evidence, recommendation, risk, and preflight for each draft
- an Approve draft action
- a Context tab showing budget usage, task progress, account cache freshness, and Memory in use

## Approval And Execution

`ads_create_campaign`, `ads_create_ad_set`, `ads_create_ad`, and `ads_create_creative` create non-live Meta Draft Mode objects directly. Activation, updates, deletes, and publication remain blocked. Other write-like tools stage local approval records.

The execute endpoint returns `410 execution_disabled_in_demo`. There is no Execute button in the UI.

## Quality

Tests cover:

- tool use and observation
- draft creation without a write tool
- ask-user stop behavior
- max-step stop behavior
- forbidden write-tool rejection
- dynamic MCP discovery and deferred tool schemas
- tool-search selection
- write-tool interception
- media result limits
- draft evidence and preflight
- frontend rendering and approval
- removal of the fixed pipeline
- five-round continuity and structured summary
- Memory scope and deletion
- task progress and tool ledger carry-forward
- account cache hits, TTL, and stale fallback

## Development Boundary

The functional outline is not implementation permission. Work must stay inside the active stage document.
