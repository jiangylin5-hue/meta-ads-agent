from backend.integrations.meta_ads import MetaAdsProvider, _data_url_to_base64


def test_meta_ads_integration_live_publish_requires_explicit_flag(monkeypatch) -> None:
    monkeypatch.setenv("META_ACCESS_TOKEN", "token")
    monkeypatch.delenv("META_LIVE_WRITE_ENABLED", raising=False)
    provider = MetaAdsProvider()
    status = provider.status()

    assert status["live_publish_enabled"] is False
    assert "create_active_campaign" in status["allowed_operations"]

    monkeypatch.setenv("META_LIVE_WRITE_ENABLED", "true")
    assert MetaAdsProvider().status()["live_publish_enabled"] is True


def test_meta_ads_integration_accepts_image_data_url_base64() -> None:
    assert _data_url_to_base64("data:image/png;base64,SGVsbG8=") == "SGVsbG8="


def test_meta_ads_integration_normalizes_ad_account_id() -> None:
    provider = MetaAdsProvider()

    assert provider._normalize_ad_account_id("123") == "act_123"
    assert provider._normalize_ad_account_id("act_123") == "act_123"


def test_meta_integration_user_facing_messages_are_readable_chinese() -> None:
    provider = MetaAdsProvider()

    assert "\u672a\u914d\u7f6e META_ACCESS_TOKEN" in provider.limitation_message()


def test_meta_integration_list_ads_requests_creative_fields(monkeypatch) -> None:
    captured = {}
    provider = MetaAdsProvider(access_token="token")

    def fake_graph_get(path, params, include_token=True):
        captured["path"] = path
        captured["params"] = params
        return {"data": [{"id": "ad_1", "creative": {"id": "creative_1"}}]}

    monkeypatch.setattr(provider, "_graph_get", fake_graph_get)

    ads = provider.list_ads("act_1", limit=10)

    assert captured["path"] == "act_1/ads"
    assert "creative{id,name,title,body,thumbnail_url,image_url" in captured["params"]["fields"]
    assert captured["params"]["limit"] == "10"
    assert ads[0]["creative"]["id"] == "creative_1"


def test_meta_write_methods_respect_requested_paused_status(monkeypatch) -> None:
    captured = []
    provider = MetaAdsProvider(access_token="token")

    def fake_graph_post(path, data):
        captured.append((path, data))
        return {"id": f"id_{len(captured)}"}

    monkeypatch.setattr(provider, "_graph_post", fake_graph_post)

    provider.create_campaign("act_1", {"name": "Campaign", "objective": "OUTCOME_TRAFFIC", "status": "PAUSED"})
    provider.create_adset(
        "act_1",
        {
            "name": "Ad set",
            "campaign_id": "campaign_1",
            "status": "PAUSED",
            "targeting": {"geo_locations": {"countries": ["US"]}},
        },
    )
    provider.create_ad(
        "act_1",
        {"name": "Ad", "adset_id": "adset_1", "creative_id": "creative_1", "status": "PAUSED"},
    )

    assert [item[1]["status"] for item in captured] == ["PAUSED", "PAUSED", "PAUSED"]


def test_meta_campaign_create_declares_adset_budget_sharing_disabled(monkeypatch) -> None:
    captured = {}
    provider = MetaAdsProvider(access_token="token")

    def fake_graph_post(path, data):
        captured["data"] = data
        return {"id": "campaign_1"}

    monkeypatch.setattr(provider, "_graph_post", fake_graph_post)

    provider.create_campaign("act_1", {"name": "Campaign", "objective": "OUTCOME_TRAFFIC", "status": "PAUSED"})

    assert captured["data"]["is_adset_budget_sharing_enabled"] == "false"


def test_meta_adset_create_uses_lowest_cost_without_cap_by_default(monkeypatch) -> None:
    captured = {}
    provider = MetaAdsProvider(access_token="token")

    def fake_graph_post(path, data):
        captured["data"] = data
        return {"id": "adset_1"}

    monkeypatch.setattr(provider, "_graph_post", fake_graph_post)

    provider.create_adset(
        "act_1",
        {
            "name": "Ad set",
            "campaign_id": "campaign_1",
            "status": "PAUSED",
            "targeting": {"geo_locations": {"countries": ["US"]}},
        },
    )

    assert captured["data"]["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"
