from __future__ import annotations

from typing import Any


GA4_NAMESPACE = "google_analytics"
GA4_TOOL_NAMES = frozenset(
    {
        "ga4_list_properties",
        "ga4_get_property_details",
        "ga4_list_data_streams",
        "ga4_list_key_events",
        "ga4_list_google_ads_links",
        "ga4_get_metadata",
        "ga4_run_report",
        "ga4_run_realtime_report",
        "ga4_run_funnel_report",
    }
)

_PROPERTY = {
    "type": "string",
    "description": "Numeric GA4 property ID. Omit to use the configured default property.",
}
_DATE_START = {"type": "string", "description": "GA4 start date: YYYY-MM-DD, today, yesterday, or NdaysAgo."}
_DATE_END = {"type": "string", "description": "GA4 end date: YYYY-MM-DD, today, yesterday, or NdaysAgo."}
_DIMENSIONS = {"type": "array", "items": {"type": "string"}, "maxItems": 8}
_METRICS = {"type": "array", "items": {"type": "string"}, "maxItems": 12}


def ga4_tool_definitions() -> list[dict[str, Any]]:
    return [
        _tool(
            "ga4_list_properties",
            "List GA4 accounts and numeric properties visible to the configured read-only service account.",
            {"page_size": {"type": "integer", "minimum": 1, "maximum": 200, "default": 200}},
            [],
        ),
        _tool(
            "ga4_get_property_details",
            "Read GA4 property timezone, currency, service level, and property metadata.",
            {"property_id": _PROPERTY},
            [],
        ),
        _tool(
            "ga4_list_data_streams",
            "List GA4 web/app data streams. Use to verify whether tracking is configured before interpreting zero data.",
            {"property_id": _PROPERTY},
            [],
        ),
        _tool(
            "ga4_list_key_events",
            "List GA4 key events for a property. Use to verify which business actions are configured as conversions.",
            {"property_id": _PROPERTY},
            [],
        ),
        _tool(
            "ga4_list_google_ads_links",
            "List Google Ads links for a GA4 property. This only verifies the link; it does not read Google Ads performance.",
            {"property_id": _PROPERTY},
            [],
        ),
        _tool(
            "ga4_get_metadata",
            "Read the GA4 Data API dimension and metric catalog. Use before querying unfamiliar custom fields.",
            {"property_id": _PROPERTY},
            [],
        ),
        _tool(
            "ga4_run_report",
            "Run a read-only GA4 report for sessions, users, events, key events, revenue, landing pages, source/medium, campaign, device, or geography. Use matching date windows for comparisons.",
            _report_properties(),
            ["start_date", "end_date", "metrics"],
        ),
        _tool(
            "ga4_run_realtime_report",
            "Run a read-only GA4 realtime report to verify that tracking is currently receiving events.",
            {
                "property_id": _PROPERTY,
                "dimensions": _DIMENSIONS,
                "metrics": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                "dimension_filter": {"type": "object"},
                "metric_filter": {"type": "object"},
                "order_bys": {"type": "array", "items": {"type": "object"}, "maxItems": 10},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 100},
                "return_property_quota": {"type": "boolean", "default": True},
            },
            ["metrics"],
        ),
        _tool(
            "ga4_run_funnel_report",
            "Run a read-only GA4 funnel report using explicit funnel steps and a matching date window.",
            {
                "property_id": _PROPERTY,
                "start_date": _DATE_START,
                "end_date": _DATE_END,
                "comparison_start_date": {"type": "string"},
                "comparison_end_date": {"type": "string"},
                "funnel": {"type": "object", "description": "GA4 funnel definition with a non-empty steps array."},
                "funnel_breakdown": {"type": "object"},
                "funnel_next_action": {"type": "object"},
                "return_property_quota": {"type": "boolean", "default": True},
            },
            ["start_date", "end_date", "funnel"],
        ),
    ]


def is_ga4_tool(name: str) -> bool:
    return str(name or "") in GA4_TOOL_NAMES


def _report_properties() -> dict[str, Any]:
    return {
        "property_id": _PROPERTY,
        "start_date": _DATE_START,
        "end_date": _DATE_END,
        "comparison_start_date": {"type": "string", "description": "Optional comparison-window start date with the same length and timezone."},
        "comparison_end_date": {"type": "string", "description": "Optional comparison-window end date with the same length and timezone."},
        "dimensions": _DIMENSIONS,
        "metrics": _METRICS,
        "dimension_filter": {"type": "object"},
        "metric_filter": {"type": "object"},
        "order_bys": {"type": "array", "items": {"type": "object"}, "maxItems": 10},
        "limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 100},
        "offset": {"type": "integer", "minimum": 0, "maximum": 1000000, "default": 0},
        "keep_empty_rows": {"type": "boolean"},
        "metric_aggregations": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "return_property_quota": {"type": "boolean", "default": True},
    }


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
    }


__all__ = ["GA4_NAMESPACE", "GA4_TOOL_NAMES", "ga4_tool_definitions", "is_ga4_tool"]
