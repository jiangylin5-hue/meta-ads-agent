# Stage 10 GA4 Measurement Tools

## Status

- Stage status: active
- Document status: active stage file
- Source of truth: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](../00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md)
- Previous stage: [STAGE_09_CONTEXT_AND_AGENT_MEMORY.md](STAGE_09_CONTEXT_AND_AGENT_MEMORY.md)
- Opened: 2026-10-19 by explicit user instruction

## Goal

Give the agent a global, read-only GA4 measurement toolkit so it can connect Meta advertising outcomes with website sessions, landing pages, acquisition sources, conversion events, and cross-source discrepancies.

GA4 is a model tool, not a project Skill. The model may call GA4 tools in any turn without loading a GA4 Skill. Meta tools remain Skill-scoped.

## Why This Stage Exists

The existing Skills can diagnose Meta delivery, account state, creative approval, and Meta attribution, but they cannot inspect website behavior. That leaves landing-page quality, GA4 key events, source/medium contribution, and Meta-versus-GA4 discrepancies outside the evidence chain.

The official GA4 MCP exists but is an experimental local stdio service. The current runtime has an HTTP MCP client and does not support stdio MCP. This stage exposes GA4 directly through a read-only gateway and registers it through the existing model tool-calling path.

## Scope

- Add service-account authentication using Application Default Credentials JSON.
- Add a read-only GA4 gateway backed by official Google Analytics Admin and Data APIs.
- Register GA4 tools globally for every agent turn.
- Keep GA4 tools out of the Skill catalog and out of Skill allowlists.
- Allow GA4 evidence to supplement any active Skill result.
- Add bounded result handling, caching, property validation, and trace redaction.
- Add prompt guidance for deciding when website analytics evidence is relevant.
- Keep current Meta Draft and execution boundaries unchanged.

Initial tools:

```text
ga4_list_properties
ga4_get_property_details
ga4_list_data_streams
ga4_list_key_events
ga4_list_google_ads_links
ga4_get_metadata
ga4_run_report
ga4_run_realtime_report
ga4_run_funnel_report
```

## Non-Goals

- No GA4 Skill folder.
- No GA4 property, data stream, key-event, or attribution-setting writes.
- No Measurement Protocol event writes.
- No GTM installation or landing-page modification.
- No Google Ads, TikTok, LinkedIn, or other advertising-channel integration.
- No replacement of Meta attribution with GA4 as a supposed ground truth.
- No claim that zero GA4 rows mean zero business outcomes when tracking is absent or incomplete.

## Tool Contract

- GA4 tools are read-only and globally available after configuration.
- Credentials never enter model context, tool arguments, Memory, cache, or trace.
- The numeric GA4 Property ID is required; `G-` measurement IDs are not accepted for reporting.
- `ga4_list_properties` and metadata calls are allowed without a selected property when needed for discovery.
- Report tools require an actual date window and at least one metric.
- Every report result must preserve the returned timezone, currency, row count, and property quota when available.
- Meta-attributed conversions, GA4-observed conversions, and CRM/backend outcomes must remain separate evidence classes and must not be summed blindly.
- GA4 calls must remain bounded by the turn deadline and a per-call timeout.

## Tasks

| Task | Status | Scope |
| --- | --- | --- |
| S10-T1 | complete | Stage contract, governance, runtime boundary, and task plan |
| S10-T2 | complete | GA4 configuration and service-account gateway |
| S10-T3 | complete | Global model tool schemas, execution routing, caching, and redaction |
| S10-T4 | complete | Prompt guidance and evidence separation |
| S10-T5 | complete | Focused tests and real read-only property verification |
| S10-T6 | complete | Documentation, quality evidence, and final verification |

## Acceptance Criteria

- GA4 tools appear to the model without calling `load_skill`.
- GA4 tools remain callable when a Meta Skill is active and when no Skill is active.
- Skill tool-scope checks reject unknown tools while allowing configured GA4 tools globally.
- The tool schemas do not expose credentials, file paths, access tokens, or private keys.
- The gateway accepts only validated numeric property IDs.
- A successful report returns tool provenance, actual date range, timezone, currency, row count, and quota when available.
- A valid property with no data returns a successful empty result with explicit no-data metadata.
- An unauthorized property returns a clear permission error without leaking credentials.
- GA4 reads never create a Meta Draft and never satisfy Meta Draft current-state evidence by themselves.
- Existing Meta tool behavior and safety boundaries remain unchanged.
- Documentation checks and the full backend suite pass.
- A real read-only call against Property `<ga4_property_id>` completes.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest tests\test_ga4_tools.py tests\test_agent_loop.py tests\test_docs_quality.py -q
.venv\Scripts\python.exe -m pytest tests -q
npm.cmd run lint --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run test:smoke --prefix frontend
```

## Current Progress

- 2026-10-19: Opened Stage 10 after explicit user instruction to add GA4 as global tool calling rather than a Skill. Service-account access to GA4 Property `<ga4_property_id>` is already verified; the property currently has no data stream or report rows.

- 2026-10-19: Added `backend/services/ga4_gateway.py` with service-account authentication, bounded timeouts, token refresh, Admin/Data API reads, property validation, and explicit empty-data metadata.
- 2026-10-19: Added global `ga4_*` tools through `backend/agent/ga4_tools.py`; GA4 tools require no `load_skill`, are exposed in both deferred and portable provider modes, and are cached separately from Meta reads.
- 2026-10-19: Added prompt guidance and evidence separation for Meta-reported, GA4-observed, and CRM outcomes.
- 2026-10-19: Added focused gateway, schema, global-scope, and runtime tests. Full backend suite: `205 passed, 1 skipped`.
- 2026-10-19: Real DeepSeek E2E completed in 4 steps and 25.6 seconds with no Skill loaded, five GA4 tool calls, `7,039` input / `616` output tokens, zero Drafts, and a final answer. Property `<ga4_property_id>` is connected but has no data stream, key events, or history yet.
