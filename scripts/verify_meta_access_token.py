import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import load_dotenv, meta_access_token, meta_graph_api_version
from backend.integrations.meta_ads import MetaAdsProvider


ROOT = Path(__file__).resolve().parents[1]


def is_configured_secret(value: str | None) -> bool:
    normalized = (value or "").strip().strip('"').strip("'")
    if not normalized or not normalized.isascii():
        return False
    lowered = normalized.lower()
    placeholders = {
        "your-key",
        "your-openai-key",
        "sk-your-key-here",
        "your-token",
        "your-mcp-token",
        "your-meta-access-token",
        "replace-me",
        "changeme",
        "todo",
    }
    if lowered in placeholders:
        return False
    if lowered.startswith(("your-", "replace-", "example-", "dummy-")):
        return False
    return True


def main() -> None:
    load_dotenv()
    args = parse_args()
    try:
        report = verify_meta_access_token(
            account_id=args.account_id,
            account_limit=args.account_limit,
            allow_empty_accounts=args.allow_empty_accounts,
        )
    except SystemExit as exc:
        report = failed_report(account_id=args.account_id, error=str(exc))
        if args.report_json:
            write_report(Path(args.report_json), report)
        raise
    if args.report_json:
        write_report(Path(args.report_json), report)

    print("Meta access token verification passed")
    print(f"user_id={report.get('user', {}).get('id', '')}")
    print(f"account_count={report['account_count']}")
    if args.account_id:
        print(f"account_id_found={report['account_id_found']}")
    if args.report_json:
        print(f"report_json={Path(args.report_json).resolve()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify META_ACCESS_TOKEN can read Meta ad accounts.")
    parser.add_argument("--account-id", default="", help="Optional ad account id to require, with or without act_ prefix.")
    parser.add_argument("--account-limit", type=int, default=50, help="Maximum ad accounts to fetch.")
    parser.add_argument(
        "--allow-empty-accounts",
        action="store_true",
        help="Pass when the token owner has no ad accounts yet; still writes a connection diagnostic report.",
    )
    parser.add_argument("--report-json", default="", help="Optional path for a machine-readable verification report.")
    return parser.parse_args()


def verify_meta_access_token(
    account_id: str = "",
    account_limit: int = 50,
    allow_empty_accounts: bool = False,
) -> dict[str, Any]:
    if not is_configured_secret(meta_access_token()):
        raise SystemExit("META_ACCESS_TOKEN is missing or still a placeholder.")

    provider = MetaAdsProvider()
    try:
        user = provider.get_me()
        permissions = provider.list_permissions()
        businesses = provider.list_businesses(limit=account_limit)
        accounts = provider.list_ad_accounts(limit=account_limit)
    except Exception as exc:
        raise SystemExit(f"Meta access token verification failed: {exc}") from exc

    if not accounts and not allow_empty_accounts:
        raise SystemExit("META_ACCESS_TOKEN is valid, but returned no accessible Meta ad accounts.")

    normalized_account_id = normalize_account_id(account_id) if account_id else ""
    account_id_found = not normalized_account_id or any(
        normalize_account_id(str(item.get("id") or item.get("account_id") or "")) == normalized_account_id
        for item in accounts
    )
    if normalized_account_id and not account_id_found:
        raise SystemExit(f"Account {normalized_account_id} was not found in accessible Meta ad accounts.")

    return {
        "status": "passed" if accounts else "connected_no_ad_accounts",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": "meta",
        "provider": "meta_graph_api",
        "graph_api_version": meta_graph_api_version(),
        "user": redact_user(user),
        "permissions": summarize_permissions(permissions),
        "business_count": len(businesses),
        "businesses": [redact_business(item) for item in businesses],
        "account_count": len(accounts),
        "account_id_requested": normalized_account_id,
        "account_id_found": account_id_found,
        "accounts": [redact_account(item) for item in accounts],
    }


def normalize_account_id(account_id: str) -> str:
    value = account_id.strip()
    if not value:
        return ""
    return value if value.startswith("act_") else f"act_{value}"


def redact_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(user.get("id", "")),
        "name_present": bool(user.get("name")),
    }


def redact_account(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": normalize_account_id(str(account.get("id") or account.get("account_id") or "")),
        "name_present": bool(account.get("name")),
        "account_status": account.get("account_status", ""),
        "currency": account.get("currency", ""),
        "timezone_name": account.get("timezone_name", ""),
    }


def redact_business(business: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(business.get("id", "")),
        "name_present": bool(business.get("name")),
    }


def summarize_permissions(permissions: list[dict[str, Any]]) -> dict[str, Any]:
    granted = sorted(
        str(item.get("permission", ""))
        for item in permissions
        if item.get("permission") and item.get("status") == "granted"
    )
    declined = sorted(
        str(item.get("permission", ""))
        for item in permissions
        if item.get("permission") and item.get("status") != "granted"
    )
    return {
        "granted": granted,
        "declined_or_expired": declined,
        "has_ads_read": "ads_read" in granted or "ads_management" in granted,
        "has_business_management": "business_management" in granted,
    }


def failed_report(*, account_id: str = "", error: str = "") -> dict[str, Any]:
    return {
        "status": "failed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": "meta",
        "provider": "meta_graph_api",
        "graph_api_version": meta_graph_api_version(),
        "account_id_requested": normalize_account_id(account_id) if account_id else "",
        "account_count": 0,
        "account_id_found": False if account_id else True,
        "error_category": classify_error(error),
        "error": error[:1000],
    }


def classify_error(error: str) -> str:
    text = (error or "").lower()
    if "401" in text or "unauthorized" in text or "oauth" in text or "access token" in text:
        return "authorization_failed"
    if "no accessible meta ad accounts" in text:
        return "no_accessible_ad_accounts"
    if "was not found" in text:
        return "account_not_found"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    return "verification_failed"


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
