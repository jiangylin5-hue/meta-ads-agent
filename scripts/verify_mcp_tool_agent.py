"""Live smoke for MCP-native tool search and the ReAct loop.

This makes a real model response and a read-only Meta MCP call. It supports
both deferred-tool and portable-tool provider modes and never calls a write-like MCP tool.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agent.runtime import AgentRuntime


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify provider tool exposure and a read-only ReAct turn.")
    parser.add_argument("--spend-credits", action="store_true", help="Required because this makes a real model call.")
    args = parser.parse_args()
    if not args.spend_credits:
        print("Refusing to call a real model without --spend-credits.", file=sys.stderr)
        return 2

    result = AgentRuntime(max_steps=8).run_turn(
        "Load the account_brief project skill, read its brief-shape reference, use the currently exposed Meta "
        "account-list tool to call ads_get_ad_accounts with limit 3, then call submit_result with reply, facts, "
        "missing_data, and source_tools matching account_brief_v1."
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    tools = list(result.get("tool_calls") or [])
    account_call = any(name in tools for name in ("ads_get_ad_accounts", "meta_ads.ads_get_ad_accounts"))
    if "load_skill" not in tools or "read_skill_reference" not in tools or not account_call or "submit_result" not in tools:
        print("Expected load_skill, read_skill_reference, ads_get_ad_accounts, and submit_result in the trace.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
