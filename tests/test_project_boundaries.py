from pathlib import Path

from backend.main import app


REMOVED_PATHS = [
    "backend/services/chat_workflow.py",
    "backend/services/chat_runtime_context.py",
    "backend/services/conversation_memory.py",
    "backend/services/llm_service.py",
    "backend/services/prompt_registry.py",
    "backend/services/query_rewrite.py",
    "backend/services/workspace_plan.py",
    "backend/route_handlers/chat.py",
    "backend/route_handlers/chat_intent.py",
    "backend/route_handlers/chat_responses.py",
    "backend/route_handlers/dashboard_helpers.py",
    "backend/routes/chat_routes.py",
    "backend/prompts",
]


def test_fixed_pipeline_files_are_removed() -> None:
    for path in REMOVED_PATHS:
        assert not Path(path).exists(), path


def test_api_has_one_agent_turn_route_and_no_legacy_chat_route() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/agent/turn" in paths
    assert "/api/chat" not in paths
    assert "/api/intent" not in paths


def test_route_handlers_stay_small_and_do_not_own_agent_loop() -> None:
    for path in Path("backend/route_handlers").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 400, path
        assert "while step" not in text, path

    loop = Path("backend/agent/runtime.py").read_text(encoding="utf-8")
    assert "for step in range(1, self.max_steps + 1)" in loop
    assert "ensure_tool_allowed" in loop

def test_mcp_native_tool_surface_is_code_enforced() -> None:
    tools = Path("backend/agent/tools.py").read_text(encoding="utf-8")
    runtime = Path("backend/agent/runtime.py").read_text(encoding="utf-8")
    agents = Path("AGENTS.md").read_text(encoding="utf-8")

    assert "defer_loading" in tools
    assert "tool_search" in runtime
    assert "load_skill" in runtime
    assert Path("backend/agent/skills.py").exists()
    assert Path("backend/skills/tool_groups.json").exists()
    assert len(list(Path("backend/skills").glob("*/SKILL.md"))) == 12
    assert len(list(Path("backend/skills").glob("*/references/*.md"))) >= 24
    assert not Path("backend/agent/performance.py").exists()
    for name in (
        "create_campaign",
        "create_adset",
        "create_ad",
        "create_ad_creative",
        "create_budget_schedule",
        "update_campaign",
        "update_adset",
        "update_ad",
        "update_ad_creative",
        "upload_ad_image",
    ):
        assert name in tools
    assert "DIRECT_DRAFT_CREATE_TOOLS" in tools
    assert "FORBIDDEN_PUBLISH_TOOLS" in tools
    assert "forwards only the four draft creation tools to mcp" in agents.lower()
    assert "ads_activate_entity" in agents

def test_official_meta_mcp_is_the_configured_provider() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")
    gateway = Path("backend/services/account_gateway.py").read_text(encoding="utf-8")

    assert "ADS_MCP_ENDPOINT_URL=https://mcp.facebook.com/ads" in env_example
    assert "Mcp-Session-Id" in gateway
    assert "notifications/initialized" in gateway
    assert "meta_official_mcp" in gateway
