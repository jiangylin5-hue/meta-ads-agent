# Meta Data Workflow

## Status

- Document status: active Meta data reference
- Source of truth: [IMPLEMENTATION_SOURCE_OF_TRUTH.md](../00-governance/IMPLEMENTATION_SOURCE_OF_TRUTH.md)
- MCP reference: [MCP_WORKFLOW.md](MCP_WORKFLOW.md)

## Flow

```text
model loads a skill when useful
-> model uses tool_search
-> model calls a meta_ads read tool
-> MCP or local Meta provider returns data
-> adapter bounds and sanitizes the result
-> model uses the observation
```

## Common Read Paths

Account discovery:

```text
ads_get_ad_accounts
-> ads_get_ad_entities
-> ads_insights_performance_trend / ads_account_get_activity_logs
```

Performance diagnosis:

```text
ads_get_ad_entities
-> ads_insights_performance_trend
-> ads_insights_anomaly_signal / ads_insights_auction_ranking_benchmarks
-> optional ads_get_creatives
```

Audience research:

```text
ads_get_ad_account_custom_audiences
ads_catalog_get_dynamic_ads_health
ads_catalog_get_suggested_filter
ads_catalog_list_dpa_eligible_catalogs
```

## Result Budget

- General MCP result: 16,000 characters.
- Image/video result: 4,000 characters.
- Media bytes and data URLs are replaced with metadata.
- Lists are capped and marked when truncated.
- Requesting a narrower query is preferred over increasing the budget.

## Missing Data

An empty list remains empty. The model must report missing data rather than invent a metric or entity.

## Write Boundary

Read tools execute through MCP. The four allowed create tools execute through official Draft Mode and return non-live Draft objects. All other write-like tools are virtualized into local drafts or rejected; activation and publication are blocked.

## Verification

```powershell
$env:OPENAI_API_KEY=""
.venv\Scripts\python.exe -m pytest tests\test_account_gateway.py tests\test_agent_loop.py tests\test_performance_dashboard.py -q
```
