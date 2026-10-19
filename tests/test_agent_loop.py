from __future__ import annotations

import json
import time
from threading import Event
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from backend.agent.runtime import AgentRuntime, _build_live_read_evidence, _draft_evidence_errors, _draft_mutation_evidence_errors
from backend.agent.state import AgentState
from backend.agent.tools import MAX_GENERAL_RESULT_CHARS, MetaToolRegistry, is_forbidden_publish_tool
from backend.main import app


MCP_TOOL_NAMES = (
    "ads_get_ad_accounts",
    "ads_get_ad_entities",
    "ads_insights_advertiser_context",
    "ads_get_field_context",
    "ads_insights_performance_trend",
    "ads_insights_anomaly_signal",
    "ads_insights_auction_ranking_benchmarks",
    "ads_insights_industry_benchmark",
    "ads_get_opportunity_score",
    "ads_account_get_activity_logs",
    "ads_get_errors",
    "ads_get_creatives",
    "ads_get_creative_ads",
    "ads_get_ad_preview",
    "ads_get_ad_images",
    "ads_get_ad_videos",
    "ads_update_entity",
    "ads_create_creative",
    "ads_create_ad",
    "ads_activate_entity",
    "ads_creative_update",
    "ads_create_campaign",
    "ads_create_ad_set",
)


def _tool_definitions() -> list[dict[str, Any]]:
    definitions = []
    for name in MCP_TOOL_NAMES:
        properties: dict[str, Any] = {
            "access_token": {"type": "string"},
            "advertiser_request": {"type": "string"},
            "advertiser_job": {"type": "string"},
        }
        required: list[str] = []
        if name not in {"ads_get_ad_accounts"}:
            properties["ad_account_id"] = {"type": "string"}
            required.append("ad_account_id")
        if name == "ads_get_ad_entities":
            properties["date_preset"] = {"type": "string"}
            properties["time_range"] = {"type": "object"}
            properties["level"] = {"type": "string"}
        if name == "ads_insights_performance_trend":
            properties["analysis_level"] = {"type": "string"}
        if name == "ads_update_entity":
            properties["entity_id"] = {"type": "string"}
            properties["entity_type"] = {"type": "string"}
            properties["fields"] = {"type": "object"}
            required.extend(["entity_id", "entity_type", "fields"])
        if name.startswith("ads_create_"):
            properties["name"] = {"type": "string"}
        definitions.append(
            {
                "name": name,
                "description": f"Tool {name}",
                "inputSchema": {"type": "object", "properties": properties, "required": required},
            }
        )
    return definitions


class FakeMCP:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_tools(self) -> list[dict[str, Any]]:
        return _tool_definitions()

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.calls.append((name, dict(arguments or {})))
        if name == "ads_get_ad_entities":
            return {"data": [{"id": "cmp_1", "campaign_id": "cmp_1", "name": "Demo Campaign", "status": "ACTIVE", "effective_status": "ACTIVE", "daily_budget": "6250", "learning_stage_info": "ACTIVE", "impressions": 12000, "clicks": 300, "results": 40}]}
        return {"data": [{"id": "act_1", "name": "Demo Account"}]}


class FakeLLM:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]] = []

    def complete(self, instructions: str, input_items: list[dict[str, Any]], tools: list[dict[str, Any]], **_kwargs: Any) -> dict[str, Any]:
        self.calls.append((instructions, input_items, tools))
        if not self.responses:
            raise AssertionError("FakeLLM has no response left")
        return self.responses.pop(0)


def _function_response(name: str, arguments: dict[str, Any], namespace: str = "meta_ads", *, search: bool = False) -> dict[str, Any]:
    import json

    output_items = []
    if search:
        output_items.extend(
            [
                {
                    "type": "tool_search_call",
                    "arguments": {"paths": [namespace], "query": name},
                    "execution": "server",
                    "status": "completed",
                },
                {
                    "type": "tool_search_output",
                    "tools": [{"type": "namespace", "name": namespace, "tools": [{"type": "function", "name": name}]}],
                },
            ]
        )
    output_items.append(
        {
            "type": "function_call",
            "call_id": f"call_{name}",
            "name": name,
            "namespace": namespace,
            "arguments": json.dumps(arguments),
        }
    )
    return {
        "content": "",
        "output_items": output_items,
        "tool_calls": [{"id": f"call_{name}", "name": name, "namespace": namespace, "arguments": json.dumps(arguments)}],
    }


def _skill_response(skill_id: str) -> dict[str, Any]:
    return _function_response("load_skill", {"skill_id": skill_id}, namespace="")


def _submit_response(
    result: dict[str, Any],
    reply: str = "Done.",
    draft_action_ids: list[str] | None = None,
) -> dict[str, Any]:
    payload = {"reply": reply, "result": result, "draft_action_ids": draft_action_ids or []}
    return _function_response("submit_result", payload, namespace="")


def _multi_submit_response(
    skill_results: dict[str, Any],
    resolved_decision: str,
    conflicts: list[str] | None = None,
    reply: str = "Done.",
) -> dict[str, Any]:
    return _function_response(
        "submit_result",
        {
            "reply": reply,
            "skill_results": skill_results,
            "resolved_decision": resolved_decision,
            "conflicts": conflicts or [],
        },
        namespace="",
    )


def _final_response(text: str) -> dict[str, Any]:
    return {"content": text, "output_items": [{"type": "message", "role": "assistant", "content": text}], "tool_calls": []}


def _registry(mcp: FakeMCP, *, draft_creator=None, action_creator=None, preflight_runner=None) -> MetaToolRegistry:
    return MetaToolRegistry(
        mcp_client=mcp,
        tool_definitions=_tool_definitions(),
        draft_creator=draft_creator,
        action_creator=action_creator,
        preflight_runner=preflight_runner,
    )


def test_react_loop_loads_tool_with_search_then_answers() -> None:
    mcp = FakeMCP()
    llm = FakeLLM(
        [
            _skill_response("account_brief"),
            _function_response("ads_get_ad_accounts", {"limit": 3}, search=True),
            _submit_response({"facts": ["Three readable accounts."], "missing_data": [], "source_tools": ["ads_get_ad_accounts"]}, "There are readable accounts. Next, choose one."),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(mcp), max_steps=4).run_turn("Which accounts are readable?")

    assert result["reply"] == "There are readable accounts. Next, choose one."
    assert result["stopped_reason"] == "final"
    assert result["tool_calls"] == ["load_skill", "tool_search", "meta_ads.ads_get_ad_accounts", "submit_result"]
    assert result["skills_loaded"] == ["account_brief"]
    assert result["structured_result"]["skill_results"]["account_brief"]["facts"] == ["Three readable accounts."]
    assert result["intent_type"] == "read_data"
    assert mcp.calls[0][0] == "ads_get_ad_accounts"
    assert "access_token" not in llm.calls[0][2][0]["tools"][0]["parameters"]["properties"]


def test_registry_exposes_official_deferred_tools_and_tool_search() -> None:
    schemas = _registry(FakeMCP()).schemas()
    namespace = schemas[0]
    assert namespace["type"] == "namespace"
    assert namespace["name"] == "meta_ads"
    assert len(namespace["tools"]) == len(MCP_TOOL_NAMES) - 1
    assert "ads_activate_entity" not in {tool["name"] for tool in namespace["tools"]}
    assert all(tool["defer_loading"] is True for tool in namespace["tools"])
    assert {"type": "tool_search"} in schemas
    assert {item.get("name") for item in schemas if item.get("type") == "function"} == {"ask_user"}
    update_schema = next(tool for tool in namespace["tools"] if tool["name"] == "ads_update_entity")
    assert "access_token" not in update_schema["parameters"]["properties"]
    assert "evidence" in update_schema["parameters"]["required"]
    assert "recommendation" in update_schema["parameters"]["required"]
    assert "risk_level" in update_schema["parameters"]["required"]
    assert "current_state" in update_schema["parameters"]["required"]


def test_write_tool_creates_draft_without_calling_mcp() -> None:
    mcp = FakeMCP()
    captured: dict[str, Any] = {}

    def create_draft(request):
        captured["request"] = request
        return SimpleNamespace(id="draft_1", status="draft")

    def create_action(draft):
        return SimpleNamespace(id="act_1", status="draft_created")

    def preflight(action_id):
        return {"preflight": {"result": "allowed", "blocked_reasons": []}}

    llm = FakeLLM(
        [
            _skill_response("optimization_draft"),
            _function_response(
                "ads_get_ad_entities",
                {"ad_account_id": "act_1", "date_preset": "last_7d", "level": "campaign", "force_refresh": True},
            ),
            _function_response(
                "ads_update_entity",
                {
                    "ad_account_id": "act_1",
                    "entity_id": "cmp_1",
                    "entity_type": "campaign",
                    "fields": {"daily_budget": 5000},
                    "evidence": "CPA doubled while spend was flat.",
                    "recommendation": "Reduce the daily budget by 20%.",
                    "risk_level": "high",
                    "current_state": {
                        "current_budget": 6250,
                        "current_status": "ACTIVE",
                        "sample_size": {"impressions": 12000},
                        "learning_state": "ACTIVE",
                        "comparison_window": "previous_7d",
                    },
                },
                search=True,
            ),
            _submit_response(
                {
                    "evidence": "CPA doubled while spend was flat.",
                    "recommendation": "Reduce the daily budget by 20%.",
                    "current_state": {
                        "current_budget": 6250,
                        "current_status": "ACTIVE",
                        "sample_size": {"impressions": 12000},
                        "learning_state": "ACTIVE",
                        "comparison_window": "previous_7d",
                    },
                    "current_budget": 6250,
                    "current_status": "ACTIVE",
                    "sample_size": {"impressions": 12000},
                    "learning_state": "ACTIVE",
                    "comparison_window": "previous_7d",
                    "source_tools": ["ads_get_ad_entities"],
                    "proposed_change": {"daily_budget": 5000},
                    "risk_level": "high",
                    "rollback": "Restore the previous budget.",
                    "requires_approval": True,
                    "decision": "FIX",
                },
                "I prepared a draft for approval.",
                draft_action_ids=["staged_1"],
            ),
        ]
    )
    result = AgentRuntime(
        llm=llm,
        tools=_registry(mcp, draft_creator=create_draft, action_creator=create_action, preflight_runner=preflight),
        max_steps=6,
    ).run_turn("Reduce this campaign budget.")

    assert [call[0] for call in mcp.calls] == ["ads_get_ad_entities"]
    assert result["drafts"][0]["draft_id"] == "draft_1"
    assert result["drafts"][0]["evidence"] == "CPA doubled while spend was flat."
    assert captured["request"].action["action_type"] == "ads_update_entity"
    assert captured["request"].action["proposed_value"]["fields"]["daily_budget"] == 5000
    assert captured["request"].action["current_value"]["current_budget"] == "6250"


def test_meta_tool_requires_a_loaded_skill() -> None:
    mcp = FakeMCP()
    llm = FakeLLM([_function_response("ads_get_ad_accounts", {}, search=True), _final_response("No skill loaded.")])
    result = AgentRuntime(llm=llm, tools=_registry(mcp), max_steps=3).run_turn("Check my ads.")

    assert mcp.calls == []
    assert result["trace"][1]["result"]["error"].startswith("Tool is outside the loaded skill scope")


def test_more_than_eight_skills_are_rejected() -> None:
    skill_ids = [
        "account_brief",
        "performance_diagnosis",
        "creative_diagnosis",
        "campaign_plan",
        "policy_preflight",
        "tracking_troubleshooting",
        "audience_audit",
        "catalog_health",
        "competitive_research",
    ]
    llm = FakeLLM([_skill_response(skill_id) for skill_id in skill_ids])
    result = AgentRuntime(llm=llm, tools=_registry(FakeMCP()), max_steps=9).run_turn("Check everything.")

    assert result["skills_loaded"] == skill_ids[:8]
    assert result["trace"][8]["result"]["error"].startswith("At most 8 skills")


def test_batch_load_accepts_eight_skills() -> None:
    skill_ids = [
        "account_brief",
        "performance_diagnosis",
        "creative_diagnosis",
        "campaign_plan",
        "policy_preflight",
        "tracking_troubleshooting",
        "audience_audit",
        "catalog_health",
    ]
    llm = FakeLLM([_function_response("load_skill", {"skill_ids": skill_ids})])
    result = AgentRuntime(llm=llm, tools=_registry(FakeMCP()), max_steps=1).run_turn("Load the full launch skill set.")

    assert len(result["skills_loaded"]) == 8
    assert "error" not in result["trace"][0]["result"]

def test_load_skill_accepts_multiple_ids_for_multi_intent_requests() -> None:
    llm = FakeLLM(
        [
            _function_response(
                "load_skill",
                {"skill_ids": ["account_brief", "performance_diagnosis", "creative_diagnosis"]},
                namespace="",
            ),
            _function_response(
                "ads_get_ad_entities",
                {"ad_account_id": "act_1", "date_preset": "last_7d", "level": "campaign", "force_refresh": True},
            ),
            _multi_submit_response(
                {
                    "account_brief": {
                        "facts": ["Read the account."],
                        "missing_data": [],
                        "source_tools": ["ads_get_ad_entities"],
                    },
                    "performance_diagnosis": {
                        "facts": ["Read the account."],
                        "hypotheses": [],
                        "missing_data": [],
                        "decision": "HOLD",
                        "comparison_window": "previous_7d",
                        "sample_size": {"impressions": 12000},
                        "learning_state": "ACTIVE",
                        "source_tools": ["ads_get_ad_entities"],
                    },
                    "creative_diagnosis": {
                        "facts": ["Read the account."],
                        "hypotheses": [],
                        "missing_data": [],
                        "decision": "HOLD",
                        "source_tools": ["ads_get_ad_entities"],
                    },
                },
                "HOLD",
                reply="Loaded the needed skills.",
            ),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(FakeMCP()), max_steps=4).run_turn("multi intent request")

    assert result["skills_loaded"] == ["account_brief", "performance_diagnosis", "creative_diagnosis"]
    assert result["trace"][0]["result"]["skill"] == "account_brief + performance_diagnosis + creative_diagnosis"
    load_tool = next(tool for tool in llm.calls[0][2] if tool.get("name") == "load_skill")
    assert load_tool["parameters"]["properties"]["skill_ids"]["maxItems"] == 8


def test_multi_skill_decision_conflict_requires_model_resolution() -> None:
    results = {
        "performance_diagnosis": {
            "facts": ["CPA changed."],
            "hypotheses": ["Creative fatigue is possible."],
            "missing_data": [],
            "decision": "HOLD",
            "comparison_window": "previous_7d",
            "sample_size": {"impressions": 12000},
            "learning_state": "ACTIVE",
            "source_tools": ["ads_get_ad_entities"],
        },
        "optimization_draft": {
            "evidence": "CPA changed and current state was read.",
            "recommendation": "Reduce budget.",
            "current_state": {
                "current_budget": 6250,
                "current_status": "ACTIVE",
                "sample_size": {"impressions": 12000},
                "learning_state": "ACTIVE",
                "comparison_window": "previous_7d",
            },
            "current_budget": 6250,
            "current_status": "ACTIVE",
            "sample_size": {"impressions": 12000},
            "learning_state": "ACTIVE",
            "comparison_window": "previous_7d",
            "source_tools": ["ads_get_ad_entities"],
            "proposed_change": {"daily_budget": 5000},
            "risk_level": "medium",
            "rollback": "Restore the previous budget.",
            "requires_approval": True,
            "decision": "FIX",
        },
    }
    llm = FakeLLM(
        [
            _skill_response("performance_diagnosis"),
            _skill_response("optimization_draft"),
            _function_response(
                "ads_get_ad_entities",
                {"ad_account_id": "act_1", "date_preset": "last_7d", "level": "campaign", "force_refresh": True},
            ),
            _multi_submit_response(results, "INVESTIGATE", reply="Resolve the evidence gap first."),
            _multi_submit_response(
                results,
                "INVESTIGATE",
                conflicts=["Performance recommends HOLD while optimization proposes FIX."],
                reply="Resolve the evidence gap first.",
            ),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(FakeMCP()), max_steps=5).run_turn("Why did CPA change and should we cut budget?")

    assert result["trace"][3]["result"]["missing_conflicts"]
    assert result["reply"] == "Resolve the evidence gap first."
    assert result["structured_result"]["resolved_decision"] == "INVESTIGATE"
    assert result["structured_result"]["conflicts"]


def test_reference_is_loaded_only_after_skill_and_is_traced() -> None:
    llm = FakeLLM(
        [
            _skill_response("performance_diagnosis"),
            _function_response(
                "read_skill_reference",
                {"skill_id": "performance_diagnosis", "reference_id": "evaluation-level"},
                namespace="",
            ),
            _function_response(
                "ads_get_ad_entities",
                {"ad_account_id": "act_1", "date_preset": "last_7d", "level": "campaign", "force_refresh": True},
            ),
            _submit_response(
                {
                    "facts": ["Evaluation level read."],
                    "hypotheses": [],
                    "missing_data": [],
                    "decision": "HOLD",
                    "comparison_window": "previous_7d",
                    "sample_size": {"impressions": 12000},
                    "learning_state": "ACTIVE",
                    "source_tools": ["ads_get_ad_entities"],
                },
                "Read the evaluation-level reference.",
            ),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(FakeMCP()), max_steps=5).run_turn("why did campaign CPA change")

    assert result["skills_loaded"] == ["performance_diagnosis"]
    assert result["references_loaded"] == ["performance_diagnosis.evaluation-level"]
    assert result["trace"][1]["result"]["reference"] == "evaluation-level"


def test_reference_requires_its_skill_to_be_loaded_first() -> None:
    llm = FakeLLM(
        [
            _function_response(
                "read_skill_reference",
                {"skill_id": "performance_diagnosis", "reference_id": "evaluation-level"},
                namespace="",
            ),
            _final_response("Cannot read it yet."),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(FakeMCP()), max_steps=3).run_turn("Read the reference.")

    assert result["references_loaded"] == []
    assert result["trace"][0]["result"]["error"].startswith("Load skill performance_diagnosis")


def test_missing_date_window_is_rejected_before_mcp() -> None:
    mcp = FakeMCP()
    llm = FakeLLM(
        [
            _skill_response("performance_diagnosis"),
            _function_response("ads_get_ad_entities", {"ad_account_id": "act_1", "level": "campaign"}),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(mcp), max_steps=2).run_turn("Why did CPA change?")

    assert mcp.calls == []
    assert "date window" in result["trace"][1]["result"]["error"]


def test_submit_requires_a_successful_read_for_evidence() -> None:
    llm = FakeLLM(
        [
            _skill_response("performance_diagnosis"),
            _submit_response(
                {"facts": [], "hypotheses": [], "missing_data": [], "decision": "HOLD"},
                "First attempt.",
            ),
            _function_response(
                "ads_get_ad_entities",
                {"ad_account_id": "act_1", "date_preset": "last_7d", "level": "campaign", "force_refresh": True},
            ),
            _submit_response(
                {
                    "facts": ["Read the entity."],
                    "hypotheses": [],
                    "missing_data": [],
                    "decision": "HOLD",
                    "comparison_window": "previous_7d",
                    "sample_size": {"impressions": 12000},
                    "learning_state": "ACTIVE",
                    "source_tools": ["ads_get_ad_entities"],
                },
                "Validated result.",
            ),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(FakeMCP()), max_steps=5).run_turn("Why did CPA change?")

    assert result["trace"][1]["result"]["missing_evidence"]
    assert result["reply"] == "Validated result."
    assert result["structured_result"]["skill_results"]["performance_diagnosis"]["decision"] == "HOLD"


def test_submit_validates_required_fields_and_decision_modes() -> None:
    llm = FakeLLM(
        [
            _skill_response("performance_diagnosis"),
            _function_response(
                "ads_get_ad_entities",
                {"ad_account_id": "act_1", "date_preset": "last_7d", "level": "campaign", "force_refresh": True},
            ),
            _submit_response({"facts": ["A fact."], "decision": "BAD"}, "Invalid."),
            _submit_response(
                {
                    "facts": ["A fact."],
                    "hypotheses": [],
                    "missing_data": [],
                    "decision": "HOLD",
                    "comparison_window": "previous_7d",
                    "sample_size": {"impressions": 12000},
                    "learning_state": "ACTIVE",
                    "source_tools": ["ads_get_ad_entities"],
                },
                "Valid.",
            ),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(FakeMCP()), max_steps=5).run_turn("Why did CPA change?")

    invalid = result["trace"][2]["result"]
    assert invalid["missing_fields"] or invalid["invalid_fields"]
    assert result["reply"] == "Valid."


def test_plain_final_is_rejected_until_submit_result() -> None:
    llm = FakeLLM(
        [
            _skill_response("account_brief"),
            _function_response("ads_get_ad_accounts", {}),
            _final_response("Plain answer."),
            _submit_response({"facts": ["Read the account."], "missing_data": [], "source_tools": ["ads_get_ad_accounts"]}, "Structured answer."),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(FakeMCP()), max_steps=5).run_turn("Which accounts are readable?")

    assert result["reply"] == "Structured answer."
    assert result["structured_result"]["skill_results"]["account_brief"]["facts"] == ["Read the account."]


def test_write_requires_a_successful_read_before_drafting() -> None:
    mcp = FakeMCP()
    llm = FakeLLM(
        [
            _skill_response("optimization_draft"),
            _function_response(
                "ads_update_entity",
                {
                    "ad_account_id": "act_1",
                    "entity_id": "cmp_1",
                    "entity_type": "campaign",
                    "fields": {"daily_budget": 5000},
                    "evidence": "CPA doubled while spend was flat.",
                    "recommendation": "Reduce the daily budget by 20%.",
                    "risk_level": "high",
                    "current_state": {
                        "current_budget": 6250,
                        "current_status": "ACTIVE",
                        "sample_size": {"impressions": 12000},
                        "learning_state": "ACTIVE",
                        "comparison_window": "previous_7d",
                    },
                },
            ),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(mcp), max_steps=2).run_turn("Change the budget.")

    assert mcp.calls == []
    assert "successful live read tool call" in result["trace"][1]["result"]["missing_evidence"]


def test_optimization_draft_requires_current_budget_status_and_context() -> None:
    mcp = FakeMCP()
    llm = FakeLLM(
        [
            _skill_response("optimization_draft"),
            _function_response(
                "ads_get_ad_entities",
                {"ad_account_id": "act_1", "date_preset": "last_7d", "level": "campaign", "force_refresh": True},
            ),
            _function_response(
                "ads_update_entity",
                {
                    "ad_account_id": "act_1",
                    "entity_id": "cmp_1",
                    "entity_type": "campaign",
                    "fields": {"daily_budget": 5000},
                    "evidence": "CPA doubled while spend was flat.",
                    "recommendation": "Reduce the daily budget by 20%.",
                    "risk_level": "high",
                    "current_state": {"current_status": "ACTIVE"},
                },
            ),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(mcp), max_steps=3).run_turn("Change the budget.")

    assert [call[0] for call in mcp.calls] == ["ads_get_ad_entities"]
    missing = result["trace"][2]["result"]["missing_evidence"]
    assert "current_state.current_budget" in missing
    assert "current_state.sample_size" in missing
    assert "current_state.learning_state" in missing
    assert "current_state.comparison_window" in missing


def test_write_requires_force_refreshed_live_read_for_draft_account() -> None:
    mcp = FakeMCP()
    llm = FakeLLM(
        [
            _skill_response("optimization_draft"),
            _function_response(
                "ads_get_ad_entities",
                {"ad_account_id": "act_1", "date_preset": "last_7d", "level": "campaign"},
            ),
            _function_response(
                "ads_update_entity",
                {
                    "ad_account_id": "act_1",
                    "entity_id": "cmp_1",
                    "entity_type": "campaign",
                    "fields": {"daily_budget": 5000},
                    "evidence": "CPA doubled while spend was flat.",
                    "recommendation": "Reduce the daily budget by 20%.",
                    "risk_level": "high",
                    "current_state": {
                        "current_budget": 6250,
                        "current_status": "ACTIVE",
                        "sample_size": {"impressions": 12000},
                        "learning_state": "ACTIVE",
                        "comparison_window": "previous_7d",
                    },
                },
            ),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(mcp), max_steps=3).run_turn("Change the budget.")

    assert [call[0] for call in mcp.calls] == ["ads_get_ad_entities"]
    assert "live read with force_refresh=true for draft account" in result["trace"][2]["result"]["missing_evidence"]


def test_write_requires_live_read_for_draft_target() -> None:
    mcp = FakeMCP()
    llm = FakeLLM(
        [
            _skill_response("optimization_draft"),
            _function_response(
                "ads_get_ad_entities",
                {"ad_account_id": "act_1", "date_preset": "last_7d", "level": "campaign", "force_refresh": True},
            ),
            _function_response(
                "ads_update_entity",
                {
                    "ad_account_id": "act_1",
                    "entity_id": "cmp_999",
                    "entity_type": "campaign",
                    "fields": {"daily_budget": 5000},
                    "evidence": "CPA doubled while spend was flat.",
                    "recommendation": "Reduce the daily budget by 20%.",
                    "risk_level": "high",
                    "current_state": {
                        "current_budget": 6250,
                        "current_status": "ACTIVE",
                        "sample_size": {"impressions": 12000},
                        "learning_state": "ACTIVE",
                        "comparison_window": "previous_7d",
                    },
                },
            ),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(mcp), max_steps=3).run_turn("Change the budget.")

    assert [call[0] for call in mcp.calls] == ["ads_get_ad_entities"]
    assert "live read for draft target campaign:cmp_999" in result["trace"][2]["result"]["missing_evidence"]


def test_optimization_draft_rejects_mismatched_current_state() -> None:
    mcp = FakeMCP()
    llm = FakeLLM(
        [
            _skill_response("optimization_draft"),
            _function_response(
                "ads_get_ad_entities",
                {"ad_account_id": "act_1", "date_preset": "last_7d", "level": "campaign", "force_refresh": True},
            ),
            _function_response(
                "ads_update_entity",
                {
                    "ad_account_id": "act_1",
                    "entity_id": "cmp_1",
                    "entity_type": "campaign",
                    "fields": {"daily_budget": 5000},
                    "evidence": "CPA doubled while spend was flat.",
                    "recommendation": "Reduce the daily budget by 20%.",
                    "risk_level": "high",
                    "current_state": {
                        "current_budget": 99999,
                        "current_status": "ACTIVE",
                        "sample_size": {"impressions": 12000},
                        "learning_state": "ACTIVE",
                        "comparison_window": "previous_7d",
                    },
                },
            ),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(mcp), max_steps=3).run_turn("Change the budget.")

    assert [call[0] for call in mcp.calls] == ["ads_get_ad_entities"]
    assert "current_state.current_budget does not match live read" in result["trace"][2]["result"]["missing_evidence"]
    assert result["drafts"] == []


def test_optimization_draft_rejects_unverifiable_sample_size() -> None:
    class MissingMetricsMCP(FakeMCP):
        def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
            self.calls.append((name, dict(arguments or {})))
            return {
                "data": [
                    {
                        "id": "cmp_1",
                        "effective_status": "ACTIVE",
                        "daily_budget": "6250",
                        "learning_stage_info": "ACTIVE",
                    }
                ]
            }

    mcp = MissingMetricsMCP()
    llm = FakeLLM(
        [
            _skill_response("optimization_draft"),
            _function_response(
                "ads_get_ad_entities",
                {"ad_account_id": "act_1", "date_preset": "last_7d", "level": "campaign", "force_refresh": True},
            ),
            _function_response(
                "ads_update_entity",
                {
                    "ad_account_id": "act_1",
                    "entity_id": "cmp_1",
                    "entity_type": "campaign",
                    "fields": {"daily_budget": 5000},
                    "evidence": "CPA doubled while spend was flat.",
                    "recommendation": "Reduce the daily budget by 20%.",
                    "risk_level": "high",
                    "current_state": {
                        "current_budget": 6250,
                        "current_status": "ACTIVE",
                        "sample_size": {"impressions": 12000},
                        "learning_state": "ACTIVE",
                        "comparison_window": "previous_7d",
                    },
                },
            ),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(mcp), max_steps=3).run_turn("Change the budget.")

    assert [call[0] for call in mcp.calls] == ["ads_get_ad_entities"]
    assert "live read did not expose current_state.sample_size" in result["trace"][2]["result"]["missing_evidence"]
    assert result["drafts"] == []


def test_write_is_staged_until_final_decision() -> None:
    llm = FakeLLM(
        [
            _skill_response("optimization_draft"),
            _function_response(
                "ads_get_ad_entities",
                {"ad_account_id": "act_1", "date_preset": "last_7d", "level": "campaign", "force_refresh": True},
            ),
            _function_response(
                "ads_update_entity",
                {
                    "ad_account_id": "act_1",
                    "entity_id": "cmp_1",
                    "entity_type": "campaign",
                    "fields": {"daily_budget": 5000},
                    "evidence": "CPA doubled while spend was flat.",
                    "recommendation": "Reduce the daily budget by 20%.",
                    "risk_level": "high",
                    "current_state": {
                        "current_budget": 6250,
                        "current_status": "ACTIVE",
                        "sample_size": {"impressions": 12000},
                        "learning_state": "ACTIVE",
                        "comparison_window": "previous_7d",
                    },
                },
            ),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(FakeMCP()), max_steps=3).run_turn("Change the budget.")

    assert result["drafts"] == []
    assert result["trace"][2]["result"]["staged_action_id"] == "staged_1"
    assert result["trace"][2]["result"]["status"] == "staged"


def test_ask_user_stops_the_loop() -> None:
    llm = FakeLLM([_function_response("ask_user", {"question": "Which account?"}, namespace="")])
    result = AgentRuntime(llm=llm, tools=_registry(FakeMCP()), max_steps=3).run_turn("Check my ads.")

    assert result["reply"] == "Which account?"
    assert result["stopped_reason"] == "ask_user"


def test_loop_stops_at_max_steps() -> None:
    response = _function_response("ads_get_ad_accounts", {}, search=False)
    result = AgentRuntime(llm=FakeLLM([_skill_response("account_brief"), response]), tools=_registry(FakeMCP()), max_steps=2).run_turn("Keep looking.")

    assert result["stopped_reason"] == "max_steps"
    assert result["steps"] == 2


def test_forbidden_execution_tool_is_rejected_by_policy() -> None:
    llm = FakeLLM(
        [
            _function_response("execute_action", {"action_id": "act_1"}, namespace=""),
            _final_response("I cannot execute account changes."),
        ]
    )
    result = AgentRuntime(llm=llm, tools=_registry(FakeMCP()), max_steps=2).run_turn("Execute it.")

    assert result["trace"][0]["result"]["error"].startswith("Execution tool is not available")
    assert result["reply"] == "I cannot execute account changes."


def test_tool_arguments_are_validated_before_mcp_call() -> None:
    mcp = FakeMCP()
    result = _registry(mcp).execute("ads_get_ad_entities", {"ad_account_id": 123})

    assert result["error"].startswith("Invalid arguments for ads_get_ad_entities")
    assert result["schema_errors"]
    assert mcp.calls == []


def test_malformed_json_arguments_fail_before_mcp_call() -> None:
    mcp = FakeMCP()
    bad_call = {
        "content": "",
        "output_items": [
            {
                "type": "function_call",
                "call_id": "call_bad_json",
                "name": "ads_get_ad_entities",
                "namespace": "meta_ads",
                "arguments": "{not valid json",
            }
        ],
        "tool_calls": [
            {
                "id": "call_bad_json",
                "name": "ads_get_ad_entities",
                "namespace": "meta_ads",
                "arguments": "{not valid json",
            }
        ],
    }
    result = AgentRuntime(
        llm=FakeLLM([_skill_response("account_brief"), bad_call]),
        tools=_registry(mcp),
        max_steps=2,
    ).run_turn("Read the account.")

    assert mcp.calls == []
    assert "Invalid JSON arguments" in result["trace"][1]["result"]["error"]


def test_missing_required_tool_argument_is_rejected_before_mcp_call() -> None:
    mcp = FakeMCP()
    result = _registry(mcp).execute("ads_get_ad_entities", {})

    assert result["error"].startswith("Invalid arguments for ads_get_ad_entities")
    assert any("ad_account_id" in item for item in result["schema_errors"])
    assert mcp.calls == []


def test_registry_caps_large_read_results() -> None:
    class HugeMCP(FakeMCP):
        def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
            return "x" * (MAX_GENERAL_RESULT_CHARS * 2)

    result = _registry(HugeMCP()).execute("ads_get_ad_accounts", {})
    assert result["truncated"] is True
    assert result["original_chars"] > MAX_GENERAL_RESULT_CHARS


def test_agent_turn_route_returns_react_envelope(monkeypatch) -> None:
    import backend.routes.agent_routes as agent_handler

    class FakeExecution:
        def __init__(self, **_kwargs):
            pass

        def prepare(self):
            return self

        def execute(self):
            return {
                "reply": "Readable accounts are available.",
                "trace": [{"step": 1, "tool": "meta_ads.get_ad_accounts", "arguments": {}, "result": {"count": 1}}],
                "visible_agent_steps": [{"agent": "Agent", "title": "调用 meta_ads.get_ad_accounts", "status": "completed", "detail": "count=1"}],
                "drafts": [],
                "tool_calls": ["meta_ads.get_ad_accounts"],
                "steps": 1,
                "stopped_reason": "final",
                "intent_type": "read_data",
                "presentation_mode": "dashboard",
                "runtime": "react",
                "context_manifest": {"recent_rounds_limit": 5},
                "task_state": {"task_id": "task_test"},
                "user_message_id": "msg_user",
                "assistant_message_id": "msg_assistant",
                "turn_id": "turn_test",
            }

        def record_failure(self, _code):
            return

    class FakeTurnService:
        def begin(self, **_kwargs):
            return "turn_test", None

        def complete(self, _turn_id, _response):
            return

        def fail(self, *_args, **_kwargs):
            return

        def release(self, **_kwargs):
            return

    monkeypatch.setattr(agent_handler, "AgentTurnExecution", FakeExecution)
    monkeypatch.setattr(agent_handler, "TurnControlService", lambda: FakeTurnService())
    monkeypatch.setattr(agent_handler, "get_or_create_session", lambda _session_id: ("test-agent-turn", {}))
    client = TestClient(app)
    response = client.post("/api/agent/turn", json={"message": "Which accounts are readable?", "session_id": "test-agent-turn"})
    payload = response.json()

    assert response.status_code == 200
    assert payload["reply"] == "Readable accounts are available."
    assert payload["runtime"] == "react"
    assert "get_ad_accounts" in payload["visible_agent_steps"][0]["title"]
    assert payload["intent_type"] == "read_data"
    assert payload["presentation_mode"] == "dashboard"
    assert payload["turn_id"] == "turn_test"
    assert "workflow_id" not in payload
    assert "agent_plan" not in payload


def test_openai_responses_client_passes_reasoning_and_maps_tool_calls(monkeypatch) -> None:
    import backend.agent.runtime as runtime_module

    captured: dict[str, Any] = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            call = SimpleNamespace(
                type="function_call",
                call_id="call_1",
                name="ads_get_ad_accounts",
                namespace="meta_ads",
                arguments="{}",
                model_dump=lambda **_: {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "ads_get_ad_accounts",
                    "namespace": "meta_ads",
                    "arguments": "{}",
                },
            )
            return SimpleNamespace(output_text="", output=[call])

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    client = runtime_module.OpenAIResponsesClient(api_key="test-key", model="gpt-6-luna", reasoning_effort="high")
    result = client.complete(
        "policy",
        [{"role": "user", "content": "hello"}],
        [
            {
                "type": "namespace",
                "name": "meta_ads",
                "tools": [{"type": "function", "name": "ads_get_ad_accounts", "parameters": {"type": "object"}, "defer_loading": True}],
            },
            {"type": "tool_search"},
        ],
    )

    assert captured["reasoning"] == {"effort": "high"}
    assert captured["model"] == "gpt-6-luna"
    assert captured["store"] is False
    assert captured["tools"][0]["type"] == "namespace"
    assert captured["tools"][0]["tools"][0]["defer_loading"] is True
    assert result["tool_calls"][0]["name"] == "ads_get_ad_accounts"
    assert result["tool_calls"][0]["namespace"] == "meta_ads"

def test_media_results_have_a_tighter_budget() -> None:
    class HugeMediaMCP(FakeMCP):
        def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
            return "video metadata " + "x" * 20000

    result = _registry(HugeMediaMCP()).execute("ads_get_ad_videos", {"ad_account_id": "act_1"})
    assert result["truncated"] is True
    assert result["original_chars"] > 4000
    assert len(result.get("preview", "")) < 4200

def _official_tool_definitions() -> list[dict[str, Any]]:
    names = (
        "ads_get_ad_accounts",
        "ads_get_ad_entities",
        "ads_insights_performance_trend",
        "ads_create_campaign",
        "ads_update_entity",
        "ads_delete_custom_audience",
        "ads_log_ui_interaction",
        "ads_get_ad_preview_screenshot",
    )
    return [
        {
            "name": name,
            "description": f"Official tool {name}",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ad_account_id": {"type": "string"},
                    "entity_id": {"type": "string"},
                    "entity_type": {"type": "string"},
                    "client_conversation_id": {"type": "string"},
                    "advertiser_request": {"type": "string"},
                    "advertiser_job": {"type": "string"},
                },
                "required": [],
            },
        }
        for name in names
    ]


def test_official_tool_schemas_hide_runtime_metadata_and_ignored_tools() -> None:
    registry = MetaToolRegistry(mcp_client=FakeMCP(), tool_definitions=_official_tool_definitions())
    schemas = registry.schemas()
    names = {tool["name"] for tool in schemas[0]["tools"]}

    assert "ads_get_ad_entities" in names
    assert "ads_create_campaign" in names
    assert "ads_log_ui_interaction" not in names
    assert "ads_get_ad_preview_screenshot" not in names
    account_tool = next(tool for tool in schemas[0]["tools"] if tool["name"] == "ads_get_ad_accounts")
    assert "client_conversation_id" not in account_tool["parameters"]["properties"]
    write_tool = next(tool for tool in schemas[0]["tools"] if tool["name"] == "ads_create_campaign")
    assert {"evidence", "recommendation", "risk_level", "current_state"}.issubset(set(write_tool["parameters"]["required"]))


def test_official_read_injects_metadata_and_official_write_stays_local() -> None:
    mcp = FakeMCP()
    captured: dict[str, Any] = {}

    def create_draft(request):
        captured["request"] = request
        return SimpleNamespace(id="draft_official", status="draft")

    def create_action(draft):
        return SimpleNamespace(id="act_official", status="draft_created")

    registry = MetaToolRegistry(
        mcp_client=mcp,
        tool_definitions=_official_tool_definitions(),
        draft_creator=create_draft,
        action_creator=create_action,
        preflight_runner=lambda action_id: {"preflight": {"result": "allowed"}},
    )
    mcp.injects_access_token_argument = False
    registry.set_context("act_123", "Reduce the campaign budget")
    read_result = registry.execute("ads_get_ad_accounts", {})
    assert read_result["tool"] == "ads_get_ad_accounts"
    call_args = mcp.calls[-1][1]
    assert call_args["client_conversation_id"]
    assert call_args["advertiser_request"] == "Reduce the campaign budget"
    assert "access_token" not in call_args

    before = len(mcp.calls)
    draft = registry.execute(
        "ads_update_entity",
        {
            "ad_account_id": "act_123",
            "entity_id": "cmp_1",
            "entity_type": "campaign",
            "fields": '{"daily_budget":5000}',
            "evidence": "CPA rose while spend stayed flat.",
            "recommendation": "Reduce the budget by 20%.",
            "risk_level": "high",
            "current_state": {"status": "ACTIVE"},
        },
    )
    assert len(mcp.calls) == before
    assert draft["draft_id"] == "draft_official"
    assert captured["request"].action["action_type"] == "ads_update_entity"
    assert captured["request"].action["target_id"] == "cmp_1"

def test_read_tool_call_hard_timeout_is_bounded_and_later_calls_fail_fast() -> None:
    release = Event()

    class SlowMCP(FakeMCP):
        def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
            self.calls.append((name, dict(arguments or {})))
            release.wait(1.5)
            return {"data": []}

    mcp = SlowMCP()
    registry = _registry(mcp)
    registry.set_deadline(time.monotonic() + 0.15)
    started = time.monotonic()
    result = registry.execute("ads_get_ad_accounts", {})
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert "deadline" in result["error"]
    second = registry.execute("ads_get_ad_accounts", {})
    assert "later MCP calls are skipped" in second["error"]
    assert len(mcp.calls) == 1
    release.set()


def test_direct_draft_hard_timeout_is_logged_as_failure(monkeypatch) -> None:
    monkeypatch.setenv("META_DRAFT_WRITE_ENABLED", "true")
    release = Event()

    class SlowMCP(FakeMCP):
        def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
            self.calls.append((name, dict(arguments or {})))
            release.wait(1.5)
            return {"data": []}

    logged: list[dict[str, Any]] = []
    registry = MetaToolRegistry(
        mcp_client=SlowMCP(),
        tool_definitions=_official_tool_definitions(),
        direct_draft_logger=logged.append,
    )
    registry.set_context("act_123", "Create a paused campaign draft")
    registry.set_deadline(time.monotonic() + 0.15)
    result = registry.create_paused_draft(
        "ads_create_campaign",
        {
            "ad_account_id": "act_123",
            "campaign_name": "Paused E2E Draft",
            "objective": "OUTCOME_TRAFFIC",
            "buying_type": "AUCTION",
            "evidence": "User requested a new traffic campaign draft.",
            "recommendation": "Create the campaign in PAUSED state only.",
            "risk_level": "low",
            "current_state": {"account_status": "ACTIVE"},
        },
    )

    assert result["created"] is False
    assert "deadline" in result["error"]
    assert logged[0]["created"] is False
    release.set()


def test_agent_turn_route_replays_completed_idempotent_turn(monkeypatch) -> None:
    import backend.routes.agent_routes as agent_handler

    class FakeTurnService:
        def begin(self, **_kwargs):
            return "turn_cached", {
                "session_id": "s1",
                "reply": "cached reply",
                "trace": [],
                "drafts": [],
                "runtime": "react",
            }

    monkeypatch.setattr(agent_handler, "get_or_create_session", lambda _session_id: ("s1", {}))
    monkeypatch.setattr(agent_handler, "TurnControlService", lambda: FakeTurnService())
    client = TestClient(app)
    response = client.post(
        "/api/agent/turn",
        json={"message": "hello", "session_id": "s1", "idempotency_key": "key_1"},
    )

    assert response.status_code == 200
    assert response.json()["reply"] == "cached reply"
    assert response.json()["idempotent_replay"] is True


def test_agent_turn_route_returns_409_when_session_turn_is_active(monkeypatch) -> None:
    import backend.routes.agent_routes as agent_handler
    from backend.services.turn_control import TurnConflictError

    class FakeTurnService:
        def begin(self, **_kwargs):
            raise TurnConflictError("turn_already_in_progress", "Another turn is active.")

    monkeypatch.setattr(agent_handler, "get_or_create_session", lambda _session_id: ("s1", {}))
    monkeypatch.setattr(agent_handler, "TurnControlService", lambda: FakeTurnService())
    client = TestClient(app)
    response = client.post(
        "/api/agent/turn",
        json={"message": "hello", "session_id": "s1", "idempotency_key": "key_1"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "turn_already_in_progress"

def test_direct_paused_draft_creation_calls_mcp_without_activation(monkeypatch) -> None:
    monkeypatch.setenv("META_DRAFT_WRITE_ENABLED", "true")
    mcp = FakeMCP()
    logged: list[dict[str, Any]] = []
    registry = MetaToolRegistry(
        mcp_client=mcp,
        tool_definitions=_official_tool_definitions(),
        direct_draft_logger=logged.append,
    )
    registry.set_context("act_123", "Create a paused campaign draft")

    result = registry.create_paused_draft(
        "ads_create_campaign",
        {
            "ad_account_id": "act_123",
            "campaign_name": "Paused E2E Draft",
            "objective": "OUTCOME_TRAFFIC",
            "buying_type": "AUCTION",
            "evidence": "User requested a new traffic campaign draft.",
            "recommendation": "Create the campaign in PAUSED state only.",
            "risk_level": "low",
            "current_state": {"account_status": "ACTIVE"},
            "status": "ACTIVE",
            "publish_as_active": True,
        },
    )

    assert result["created"] is True
    assert result["published"] is False
    assert result["status"] == "DRAFT"
    assert mcp.calls[0][0] == "ads_create_campaign"
    sent = mcp.calls[0][1]
    assert "status" not in sent
    assert "publish_as_active" not in sent
    assert "evidence" not in sent
    assert "current_state" not in sent
    assert logged[0]["created"] is True


def test_activation_and_publish_tools_are_not_exposed_or_allowed() -> None:
    registry = MetaToolRegistry(mcp_client=FakeMCP(), tool_definitions=_official_tool_definitions())
    names = {tool["name"] for tool in registry.schemas()[0]["tools"]}

    assert is_forbidden_publish_tool("ads_activate_entity") is True
    assert "ads_activate_entity" not in names

def test_runtime_records_direct_meta_draft_without_local_staging(monkeypatch) -> None:
    monkeypatch.setenv("META_DRAFT_WRITE_ENABLED", "true")
    mcp = FakeMCP()
    llm = FakeLLM(
        [
            _skill_response("campaign_plan"),
            _function_response("ads_get_ad_accounts", {"limit": 3, "force_refresh": True}, search=True),
            _function_response(
                "ads_create_campaign",
                {
                    "ad_account_id": "act_1",
                    "campaign_name": "Paused Draft E2E",
                    "objective": "OUTCOME_TRAFFIC",
                    "buying_type": "AUCTION",
                    "evidence": "The user requested a paused traffic campaign draft.",
                    "recommendation": "Create only a non-live Draft campaign.",
                    "risk_level": "low",
                    "current_state": {"account_status": "ACTIVE"},
                },
            ),
            _submit_response(
                {
                    "plan": {"summary": "Create one non-live campaign Draft."},
                    "assumptions": [],
                    "missing_data": [],
                    "draft_request": {"campaign_name": "Paused Draft E2E"},
                    "source_tools": ["ads_get_ad_accounts"],
                },
                "Draft campaign created in non-live Draft Mode.",
            ),
        ]
    )
    registry = MetaToolRegistry(
        mcp_client=mcp,
        tool_definitions=_official_tool_definitions(),
        direct_draft_logger=lambda _event: None,
    )
    result = AgentRuntime(llm=llm, tools=registry, max_steps=5).run_turn(
        "Create a paused traffic campaign draft.",
        account_id="act_1",
        draft_creation_authorized=True,
    )

    assert len(result["direct_drafts"]) == 1
    assert result["drafts"] == []
    assert result["direct_drafts"][0]["published"] is False
    assert result["direct_drafts"][0]["status"] == "DRAFT"
    assert [name for name, _ in mcp.calls] == ["ads_get_ad_accounts", "ads_create_campaign"]

def test_direct_draft_provider_error_is_not_reported_as_created(monkeypatch) -> None:
    monkeypatch.setenv("META_DRAFT_WRITE_ENABLED", "true")

    class ValidationMCP(FakeMCP):
        def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
            return {"error_category": "VALIDATION", "error_message": "creative is required", "is_retryable": False}

    logged: list[dict[str, Any]] = []
    registry = MetaToolRegistry(
        mcp_client=ValidationMCP(),
        tool_definitions=_official_tool_definitions(),
        direct_draft_logger=logged.append,
    )
    result = registry.create_paused_draft(
        "ads_create_campaign",
        {
            "ad_account_id": "act_123",
            "campaign_name": "Invalid Draft",
            "objective": "OUTCOME_TRAFFIC",
            "buying_type": "AUCTION",
            "evidence": "Evidence.",
            "recommendation": "Create a Draft.",
            "risk_level": "low",
            "current_state": {"account_status": "ACTIVE"},
        },
    )

    assert result["created"] is False
    assert result["status"] == "FAILED"
    assert "creative is required" in result["error"]
    assert logged[0]["created"] is False


def test_draft_readback_ids_unlock_child_draft_creation() -> None:
    state = AgentState(message="create draft hierarchy", account_id="act_1")
    campaign_evidence = _build_live_read_evidence(
        "ads_get_ad_entities",
        {"ad_account_id": "act_1", "level": "campaign", "object_state": "draft", "force_refresh": True},
        {
            "tool": "ads_get_ad_entities",
            "result": {
                "ad_drafts": [
                    {
                        "ad_object_id": "campaign_draft_1",
                        "ad_object_type": "campaign",
                        "status": "EDITING",
                        "validation_status": "VALIDATED",
                        "action": "add",
                    }
                ]
            },
        },
        "act_1",
    )
    state.live_read_evidence.append(campaign_evidence)

    assert "campaign_draft_1" in campaign_evidence["target_ids"]
    assert _draft_evidence_errors(
        "ads_create_ad_set",
        {
            "ad_account_id": "act_1",
            "campaign_id": "campaign_draft_1",
            "current_state": {"campaign_draft_status": "EDITING"},
        },
        state,
    ) == []

    adset_evidence = _build_live_read_evidence(
        "ads_get_ad_entities",
        {"ad_account_id": "act_1", "level": "adset", "object_state": "draft", "force_refresh": True},
        {
            "tool": "ads_get_ad_entities",
            "result": {
                "ad_drafts": [
                    {
                        "ad_object_id": "adset_draft_1",
                        "parent_ad_object_id": "campaign_draft_1",
                        "ad_object_type": "adset",
                        "status": "EDITING",
                        "validation_status": "VALIDATED",
                        "action": "add",
                    }
                ]
            },
        },
        "act_1",
    )
    state.live_read_evidence.append(adset_evidence)

    assert {"adset_draft_1", "campaign_draft_1"}.issubset(set(adset_evidence["target_ids"]))
    assert _draft_evidence_errors(
        "ads_create_ad",
        {
            "ad_account_id": "act_1",
            "adset_id": "adset_draft_1",
            "current_state": {"adset_draft_status": "EDITING"},
        },
        state,
    ) == []


def test_draft_mutation_requires_draft_readback_and_rejects_live_target() -> None:
    state = AgentState(message="delete draft", account_id="act_1")
    live_evidence = _build_live_read_evidence(
        "ads_get_ad_entities",
        {"ad_account_id": "act_1", "level": "campaign", "force_refresh": True},
        {"tool": "ads_get_ad_entities", "result": {"ad_entities": [{"id": "cmp_1", "effective_status": "ACTIVE"}]}},
        "act_1",
    )
    state.live_read_evidence.append(live_evidence)

    assert _draft_mutation_evidence_errors(
        "ads_update_entity",
        {"ad_account_id": "act_1", "entity_id": "cmp_1", "entity_type": "campaign", "draft_only": True},
        state,
    )

    draft_evidence = _build_live_read_evidence(
        "ads_get_ad_entities",
        {"ad_account_id": "act_1", "level": "campaign", "object_state": "draft", "force_refresh": True},
        {"tool": "ads_get_ad_entities", "result": {"ad_drafts": [{"ad_object_id": "cmp_1", "status": "EDITING", "validation_status": "VALIDATED"}]}},
        "act_1",
    )
    state.live_read_evidence.append(draft_evidence)

    assert _draft_mutation_evidence_errors(
        "ads_update_entity",
        {"ad_account_id": "act_1", "entity_id": "cmp_1", "entity_type": "campaign", "draft_only": True},
        state,
    ) == []


def test_direct_draft_delete_uses_mcp_and_never_marks_published(monkeypatch) -> None:
    monkeypatch.setenv("META_DRAFT_WRITE_ENABLED", "true")
    mcp = FakeMCP()
    logged: list[dict[str, Any]] = []
    registry = MetaToolRegistry(
        mcp_client=mcp,
        tool_definitions=_tool_definitions(),
        direct_draft_logger=lambda event: logged.append(event),
    )
    registry.set_context("act_1", "Delete draft")

    result = registry.mutate_draft(
        "ads_update_entity",
        {
            "ad_account_id": "act_1",
            "entity_id": "cmp_draft_1",
            "entity_type": "campaign",
            "fields": {"status": "DELETED"},
            "evidence": "Draft read returned EDITING/VALIDATED.",
            "recommendation": "Delete the abandoned draft.",
            "risk_level": "low",
            "current_state": {"draft_status": "EDITING"},
            "draft_only": True,
        },
    )

    assert result["deleted"] is True
    assert result["published"] is False
    assert mcp.calls[0][0] == "ads_update_entity"
    assert "draft_only" not in mcp.calls[0][1]
    assert logged[0]["operation"] == "deleted"


def test_direct_draft_creation_is_blocked_without_explicit_confirmation(monkeypatch) -> None:
    monkeypatch.setenv("META_DRAFT_WRITE_ENABLED", "true")
    mcp = FakeMCP()
    llm = FakeLLM(
        [
            _skill_response("campaign_plan"),
            _function_response("ads_get_ad_accounts", {"limit": 3, "force_refresh": True}, search=True),
            _function_response(
                "ads_create_campaign",
                {
                    "ad_account_id": "act_1",
                    "campaign_name": "Unconfirmed Draft",
                    "objective": "OUTCOME_TRAFFIC",
                    "buying_type": "AUCTION",
                    "evidence": "Plan was prepared.",
                    "recommendation": "Create the draft.",
                    "risk_level": "low",
                    "current_state": {"account_status": "ACTIVE"},
                },
            ),
        ]
    )
    registry = MetaToolRegistry(
        mcp_client=mcp,
        tool_definitions=_official_tool_definitions(),
        direct_draft_logger=lambda _event: None,
    )
    result = AgentRuntime(llm=llm, tools=registry, max_steps=3).run_turn(
        "Create a new campaign draft.",
        account_id="act_1",
        draft_creation_authorized=False,
    )

    assert result["direct_drafts"] == []
    create_trace = next(item for item in result["trace"] if item["tool"] == "meta_ads.ads_create_campaign")
    assert create_trace["result"]["confirmation_required"] is True
    assert create_trace["result"]["confirmation_phrase"] == "确认创建草稿"
    assert [name for name, _ in mcp.calls] == ["ads_get_ad_accounts"]


def test_draft_confirmation_phrase_is_explicit() -> None:
    from backend.services.agent_turn_service import is_explicit_draft_confirmation

    assert is_explicit_draft_confirmation("确认创建草稿") is True
    assert is_explicit_draft_confirmation("确认创建草稿，请继续") is True
    assert is_explicit_draft_confirmation("confirm create draft") is True
    assert is_explicit_draft_confirmation("好的") is False


def test_direct_draft_delete_with_active_errors_is_not_success(monkeypatch) -> None:
    monkeypatch.setenv("META_DRAFT_WRITE_ENABLED", "true")

    class ActiveErrorMCP(FakeMCP):
        def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
            self.calls.append((name, dict(arguments or {})))
            return {
                "success": True,
                "entity_id": "cmp_draft_1",
                "is_draft": True,
                "active_errors": json.dumps([
                    {"error_code": 1487564, "error_type": "AD_DRAFT_PUBLISHING", "error_description": "new campaign must be ACTIVE or PAUSED"}
                ]),
            }

    logged: list[dict[str, Any]] = []
    registry = MetaToolRegistry(
        mcp_client=ActiveErrorMCP(),
        tool_definitions=_tool_definitions(),
        direct_draft_logger=logged.append,
    )
    result = registry.mutate_draft(
        "ads_update_entity",
        {
            "ad_account_id": "act_1",
            "entity_id": "cmp_draft_1",
            "entity_type": "campaign",
            "fields": {"status": "DELETED"},
            "evidence": "Draft read returned EDITING/VALIDATED.",
            "recommendation": "Delete the abandoned draft.",
            "risk_level": "medium",
            "current_state": {"draft_status": "EDITING"},
            "draft_only": True,
        },
    )

    assert result["status"] == "FAILED"
    assert result["published"] is False
    assert "1487564" in result["error"]
    assert logged[0]["created"] is False
