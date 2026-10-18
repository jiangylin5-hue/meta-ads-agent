import json
import argparse
from pathlib import Path
import shutil

import pytest

from scripts import verify_meta_access_token as verifier


TEST_TMP = Path(".test-tmp-verify-meta-access-token")


class FakeProvider:
    def get_me(self):
        return {"id": "user_1", "name": "User One"}

    def list_permissions(self):
        return [
            {"permission": "ads_read", "status": "granted"},
            {"permission": "business_management", "status": "granted"},
        ]

    def list_businesses(self, limit=50):
        return [{"id": "biz_1", "name": "Business One"}]

    def list_ad_accounts(self, limit=50):
        return [
            {
                "id": "act_123",
                "name": "Account 123",
                "account_status": 1,
                "currency": "USD",
                "timezone_name": "America/Los_Angeles",
            }
        ]


class EmptyProvider(FakeProvider):
    def list_ad_accounts(self, limit=50):
        return []


def test_verify_meta_access_token_rejects_missing_or_placeholder_key(monkeypatch) -> None:
    monkeypatch.setattr(verifier, "meta_access_token", lambda: "your-meta-access-token")

    with pytest.raises(SystemExit) as exc_info:
        verifier.verify_meta_access_token()

    assert "missing or still a placeholder" in str(exc_info.value)


def test_verify_meta_access_token_reports_accounts(monkeypatch) -> None:
    monkeypatch.setattr(verifier, "meta_access_token", lambda: "meta-token")
    monkeypatch.setattr(verifier, "MetaAdsProvider", FakeProvider)

    report = verifier.verify_meta_access_token(account_id="123", account_limit=10)

    assert report["status"] == "passed"
    assert report["provider"] == "meta_graph_api"
    assert report["account_count"] == 1
    assert report["account_id_requested"] == "act_123"
    assert report["account_id_found"] is True
    assert report["user"]["name_present"] is True
    assert report["permissions"]["has_ads_read"] is True
    assert report["permissions"]["has_business_management"] is True
    assert report["business_count"] == 1
    assert report["businesses"][0]["name_present"] is True
    assert report["accounts"][0]["name_present"] is True


def test_verify_meta_access_token_requires_accessible_accounts(monkeypatch) -> None:
    monkeypatch.setattr(verifier, "meta_access_token", lambda: "meta-token")
    monkeypatch.setattr(verifier, "MetaAdsProvider", EmptyProvider)

    with pytest.raises(SystemExit) as exc_info:
        verifier.verify_meta_access_token()

    assert "returned no accessible Meta ad accounts" in str(exc_info.value)


def test_verify_meta_access_token_can_report_empty_accounts(monkeypatch) -> None:
    monkeypatch.setattr(verifier, "meta_access_token", lambda: "meta-token")
    monkeypatch.setattr(verifier, "MetaAdsProvider", EmptyProvider)

    report = verifier.verify_meta_access_token(allow_empty_accounts=True)

    assert report["status"] == "connected_no_ad_accounts"
    assert report["account_count"] == 0
    assert report["account_id_found"] is True
    assert report["accounts"] == []


def test_main_writes_failed_report_when_meta_verification_fails(monkeypatch) -> None:
    reset_test_tmp()
    try:
        path = TEST_TMP / "meta-token-failed.json"
        monkeypatch.setattr(
            verifier,
            "parse_args",
            lambda: argparse.Namespace(
                account_id="123",
                account_limit=50,
                allow_empty_accounts=False,
                report_json=str(path),
            ),
        )
        monkeypatch.setattr(
            verifier,
            "verify_meta_access_token",
            lambda account_id="", account_limit=50, allow_empty_accounts=False: (_ for _ in ()).throw(
                SystemExit("Meta access token verification failed: 401 Unauthorized")
            ),
        )

        with pytest.raises(SystemExit):
            verifier.main()

        report = json.loads(path.read_text(encoding="utf-8"))
        assert report["status"] == "failed"
        assert report["platform"] == "meta"
        assert report["provider"] == "meta_graph_api"
        assert report["account_id_requested"] == "act_123"
        assert report["error_category"] == "authorization_failed"
    finally:
        reset_test_tmp()


def test_summarize_permissions() -> None:
    summary = verifier.summarize_permissions(
        [
            {"permission": "ads_management", "status": "granted"},
            {"permission": "pages_read_engagement", "status": "declined"},
        ]
    )

    assert summary["has_ads_read"] is True
    assert summary["has_business_management"] is False
    assert summary["granted"] == ["ads_management"]
    assert summary["declined_or_expired"] == ["pages_read_engagement"]


def test_verify_meta_access_token_requires_requested_account(monkeypatch) -> None:
    monkeypatch.setattr(verifier, "meta_access_token", lambda: "meta-token")
    monkeypatch.setattr(verifier, "MetaAdsProvider", FakeProvider)

    with pytest.raises(SystemExit) as exc_info:
        verifier.verify_meta_access_token(account_id="999")

    assert "was not found" in str(exc_info.value)


def test_write_report_creates_json_file() -> None:
    reset_test_tmp()
    try:
        path = TEST_TMP / "meta-token-report.json"
        verifier.write_report(path, {"status": "passed"})

        assert json.loads(path.read_text(encoding="utf-8")) == {"status": "passed"}
    finally:
        reset_test_tmp()


def test_normalize_account_id() -> None:
    assert verifier.normalize_account_id("123") == "act_123"
    assert verifier.normalize_account_id("act_123") == "act_123"


def reset_test_tmp() -> None:
    if TEST_TMP.exists():
        shutil.rmtree(TEST_TMP)
