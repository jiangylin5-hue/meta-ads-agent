import json
import sys
from urllib import error, request


BASE_URL = "http://127.0.0.1:8010"


def main() -> None:
    base_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else BASE_URL

    connections = get_json(f"{base_url}/api/accounts/connections")
    diagnostics = get_json(f"{base_url}/api/accounts/mcp/diagnostics")
    index = get_json(f"{base_url}/")
    accounts = get_json(f"{base_url}/api/meta/adaccounts")
    account_id = first_account_id(accounts)
    campaigns = get_json(f"{base_url}/api/meta/adaccounts/{account_id}/campaigns")
    insights = get_json(f"{base_url}/api/meta/adaccounts/{account_id}/insights")

    assert_provider(connections)
    assert diagnostics.get("ready") is True, f"MCP diagnostics not ready: {diagnostics}"
    assert index.get("api") == "/api", f"Backend root did not return API metadata: {index}"
    assert accounts.get("accounts"), "No ad accounts returned from app API."
    assert campaigns.get("campaigns"), "No campaigns returned from app API."
    assert insights.get("insights"), "No insights returned from app API."

    print("App HTTP smoke test passed")
    print(f"base_url={base_url}")
    print(f"mcp_tools={diagnostics.get('tool_count')}")
    print("backend_api=loaded")
    print(f"account_id={account_id}")
    print(f"campaigns={len(campaigns.get('campaigns', []))}")
    print(f"insights={len(insights.get('insights', []))}")


def get_json(url: str) -> dict:
    try:
        with request.urlopen(request.Request(url, headers={"Accept": "application/json"}), timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {body}") from exc


def get_text(url: str) -> str:
    try:
        with request.urlopen(request.Request(url, headers={"Accept": "text/html,*/*"}), timeout=10) as response:
            return response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {body}") from exc


def first_account_id(payload: dict) -> str:
    accounts = payload.get("accounts") or []
    if not accounts:
        raise RuntimeError("No accounts returned from app API.")
    account = accounts[0]
    account_id = account.get("id") or account.get("account_id")
    if not account_id:
        raise RuntimeError(f"First account has no id: {account}")
    return account_id


def assert_provider(payload: dict) -> None:
    providers = [item.get("provider") for item in payload.get("connections", [])]
    if "meta_ads_mcp" not in providers:
        raise RuntimeError(f"meta_ads_mcp provider missing from /api/accounts/connections: {providers}")


if __name__ == "__main__":
    main()
