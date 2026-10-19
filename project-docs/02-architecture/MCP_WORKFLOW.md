# MCP Workflow

## Status

- Document status: active Meta MCP reference
- Source of truth: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](../00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md)
- Active stage: [STAGE_09_CONTEXT_AND_AGENT_MEMORY.md](../03-stages/STAGE_09_CONTEXT_AND_AGENT_MEMORY.md)

## Goal

The app discovers the Meta MCP tool catalog and exposes it to the model without loading every schema on every step.

```text
tools/list
-> registered tool defs
-> meta_ads namespace
-> defer_loading=true
-> OpenAI tool_search or DeepSeek portable Skill-scoped tools
-> read tools call MCP
-> four create tools use Draft Mode; other write-like tools stay local
```

## Configuration

```env
ADS_MCP_ENDPOINT_URL=https://mcp.facebook.com/ads
ACCOUNT_GATEWAY_PREFERENCE=mcp
ADS_MCP_API_TOKEN=
META_ACCESS_TOKEN=
```

The official endpoint uses OAuth or a user/system-user access token. The project currently sends the configured Meta token as `Authorization: Bearer <token>` and initializes an MCP session before `tools/list` and `tools/call`.

## Credential Policy

- Use one Meta System User access token with `expires_at=never` (non-expiring; 永不过期).
- Store the token only in `.env` as both `META_ACCESS_TOKEN` and `ADS_MCP_API_TOKEN`.
- Required scopes are `ads_read`, `ads_management`, and `ads_mcp_management`; use `business_management` when business reads are needed.
- Never write the token value into documentation, source files, prompts, model context, Memory, cache, trace, logs, or Git.
- Validate the credential with `scripts/doctor.py` and `scripts/verify_meta_access_token.py`.
- Token Debugger must report a valid token for App `<META_APP_ID>` and `expires_at=never`.
- Rotation: generate a new token in Meta Business Settings, update both environment variables, restart the backend, and rerun both checks.

## Catalog

The official server currently returns 98 tools, including:

```text
ads_get_ad_accounts
ads_get_ad_entities
ads_insights_performance_trend
ads_insights_anomaly_signal
ads_insights_auction_ranking_benchmarks
ads_get_opportunity_score
ads_account_get_activity_logs
ads_get_datasets
ads_get_dataset_quality
ads_get_creatives
ads_experiment_list_tests
ads_library_search
```

MCP names are preserved in the `meta_ads` namespace.

## Safety

- All schemas remove model-supplied `access_token`.
- The runtime injects the configured token.
- `ads_create_campaign`, `ads_create_ad_set`, `ads_create_ad`, and `ads_create_creative` call MCP in Draft Mode and return non-live Draft objects.
- All other write-like tools remain local or forbidden; `ads_activate_entity`, updates, deletes, and publication never reach MCP.
- Every direct Draft creation writes an execution log.
- `ads_get_ad_images`, `ads_get_ad_videos`, and screenshot tools omit raw media data.
- General results are limited to 16,000 characters; media results to 4,000 characters.

## Diagnostics

```powershell
.venv\Scripts\python.exe scripts\doctor.py
Invoke-RestMethod http://127.0.0.1:8010/api/accounts/mcp/diagnostics
```

The diagnostics endpoint reports:

- endpoint and token configured
- reachable and ready
- tool count and names
- missing required or optional tools
- connection error

## Verification

```powershell
$env:OPENAI_API_KEY=""
.venv\Scripts\python.exe -m pytest tests\test_account_gateway.py tests\test_agent_loop.py -q
.venv\Scripts\python.exe scripts\verify_mcp_tool_agent.py --spend-credits
```
