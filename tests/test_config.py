from backend import config


def test_remote_ads_mcp_token_prefers_mcp_tokens_before_meta_access_token(monkeypatch) -> None:
    monkeypatch.setenv("ADS_MCP_API_TOKEN", "ads-token")
    monkeypatch.setenv("PIPEBOARD_API_TOKEN", "pipeboard-token")
    monkeypatch.setenv("ADS_MCP_AUTH_TOKEN", "auth-token")
    monkeypatch.setenv("META_ACCESS_TOKEN", "meta-token")

    assert config.remote_ads_mcp_token() == "ads-token"


def test_remote_ads_mcp_token_does_not_fall_back_to_meta_access_token(monkeypatch) -> None:
    monkeypatch.delenv("ADS_MCP_API_TOKEN", raising=False)
    monkeypatch.delenv("PIPEBOARD_API_TOKEN", raising=False)
    monkeypatch.delenv("ADS_MCP_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("META_ACCESS_TOKEN", "meta-token")

    assert config.remote_ads_mcp_token() == ""


def test_remote_ads_mcp_token_skips_placeholder_mcp_tokens(monkeypatch) -> None:
    monkeypatch.setenv("ADS_MCP_API_TOKEN", "your-mcp-token")
    monkeypatch.setenv("PIPEBOARD_API_TOKEN", "your-token")
    monkeypatch.setenv("ADS_MCP_AUTH_TOKEN", "dummy-token")
    monkeypatch.setenv("META_ACCESS_TOKEN", "meta-token")

    assert config.remote_ads_mcp_token() == ""


def test_remote_ads_mcp_token_skips_non_ascii_placeholder_values(monkeypatch) -> None:
    monkeypatch.setenv("ADS_MCP_API_TOKEN", "你的MetaAccessToken")
    monkeypatch.setenv("PIPEBOARD_API_TOKEN", "")
    monkeypatch.setenv("ADS_MCP_AUTH_TOKEN", "")
    monkeypatch.setenv("META_ACCESS_TOKEN", "meta-token")

    assert config.remote_ads_mcp_token() == ""


def test_secret_fingerprint_does_not_expose_secret() -> None:
    fingerprint = config.secret_fingerprint("example-secret-1234")

    assert fingerprint["configured"] is True
    assert "prefix" not in fingerprint
    assert "suffix" not in fingerprint
    assert fingerprint["sha256_8"]
    assert "example-secret" not in str(fingerprint)
