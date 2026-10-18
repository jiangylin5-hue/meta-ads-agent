from backend.services.performance_dashboard import build_performance_dashboard


CAMPAIGNS = [
    {"id": "cmp_1", "name": "Alpha", "status": "ACTIVE", "effective_status": "ACTIVE"},
    {"id": "cmp_2", "name": "Beta", "status": "ACTIVE", "effective_status": "ACTIVE"},
]
INSIGHTS = [
    {"campaign_id": "cmp_1", "campaign_name": "Alpha", "spend": "10", "impressions": "1000", "clicks": "10"},
    {"campaign_id": "cmp_2", "campaign_name": "Beta", "spend": "20", "impressions": "2000", "clicks": "20"},
]


def test_missing_campaign_hint_returns_empty_not_all_campaigns() -> None:
    dashboard = build_performance_dashboard(
        account={"id": "act_1"},
        campaigns=CAMPAIGNS,
        insights=INSIGHTS,
        date_preset="last_30d",
        level="campaign",
        campaign_hint="does-not-exist",
    )

    assert dashboard["summary"]["entity_count"] == 0
    assert dashboard["entity_cards"] == []
    assert any("No campaign matched" in item for item in dashboard["data_quality"])


def test_matching_campaign_hint_keeps_only_matching_rows() -> None:
    dashboard = build_performance_dashboard(
        account={"id": "act_1"},
        campaigns=CAMPAIGNS,
        insights=INSIGHTS,
        date_preset="last_30d",
        level="campaign",
        campaign_hint="Alpha",
    )

    assert dashboard["summary"]["entity_count"] == 1
    assert dashboard["entity_cards"][0]["entity_id"] == "cmp_1"