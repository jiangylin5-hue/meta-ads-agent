# Project Charter

## Status

- Document status: active product charter
- Current implementation source: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](../00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md)

## Product Goal

Overseas Ads Agent is a small Meta ads copilot demo. A user selects one readable ad account, asks a media-buyer question, and watches a bounded ReAct loop choose tools, inspect compact evidence, and return a short answer, a non-live Meta Draft, or a local approval-gated action record.

The goal is to demonstrate a clear agent architecture:

```text
model chooses tool
-> code executes allowed tool
-> compact observation returns to model
-> repeat or answer
```

## Target User

- A developer who wants to inspect a small agent design
- A media buyer who wants a practical account-reading demo
- A small team that wants to review the read -> judgement -> draft -> approval path

## MVP Scope

- one Next.js page
- Meta account selection
- chat through one agent endpoint
- compact tool trace
- five-round context continuity, structured summary, task progress, and typed Memory
- account and insight reads through the Meta gateway with TTL caches
- evidence-backed action drafts
- draft approval
- a real OpenAI tool-call smoke script

## Out Of Scope

- SaaS navigation, billing, organizations, roles, or multi-tenant workspaces
- non-Meta channels
- batch ad creation or publishing
- live account execution
- automatic spend changes
- a separate intent router or graph framework
- vector semantic memory in this stage
- performance analysis redesign
- database and Redis redesign in this stage

## Success Criteria

- The backend exposes one chat entry point: `POST /api/agent/turn`.
- The model can call at least one read tool and use the observation in a final answer.
- A draft response includes evidence, recommendation, risk, target, and preflight.
- The frontend renders the trace and draft card.
- Draft approval is available and execution remains disabled.
- Context, Memory, task progress, and cache behavior have focused tests.
- The real OpenAI smoke can demonstrate a tool call without a live Meta write.

## Main Risks

- model judgement can be wrong
- missing data can be mistaken for evidence
- draft preflight is shallow
- Postgres and Redis remain heavier than the demo needs
- live execution is not implemented and must not be implied
