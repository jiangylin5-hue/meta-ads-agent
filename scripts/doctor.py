import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import (
    account_gateway_preference,
    openai_api_key,
    openai_model,
    remote_ads_mcp_endpoint,
    remote_ads_mcp_token,
)
from backend.services.account_gateway import RemoteMcpGateway


def main() -> None:
    failures: list[str] = []
    warnings: list[str] = []

    print("Ads Agent environment doctor")
    print("============================")

    preference = account_gateway_preference()
    print_status("gateway.preference", preference, ok=preference == "mcp")
    if preference != "mcp":
        warnings.append("ACCOUNT_GATEWAY_PREFERENCE is not mcp; the default workflow expects MCP-first.")

    endpoint = remote_ads_mcp_endpoint()
    print_status("ads_mcp.endpoint", redact_endpoint(endpoint), ok=bool(endpoint))
    if not endpoint:
        failures.append("ADS_MCP_ENDPOINT_URL is not configured.")

    token = remote_ads_mcp_token()
    print_status("ads_mcp.token", "configured" if token else "not configured", ok=bool(token), warn_when_false=True)
    if not token:
        warnings.append("ADS_MCP_API_TOKEN/PIPEBOARD_API_TOKEN/ADS_MCP_AUTH_TOKEN/META_ACCESS_TOKEN is not configured.")

    openai_key = openai_api_key()
    print_status("openai.key", "configured" if openai_key else "not configured", ok=bool(openai_key), warn_when_false=True)
    if not openai_key:
        warnings.append("/analysis requires OPENAI_API_KEY for real LLM audit.")
    print_status("openai.model", openai_model(), ok=True)

    diagnostics = RemoteMcpGateway().diagnostics()
    print_status("mcp.reachable", str(diagnostics.get("reachable")), ok=bool(diagnostics.get("reachable")))
    print_status("mcp.ready", str(diagnostics.get("ready")), ok=bool(diagnostics.get("ready")))
    print_status("mcp.tool_count", str(diagnostics.get("tool_count", 0)), ok=bool(diagnostics.get("ready")))

    missing = diagnostics.get("missing_required_tools") or []
    if missing:
        failures.append(f"MCP is missing required tools: {', '.join(missing)}")
    if diagnostics.get("error") and str(diagnostics["error"]) not in failures:
        failures.append(str(diagnostics["error"]))

    if warnings:
        print("\nWarnings")
        for item in warnings:
            print(f"- {item}")

    if failures:
        print("\nFailures")
        for item in failures:
            print(f"- {item}")
        raise SystemExit(1)

    print("\nDoctor passed. MCP is ready for account data reads.")


def print_status(name: str, value: str, ok: bool, warn_when_false: bool = False) -> None:
    if ok:
        marker = "PASS"
    elif warn_when_false:
        marker = "WARN"
    else:
        marker = "FAIL"
    print(f"[{marker}] {name}: {value}")


def redact_endpoint(endpoint: str) -> str:
    if not endpoint:
        return "not configured"
    return endpoint.split("?")[0]


if __name__ == "__main__":
    main()
