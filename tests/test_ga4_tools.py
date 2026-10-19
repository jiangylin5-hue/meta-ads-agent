import json
from typing import Any

import pytest

from backend.agent.runtime import AgentRuntime
from backend.agent.tools import MetaToolRegistry
from backend.services.ga4_gateway import Ga4Gateway, Ga4GatewayError


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"method": method, "url": url, **kwargs})
        if not self.responses:
            raise AssertionError("FakeSession has no response left")
        return self.responses.pop(0)


class FakeGa4Gateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], float | None]] = []

    def execute_tool(self, name: str, arguments: dict[str, Any], *, timeout_seconds: float | None = None) -> dict[str, Any]:
        self.calls.append((name, dict(arguments), timeout_seconds))
        return {
            "tool": name,
            "source": "google_analytics",
            "read_only": True,
            "property_id": arguments.get("property_id") or "123456789",
            "row_count": 0,
            "no_data": True,
            "missing_data": ["GA4 returned zero report rows."],
        }


class FakeMCP:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "ads_get_ad_accounts",
                "description": "List accounts",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            }
        ]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.calls.append((name, dict(arguments or {})))
        return {"data": []}


class FakeLLM:
    supports_tool_search = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]] = []

    def complete(self, instructions: str, input_items: list[dict[str, Any]], tools: list[dict[str, Any]], **_kwargs: Any) -> dict[str, Any]:
        self.calls.append((instructions, input_items, tools))
        if len(self.calls) == 1:
            arguments = {
                "start_date": "30daysAgo",
                "end_date": "yesterday",
                "dimensions": ["sessionSource", "landingPage"],
                "metrics": ["sessions", "keyEvents"],
                "limit": 10,
            }
            return {
                "content": "",
                "output_items": [
                    {
                        "type": "function_call",
                        "call_id": "ga4_call_1",
                        "name": "ga4_run_report",
                        "namespace": "google_analytics",
                        "arguments": json.dumps(arguments),
                    }
                ],
                "tool_calls": [
                    {
                        "id": "ga4_call_1",
                        "name": "ga4_run_report",
                        "namespace": "google_analytics",
                        "arguments": json.dumps(arguments),
                    }
                ],
            }
        return {"content": "GA4 is connected but the property has no data yet.", "output_items": [], "tool_calls": []}


def _gateway(session: FakeSession) -> Ga4Gateway:
    return Ga4Gateway(
        access_token="test-read-token",
        default_property_id="123456789",
        session=session,
        timeout_seconds=15,
    )


def test_ga4_gateway_lists_properties_and_does_not_expose_token() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "accountSummaries": [
                        {
                            "account": "accounts/987654321",
                            "displayName": "Test account",
                            "propertySummaries": [
                                {
                                    "property": "properties/123456789",
                                    "displayName": "ads mcp",
                                    "propertyType": "PROPERTY_TYPE_ORDINARY",
                                }
                            ],
                        }
                    ]
                }
            )
        ]
    )
    result = _gateway(session).list_properties()

    assert result["property_count"] == 1
    assert result["properties"][0]["property_id"] == "123456789"
    assert result["properties"][0]["parent_account_id"] == "987654321"
    assert "test-read-token" not in json.dumps(result)
    assert session.requests[0]["url"].endswith("/accountSummaries")


def test_ga4_gateway_runs_bounded_report_and_preserves_metadata() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "dimensionHeaders": [{"name": "sessionSource"}],
                    "metricHeaders": [{"name": "sessions"}],
                    "rows": [{"dimensionValues": [{"value": "meta"}], "metricValues": [{"value": "12"}]}],
                    "rowCount": 1,
                    "metadata": {"timeZone": "Asia/Shanghai", "currencyCode": "CNY"},
                    "propertyQuota": {"tokensPerDay": {"remaining": 199999}},
                }
            )
        ]
    )
    result = _gateway(session).run_report(
        {
            "start_date": "30daysAgo",
            "end_date": "yesterday",
            "dimensions": ["sessionSource"],
            "metrics": ["sessions"],
            "limit": 20,
        }
    )

    assert result["row_count"] == 1
    assert result["time_zone"] == "Asia/Shanghai"
    assert result["currency_code"] == "CNY"
    body = session.requests[0]["json"]
    assert body["dateRanges"] == [{"startDate": "30daysAgo", "endDate": "yesterday", "name": "current"}]
    assert body["dimensions"] == [{"name": "sessionSource"}]
    assert body["metrics"] == [{"name": "sessions"}]
    assert body["limit"] == 20
    assert body["returnPropertyQuota"] is True


def test_ga4_gateway_marks_empty_report_as_no_data() -> None:
    session = FakeSession([FakeResponse({"metadata": {"timeZone": "Asia/Shanghai", "currencyCode": "CNY"}})])
    result = _gateway(session).run_report(
        {"start_date": "30daysAgo", "end_date": "yesterday", "metrics": ["sessions"]}
    )

    assert result["row_count"] == 0
    assert result["no_data"] is True
    assert result["missing_data"] == ["GA4 returned zero report rows for the requested property and date window."]


def test_ga4_gateway_rejects_measurement_id_as_property() -> None:
    gateway = _gateway(FakeSession([]))
    with pytest.raises(Ga4GatewayError) as exc:
        gateway.run_report({"property_id": "G-ABC123", "start_date": "30daysAgo", "end_date": "yesterday", "metrics": ["sessions"]})
    assert exc.value.code == "ga4_invalid_property"


def test_ga4_gateway_surfaces_permission_error_without_credentials() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {"error": {"code": 403, "message": "User does not have sufficient permissions for this property."}},
                status_code=403,
            )
        ]
    )
    with pytest.raises(Ga4GatewayError) as exc:
        _gateway(session).get_property_details()
    assert exc.value.code == "ga4_permission_denied"
    assert "test-read-token" not in str(exc.value)


def test_registry_exposes_ga4_globally_without_skill_load() -> None:
    ga4 = FakeGa4Gateway()
    mcp = FakeMCP()
    registry = MetaToolRegistry(mcp_client=mcp, tool_definitions=mcp.list_tools(), ga4_gateway=ga4)

    schemas = registry.schemas()
    ga4_namespace = next(item for item in schemas if item.get("type") == "namespace" and item.get("name") == "google_analytics")
    names = {item["name"] for item in ga4_namespace["tools"]}
    assert {"ga4_run_report", "ga4_list_properties", "ga4_get_metadata"}.issubset(names)
    assert {item["name"] for item in registry.portable_schemas(set())} >= {"ga4_run_report"}
    assert registry.is_core_tool("ga4_run_report") is True

    result = registry.execute(
        "ga4_run_report",
        {"start_date": "30daysAgo", "end_date": "yesterday", "metrics": ["sessions"]},
    )
    assert result["tool"] == "ga4_run_report"
    assert result["result"]["no_data"] is True
    assert mcp.calls == []
    assert ga4.calls[0][0] == "ga4_run_report"
    assert "credentials" not in json.dumps(ga4_namespace).lower()


def test_runtime_calls_ga4_without_loading_a_skill() -> None:
    ga4 = FakeGa4Gateway()
    mcp = FakeMCP()
    registry = MetaToolRegistry(mcp_client=mcp, tool_definitions=mcp.list_tools(), ga4_gateway=ga4)
    llm = FakeLLM()

    result = AgentRuntime(llm=llm, tools=registry, max_steps=3).run_turn("Check GA4 traffic for the last 30 days.")

    assert result["stopped_reason"] == "final"
    assert result["skills_loaded"] == []
    assert result["tool_calls"] == ["google_analytics.ga4_run_report"]
    assert result["intent_type"] == "read_data"
    assert result["drafts"] == []
    assert result["direct_drafts"] == []
    assert ga4.calls[0][0] == "ga4_run_report"
    assert mcp.calls == []
    assert "Do not call `load_skill` for GA4" in llm.calls[0][0]
