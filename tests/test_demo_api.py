from fastapi.testclient import TestClient

from backend.main import app


def test_config_describes_the_react_runtime() -> None:
    client = TestClient(app)
    response = client.get("/api/config")
    payload = response.json()

    assert response.status_code == 200
    assert payload["runtime"]["name"] == "react"
    assert payload["runtime"]["execution"] == "disabled"
    assert payload["runtime"]["max_steps"] == 16
    assert payload["runtime"]["turn_timeout_seconds"] == 600
    assert payload["reasoning_effort"]
    assert payload["runtime"]["tool_namespace"] == "meta_ads"
    assert payload["llm_provider"] in {"openai", "deepseek"}
    if payload["llm_provider"] == "deepseek":
        assert payload["runtime"]["deferred_tools"] is False
        assert payload["runtime"]["tool_search"] is False
        assert payload["runtime"]["portable_tool_exposure"] is True
    else:
        assert payload["runtime"]["deferred_tools"] is True
        assert payload["runtime"]["tool_search"] is True
        assert payload["runtime"]["portable_tool_exposure"] is False
    assert payload["runtime"]["local_tools"] == ["ask_user", "load_skill", "read_skill_reference", "submit_result", "save_memory", "update_task"]
    assert payload["runtime"]["context_recent_rounds"] == 5
    assert payload["runtime"]["context_input_token_budget"] == 36000
    assert payload["runtime"]["long_term_memory"] is True
    assert payload["runtime"]["task_state"] is True
    assert payload["runtime"]["account_cache"] is True
    assert payload["runtime"]["direct_meta_drafts"] is True
    assert payload["runtime"]["activation"] == "blocked"
    assert isinstance(payload["meta_draft_write_enabled"], bool)
    assert payload["meta_live_write_enabled"] is False
    assert payload["runtime"]["skill_loader"] == "load_skill"
    assert payload["runtime"]["reference_loader"] == "read_skill_reference"
    assert payload["runtime"]["result_validator"] == "submit_result"
    assert payload["runtime"]["project_skill_count"] == 12
    assert payload["runtime"]["skill_scope_enforced"] is True
    assert "role_contract" not in payload
    assert "quality_registry" not in payload


def test_live_execution_routes_are_disabled() -> None:
    client = TestClient(app)

    execute = client.post("/api/actions/drafts/act_1/execute", json={})
    rollback = client.post("/api/actions/execution_1/rollback", json={})

    assert execute.status_code == 410
    assert execute.json()["detail"]["code"] == "execution_disabled_in_demo"
    assert rollback.status_code == 410
    assert rollback.json()["detail"]["code"] == "execution_disabled_in_demo"


def test_memory_candidate_resolution_routes_are_exposed() -> None:
    routes = {
        (route.path, method)
        for route in app.routes
        for method in (getattr(route, "methods", set()) or set())
    }

    assert ("/api/memory/{memory_id}/confirm", "POST") in routes
    assert ("/api/memory/{memory_id}/reject", "POST") in routes
