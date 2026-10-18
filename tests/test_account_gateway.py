from backend.services.account_gateway import (
    AutoAccountGateway,
    MetaAccountGateway,
    RemoteMcpGateway,
    _parse_rpc_response,
    gateway_for,
)


class FakeMetaProvider:
    def status(self):
        return {
            "configured": True,
            "oauth_configured": True,
            "allowed_operations": ["read_adaccounts", "read_campaigns", "read_insights"],
        }

    def list_ad_accounts(self, limit=100):
        return [{"id": "act_1", "name": "Test"}]

    def list_campaigns(self, ad_account_id=None, limit=50):
        return [{"id": "camp_1", "name": "Campaign 1"}]

    def list_ads(self, ad_account_id=None, limit=100):
        return [{"id": "ad_1", "name": "Ad 1"}]

    def get_insights(self, ad_account_id=None, date_preset="last_7d", level="campaign", limit=50, time_increment=""):
        return [{"campaign_id": "camp_1", "spend": "10"}]

    def access_token_for_requests(self):
        return "session-token"


class FakeMcpClient:
    def __init__(self):
        self.calls = []

    def call_tool(self, name, arguments=None):
        self.calls.append({"name": name, "arguments": arguments or {}})
        if name == "get_ad_accounts":
            return {"data": [{"id": "act_1", "name": "MCP Account"}]}
        if name == "get_account_info":
            return {"id": arguments["account_id"], "name": "MCP Account"}
        if name == "get_campaigns":
            return {"data": [{"id": "camp_1", "name": "MCP Campaign"}]}
        if name == "get_insights":
            return {"data": [{"campaign_id": "camp_1", "spend": "42"}]}
        raise AssertionError(f"Unexpected tool: {name}")


class FailingMcpClient:
    def call_tool(self, name, arguments=None):
        raise RuntimeError("MCP offline")


def test_meta_account_gateway_wraps_provider_snapshot() -> None:
    gateway = MetaAccountGateway(FakeMetaProvider())

    assert gateway.connection_status()["read_enabled"] is True
    assert gateway.list_accounts() == [{"id": "act_1", "name": "Test"}]
    assert gateway.account_snapshot("act_1") == {
        "platform": "meta",
        "provider": "local_meta_marketing_api",
        "account_id": "act_1",
        "date_preset": "last_7d",
        "campaigns": [{"id": "camp_1", "name": "Campaign 1"}],
        "insights": [{"campaign_id": "camp_1", "spend": "10"}],
    }
    assert gateway.list_campaigns("act_1") == [{"id": "camp_1", "name": "Campaign 1"}]
    assert gateway.get_insights("act_1") == [{"campaign_id": "camp_1", "spend": "10"}]


def test_remote_mcp_gateway_maps_core_meta_tools(monkeypatch) -> None:
    monkeypatch.setenv("ADS_MCP_ENDPOINT_URL", "http://127.0.0.1:8768/mcp")

    client = FakeMcpClient()
    gateway = RemoteMcpGateway(client=client, access_token="session-token")
    status = gateway.connection_status()
    snapshot = gateway.account_snapshot("1")

    assert status["provider"] == "meta_ads_mcp"
    assert status["configured"] is True
    assert status["token_configured"] is True
    assert status["write_enabled"] is False
    assert gateway.list_accounts() == [{"id": "act_1", "name": "MCP Account"}]
    assert snapshot["provider"] == "meta_ads_mcp"
    assert snapshot["account"] == {"id": "act_1", "name": "MCP Account"}
    assert snapshot["campaigns"] == [{"id": "camp_1", "name": "MCP Campaign"}]
    assert snapshot["insights"] == [{"campaign_id": "camp_1", "spend": "42"}]
    assert gateway.list_campaigns("1") == [{"id": "camp_1", "name": "MCP Campaign"}]
    assert gateway.get_insights("1") == [{"campaign_id": "camp_1", "spend": "42"}]
    assert client.calls[0]["arguments"]["access_token"] == "session-token"


def test_remote_mcp_gateway_diagnostics_reports_required_tools(monkeypatch) -> None:
    class ToolListClient(FakeMcpClient):
        def list_tools(self):
            return [
                {"name": "get_ad_accounts"},
                {"name": "get_account_info"},
                {"name": "get_campaigns"},
                {"name": "get_insights"},
            ]

    monkeypatch.setenv("ADS_MCP_ENDPOINT_URL", "http://127.0.0.1:8768/mcp")
    diagnostics = RemoteMcpGateway(client=ToolListClient()).diagnostics()

    assert diagnostics["reachable"] is True
    assert diagnostics["ready"] is True
    assert diagnostics["missing_required_tools"] == []


def test_mcp_rpc_response_parser_accepts_streamable_http_sse() -> None:
    response = _parse_rpc_response(
        'event: message\n'
        'data: {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"get_ad_accounts"}]}}\n\n'
    )

    assert response["result"]["tools"] == [{"name": "get_ad_accounts"}]


def test_mcp_rpc_response_parser_uses_last_valid_sse_event() -> None:
    response = _parse_rpc_response(
        'event: keepalive\n'
        'data: not-json\n\n'
        'event: message\n'
        'data: {"jsonrpc":"2.0","id":2,"result":{"ok":true}}\n\n'
    )

    assert response["result"] == {"ok": True}


def test_remote_mcp_gateway_diagnostics_reports_missing_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("ADS_MCP_ENDPOINT_URL", raising=False)

    diagnostics = RemoteMcpGateway().diagnostics()

    assert diagnostics["reachable"] is False
    assert diagnostics["ready"] is False
    assert "get_ad_accounts" in diagnostics["missing_required_tools"]


def test_gateway_for_uses_mcp_by_default(monkeypatch) -> None:
    monkeypatch.setenv("ADS_MCP_ENDPOINT_URL", "http://127.0.0.1:8768/mcp")

    gateway = gateway_for("meta", FakeMetaProvider())

    assert gateway.connection_status()["provider"] == "auto:mcp"


def test_gateway_for_falls_back_to_oauth_local_when_mcp_endpoint_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("ADS_MCP_ENDPOINT_URL", raising=False)

    gateway = gateway_for("meta", FakeMetaProvider())

    assert gateway.connection_status()["provider"] == "local_meta_marketing_api"


def test_auto_gateway_falls_back_to_local_when_mcp_is_offline(monkeypatch) -> None:
    monkeypatch.setenv("ADS_MCP_ENDPOINT_URL", "http://127.0.0.1:9999/mcp")
    local = MetaAccountGateway(FakeMetaProvider())
    mcp = RemoteMcpGateway(client=FailingMcpClient())
    gateway = AutoAccountGateway(local, mcp)

    assert gateway.list_accounts() == [{"id": "act_1", "name": "Test"}]
    assert gateway.list_campaigns("act_1") == [{"id": "camp_1", "name": "Campaign 1"}]
    assert gateway.list_ads("act_1") == [{"id": "ad_1", "name": "Ad 1"}]
    assert gateway.get_insights("act_1") == [{"campaign_id": "camp_1", "spend": "10"}]


def test_gateway_for_rejects_unknown_platform() -> None:
    try:
        gateway_for("unknown", FakeMetaProvider())
    except RuntimeError as exc:
        assert "Unsupported account data platform" in str(exc)
    else:
        raise AssertionError("Expected unsupported platform to raise RuntimeError.")

def test_mcp_image_content_is_reduced_to_metadata() -> None:
    from backend.services.account_gateway import MetaMcpClient

    class ImageClient(MetaMcpClient):
        def _rpc(self, method, params):
            return {
                "result": {
                    "content": [
                        {"type": "image", "mimeType": "image/jpeg", "data": "A" * 200000},
                    ]
                }
            }

    result = ImageClient("http://example.test/mcp").call_tool("get_ad_image", {"ad_id": "ad_1"})
    media = result["media"][0]

    assert media["data_omitted"] is True
    assert media["data_chars"] == 200000
    assert media["bytes_estimate"] == 150000
    assert media["source"]["ad_id"] == "ad_1"
    assert "data" not in media

def test_official_mcp_client_initializes_session_before_tools_list() -> None:
    from backend.services.account_gateway import MetaMcpClient

    class RecordingClient(MetaMcpClient):
        def __init__(self):
            super().__init__("https://mcp.facebook.com/ads", token="test-token")
            self.requests = []

        def _send_request(self, method, params, notification=False):
            self.requests.append((method, notification))
            if method == "initialize":
                self._session_id = "session-test"
                return {"result": {"protocolVersion": "2025-11-25"}}
            if method == "notifications/initialized":
                return {}
            return {"result": {"tools": [{"name": "ads_get_ad_accounts"}]}}

    client = RecordingClient()
    tools = client.list_tools()

    assert [item[0] for item in client.requests] == ["initialize", "notifications/initialized", "tools/list"]
    assert client._session_id == "session-test"
    assert client._protocol_version == "2025-11-25"
    assert client.injects_access_token_argument is False
    assert tools[0]["name"] == "ads_get_ad_accounts"
