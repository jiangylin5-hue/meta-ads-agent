import pytest

from scripts import doctor


class ReadyGateway:
    def diagnostics(self):
        return {
            "provider": "remote_mcp",
            "reachable": True,
            "ready": True,
            "tool_count": 4,
            "missing_required_tools": [],
        }


class BrokenGateway:
    def diagnostics(self):
        return {
            "provider": "remote_mcp",
            "reachable": False,
            "ready": False,
            "tool_count": 1,
            "missing_required_tools": ["get_insights"],
            "error": "connection failed",
        }


def test_doctor_passes_when_mcp_is_ready(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "account_gateway_preference", lambda: "mcp")
    monkeypatch.setattr(doctor, "remote_ads_mcp_endpoint", lambda: "http://127.0.0.1:9000/mcp")
    monkeypatch.setattr(doctor, "remote_ads_mcp_token", lambda: "token")
    monkeypatch.setattr(doctor, "openai_api_key", lambda: "sk-test")
    monkeypatch.setattr(doctor, "openai_model", lambda: "test-model")
    monkeypatch.setattr(doctor, "RemoteMcpGateway", ReadyGateway)

    doctor.main()

    output = capsys.readouterr().out
    assert "Doctor passed" in output
    assert "[PASS] mcp.ready: True" in output


def test_doctor_fails_when_required_mcp_settings_are_missing(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "account_gateway_preference", lambda: "mcp")
    monkeypatch.setattr(doctor, "remote_ads_mcp_endpoint", lambda: "")
    monkeypatch.setattr(doctor, "remote_ads_mcp_token", lambda: "")
    monkeypatch.setattr(doctor, "openai_api_key", lambda: "")
    monkeypatch.setattr(doctor, "openai_model", lambda: "gpt-4.1-mini")
    monkeypatch.setattr(doctor, "RemoteMcpGateway", BrokenGateway)

    with pytest.raises(SystemExit) as exc_info:
        doctor.main()

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "ADS_MCP_ENDPOINT_URL is not configured" in output
    assert "MCP is missing required tools: get_insights" in output
    assert "connection failed" in output
