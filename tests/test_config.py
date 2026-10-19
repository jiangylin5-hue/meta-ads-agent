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


def test_ga4_enabled_requires_existing_credentials_file(tmp_path, monkeypatch) -> None:
    credentials = tmp_path / "service-account.json"
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(credentials))
    monkeypatch.setenv("GOOGLE_PROJECT_ID", "test-project")
    monkeypatch.setenv("GA4_PROPERTY_ID", "123456789")

    assert config.ga4_enabled() is False
    credentials.write_text("{}", encoding="utf-8")
    assert config.ga4_enabled() is True
    assert config.ga4_project_id() == "test-project"
    assert config.ga4_default_property_id() == "123456789"
