from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.agent.context import ContextAssembler, compact_tool_outputs, split_recent_rounds
from backend.agent.runtime import AgentRuntime
from backend.agent.skills import SkillCatalog
from backend.agent.state import AgentState
from backend.agent.tools import MetaToolRegistry
from backend.services.account_cache import AccountCacheService, MCPToolResultCache, build_account_context
from backend.services.long_term_memory import LongTermMemoryService
from backend.services.task_state import TaskStateService
from backend.repositories.memory_repository import _memory_visibility_clause
from sqlalchemy.dialects import postgresql
import backend.services.session_store as session_store


class FakeLLM:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]] = []

    def complete(self, instructions: str, input_items: list[dict[str, Any]], tools: list[dict[str, Any]], **_kwargs: Any) -> dict[str, Any]:
        self.calls.append((instructions, input_items, tools))
        return self.responses.pop(0)


class MinimalTools:
    def __init__(self) -> None:
        self.selected_account_id = ""
        self.tools_by_name: dict[str, dict[str, Any]] = {}

    def set_context(self, account_id: str = "", request_text: str = "") -> None:
        self.selected_account_id = account_id

    def set_advertiser_job(self, _job: str) -> None:
        return

    def schemas(self) -> list[dict[str, Any]]:
        return []

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"tool": name, "result": {"ok": True}}

    def stage_write(self, _name: str, _arguments: dict[str, Any]) -> dict[str, Any]:
        return {"error": "not used"}

    def commit_staged_action(self, _staged: dict[str, Any]) -> dict[str, Any]:
        return {"error": "not used"}


def _final(text: str) -> dict[str, Any]:
    return {"content": text, "output_items": [{"type": "message", "role": "assistant", "content": text}], "tool_calls": []}


def _call(name: str, arguments: dict[str, Any], namespace: str = "") -> dict[str, Any]:
    return {
        "content": "",
        "output_items": [
            {
                "type": "function_call",
                "call_id": f"call_{name}",
                "name": name,
                "namespace": namespace,
                "arguments": json.dumps(arguments),
            }
        ],
        "tool_calls": [{"id": f"call_{name}", "name": name, "namespace": namespace, "arguments": json.dumps(arguments)}],
    }


def test_five_round_window_summarizes_older_messages() -> None:
    history = []
    for index in range(6):
        history.append({"id": f"u{index}", "role": "user", "content": f"goal {index}"})
        history.append({"id": f"a{index}", "role": "assistant", "content": f"answer {index}"})
    summary_payload = json.dumps(
        {
            "current_goal": "goal 0",
            "constraints": ["keep budget"],
            "confirmed_decisions": ["hold campaign"],
            "open_questions": [],
            "completed_work": ["reviewed account"],
            "account_refs": ["act_1"],
            "source_message_ids": ["u0", "a0"],
        }
    )
    llm = FakeLLM(
        [
            {"content": summary_payload, "output_items": [], "tool_calls": []},
            _final("Next answer."),
        ]
    )

    result = AgentRuntime(llm=llm, tools=MinimalTools(), max_steps=2).run_turn(
        "next question",
        history=history,
        account_id="act_1",
    )

    assert len(llm.calls) == 2
    assert result["summary_update"]["current_goal"] == "goal 0"
    assert result["context_manifest"]["recent_rounds_limit"] == 5
    assert result["context_manifest"]["recent_message_count"] == 10
    main_history = llm.calls[1][1]
    assert main_history[0]["content"] == "goal 1"
    assert main_history[10]["content"] == "next question"
    assert all(item.get("content") != "goal 0" for item in main_history)
    assert "Earlier conversation summary" in llm.calls[1][0]


def test_memory_and_task_tools_emit_persistable_updates() -> None:
    llm = FakeLLM(
        [
            _call(
                "save_memory",
                {
                    "kind": "preference",
                    "scope": "user",
                    "content": "回答先给结论",
                    "confidence": 0.95,
                    "source_quote": "以后回答先给结论",
                },
            ),
            _call(
                "update_task",
                {
                    "goal": "降低 CPA",
                    "completed_steps": ["读取近 7 天数据"],
                    "next_step": "检查 Learning 状态",
                    "constraints": ["不自动执行"],
                },
            ),
            _final("完成。"),
        ]
    )

    result = AgentRuntime(llm=llm, tools=MinimalTools(), max_steps=4).run_turn(
        "以后回答先给结论，帮我降低 CPA",
        account_id="act_1",
        session_id="session_1",
        task_id="task_1",
        user_message_id="msg_1",
    )

    assert result["memory_writes"][0]["kind"] == "preference"
    assert result["memory_writes"][0]["source_text"].startswith("以后回答先给结论")
    assert result["task_update"]["goal"] == "降低 CPA"
    assert result["task_update"]["next_step"] == "检查 Learning 状态"
    schema_names = {tool.get("name") for tool in llm.calls[0][2]}
    assert {"save_memory", "update_task"}.issubset(schema_names)


class FakeMCP:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self.calls.append((name, dict(arguments or {})))
        return {"ad_accounts": [{"ad_account_id": "1", "ad_account_name": "Account One"}]}


class MemoryCacheRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def get_tool_result(self, cache_key: str) -> dict[str, Any] | None:
        return self.rows.get(cache_key)

    def save_tool_result(self, **kwargs: Any) -> None:
        now = kwargs["fetched_at"]
        self.rows[kwargs["cache_key"]] = {
            "cache_key": kwargs["cache_key"],
            "result_json": kwargs["result"],
            "fetched_at": now.isoformat(),
            "expires_at": kwargs["expires_at"].isoformat(),
        }


def test_cached_tool_result_avoids_second_mcp_call() -> None:
    mcp = FakeMCP()
    cache = MCPToolResultCache(repository=MemoryCacheRepository())
    registry = MetaToolRegistry(
        mcp_client=mcp,
        tool_definitions=[
            {
                "name": "ads_get_ad_accounts",
                "description": "Accounts",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer"},
                        "client_conversation_id": {"type": "string"},
                        "advertiser_request": {"type": "string"},
                        "advertiser_job": {"type": "string"},
                    },
                },
            }
        ],
        result_cache=cache,
    )

    registry.set_context("act_1", "first request")
    first = registry.execute("ads_get_ad_accounts", {"limit": 3})
    registry.set_context("act_1", "second request")
    second = registry.execute("ads_get_ad_accounts", {"limit": 3})
    registry.execute("ads_get_ad_accounts", {"limit": 3, "force_refresh": True})

    assert len(mcp.calls) == 2
    assert first["tool"] == "ads_get_ad_accounts"
    assert second["_cache"]["hit"] is True
    assert second["_cache"]["fresh"] is True


def test_account_context_is_compact_and_metric_aware() -> None:
    context = build_account_context(
        "act_1",
        {
            "account": {"name": "Main", "currency": "USD", "timezone_name": "America/Los_Angeles"},
            "date_preset": "last_7d",
            "campaigns": [
                {"id": "c1", "effective_status": "ACTIVE"},
                {"id": "c2", "effective_status": "PAUSED"},
            ],
            "insights": [
                {"name": "Campaign A", "spend": "100", "impressions": "1000", "clicks": "20", "results": "4", "cost_per_result": "25"}
            ],
        },
    )

    assert context["name"] == "Main"
    assert context["entity_counts"]["campaigns"] == 2
    assert context["entity_counts"]["active_campaigns"] == 1
    assert context["totals"]["cpa"] == 25
    assert context["attention"][0]["name"] == "Campaign A"
    assert context["missing_data"] == []


class FakeMemoryRepository:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []
        self.rows: list[dict[str, Any]] = []

    def remember(self, **kwargs: Any) -> dict[str, Any]:
        self.saved.append(kwargs)
        row = {"id": f"mem_{len(self.saved)}", **kwargs, "updated_at": "2026-10-18T00:00:00+00:00"}
        self.rows.append(row)
        return row

    def list_memories(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return list(self.rows)

    def delete(self, **_kwargs: Any) -> bool:
        return True

    def update_candidate_status(self, *, user_id: str, memory_id: str, status: str) -> bool:
        for row in self.rows:
            if row.get("id") == memory_id and row.get("status") == "candidate":
                row["status"] = status
                return True
        return False


def test_memory_scope_and_explicit_quote_status() -> None:
    repository = FakeMemoryRepository()
    service = LongTermMemoryService(repository=repository)
    writes = [
        {
            "kind": "preference",
            "scope": "user",
            "content": "回答先给结论",
            "confidence": 0.9,
            "source_quote": "以后先给结论",
            "source_text": "以后先给结论",
            "source_role": "user",
        },
        {
            "kind": "habit",
            "scope": "account",
            "content": "偏好周五复盘",
            "confidence": 0.6,
            "source_quote": "",
            "source_text": "",
        },
    ]

    saved = service.remember_many(
        writes,
        user_id="local_user",
        account_id="act_1",
        session_id="s1",
        user_message_id="m1",
    )

    assert saved[0]["status"] == "active"
    assert saved[1]["status"] == "candidate"
    assert repository.saved[0]["scope_id"] == "local_user"
    assert repository.saved[1]["scope_id"] == "act_1"
    assert repository.saved[0]["source_message_id"] == "m1"


def test_memory_recall_uses_query_and_excludes_candidates() -> None:
    repository = FakeMemoryRepository()
    repository.rows = [
        {
            "id": "mem_relevant",
            "kind": "decision",
            "content": "CPA 上升时不要自动增加预算",
            "confidence": 0.9,
            "status": "active",
            "updated_at": "2026-10-17T00:00:00+00:00",
        },
        {
            "id": "mem_preference",
            "kind": "preference",
            "content": "回答先给结论",
            "confidence": 0.95,
            "status": "active",
            "updated_at": "2026-10-17T00:00:00+00:00",
        },
        {
            "id": "mem_candidate",
            "kind": "decision",
            "content": "CPA 上升时立即增加预算",
            "confidence": 0.99,
            "status": "candidate",
            "updated_at": "2026-10-18T00:00:00+00:00",
        },
    ]
    service = LongTermMemoryService(repository=repository)

    selected = service.context_for(
        user_id="local_user",
        account_id="act_1",
        query="CPA 上升以后是否增加预算？",
        task_state={"goal": "诊断 CPA 变化"},
        now=datetime(2026, 10, 18, tzinfo=timezone.utc),
    )

    assert selected[0]["id"] == "mem_relevant"
    assert "mem_candidate" not in {row["id"] for row in selected}


def test_memory_recall_prefers_recent_outcome_when_relevance_is_equal() -> None:
    repository = FakeMemoryRepository()
    repository.rows = [
        {
            "id": "mem_old",
            "kind": "outcome",
            "content": "CPA increased",
            "confidence": 0.9,
            "status": "active",
            "updated_at": "2025-01-01T00:00:00+00:00",
        },
        {
            "id": "mem_new",
            "kind": "outcome",
            "content": "CPA increased",
            "confidence": 0.9,
            "status": "active",
            "updated_at": "2026-10-17T00:00:00+00:00",
        },
    ]
    service = LongTermMemoryService(repository=repository)

    selected = service.context_for(
        user_id="local_user",
        query="CPA",
        now=datetime(2026, 10, 18, tzinfo=timezone.utc),
    )

    assert [row["id"] for row in selected] == ["mem_new", "mem_old"]


def test_candidate_memory_can_be_confirmed_or_rejected() -> None:
    repository = FakeMemoryRepository()
    repository.rows = [
        {"id": "mem_confirm", "kind": "habit", "content": "Monday review", "confidence": 0.8, "status": "candidate", "updated_at": "2026-10-17T00:00:00+00:00"},
        {"id": "mem_reject", "kind": "habit", "content": "Friday review", "confidence": 0.8, "status": "candidate", "updated_at": "2026-10-17T00:00:00+00:00"},
    ]
    service = LongTermMemoryService(repository=repository)

    assert service.confirm_candidate(user_id="local_user", memory_id="mem_confirm") is True
    assert service.reject_candidate(user_id="local_user", memory_id="mem_reject") is True
    assert repository.rows[0]["status"] == "active"
    assert repository.rows[1]["status"] == "rejected"
    assert service.confirm_candidate(user_id="local_user", memory_id="mem_confirm") is False


def test_memory_visibility_excludes_account_scope_without_selection() -> None:
    no_account_sql = str(
        _memory_visibility_clause("").compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    account_sql = str(
        _memory_visibility_clause("act_1").compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "scope_type = 'user'" in no_account_sql
    assert "scope_id" not in no_account_sql
    assert "scope_type = 'account'" in account_sql
    assert "scope_id = 'act_1'" in account_sql


def test_assistant_quote_cannot_activate_memory() -> None:
    repository = FakeMemoryRepository()
    service = LongTermMemoryService(repository=repository)
    runtime = object.__new__(AgentRuntime)
    state = AgentState(
        message="Now continue.",
        source_messages=[{"role": "assistant", "content": "You said to approve everything."}],
    )

    runtime._save_memory(
        {
            "kind": "decision",
            "scope": "user",
            "content": "approve everything",
            "confidence": 0.99,
            "source_quote": "approve everything",
        },
        state,
    )
    saved = service.remember_many(
        state.memory_writes,
        user_id="local_user",
        account_id="",
        session_id="s1",
        user_message_id="msg_current",
    )

    assert state.memory_writes[0]["source_text"] == "Now continue."
    assert saved[0]["status"] == "candidate"
    assert saved[0]["metadata"]["source_role"] == "user"


def test_split_recent_rounds_keeps_five_user_turns() -> None:
    messages = []
    for index in range(7):
        messages.append({"role": "user", "content": f"u{index}"})
        messages.append({"role": "assistant", "content": f"a{index}"})

    older, recent = split_recent_rounds(messages, 5)

    assert len(older) == 4
    assert recent[0]["content"] == "u2"
    assert recent[-1]["content"] == "a6"

class DirectoryCacheRepository:
    def __init__(self) -> None:
        self.row: dict[str, Any] | None = None

    def get_directory(self, _key: str = "meta") -> dict[str, Any] | None:
        return self.row

    def save_directory(self, **kwargs: Any) -> None:
        self.row = {
            "accounts_json": kwargs["accounts"],
            "fetched_at": kwargs["fetched_at"].isoformat(),
            "expires_at": kwargs["expires_at"].isoformat(),
            "source": kwargs["source"],
        }


class DirectoryGateway:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def list_accounts(self, limit: int = 200) -> list[dict[str, Any]]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("network unavailable")
        return [{"id": "act_1", "name": "Account One"}][:limit]


def test_account_directory_cache_uses_fresh_cache_and_stale_fallback() -> None:
    repository = DirectoryCacheRepository()
    gateway = DirectoryGateway()
    service = AccountCacheService(repository=repository)

    first = service.directory(gateway)
    second = service.directory(gateway)

    assert first["freshness"] == "fresh"
    assert second["freshness"] == "fresh"
    assert gateway.calls == 1

    assert repository.row is not None
    repository.row["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    failed = service.directory(DirectoryGateway(fail=True))

    assert failed["freshness"] == "stale"
    assert failed["accounts"][0]["name"] == "Account One"
    assert "network unavailable" in failed["error"]

class FakeTaskRepository:
    def __init__(self) -> None:
        self.updated: dict[str, Any] = {}

    def update(self, task_id: str, **kwargs: Any) -> dict[str, Any]:
        self.updated = {"id": task_id, **kwargs}
        return self.updated


def test_task_turn_records_progress_skills_and_structured_tool_ledger() -> None:
    repository = FakeTaskRepository()
    service = TaskStateService(repository=repository)
    task = {
        "id": "task_1",
        "account_id": "act_1",
        "goal": "diagnose CPA",
        "status": "active",
        "progress": {"turn_count": 0, "recent": []},
        "constraints": [],
        "tool_ledger": [],
        "active_skill_ids": [],
    }

    updated = service.apply_turn(
        task,
        task_update={
            "next_step": "review learning state",
            "completed_steps": ["read insights"],
            "constraints": ["no live execution"],
        },
        trace=[
            {
                "step": 1,
                "tool": "meta_ads.ads_get_ad_entities",
                "arguments": {"ad_account_id": "act_1", "level": "campaign"},
                "result": {"summary": {"count": 3}},
            }
        ],
        skills_loaded=["performance_diagnosis"],
        user_message="why did CPA rise",
        reply="Check learning state.",
        stopped_reason="final",
        turn_id="turn_1",
    )

    assert updated["progress"]["turn_count"] == 1
    assert updated["progress"]["next_step"] == "review learning state"
    assert updated["progress"]["completed_steps"] == ["read insights"]
    assert updated["active_skill_ids"] == ["performance_diagnosis"]
    assert updated["constraints"] == ["no live execution"]
    assert updated["tool_ledger"][0]["arguments"]["level"] == "campaign"

    retried = service.apply_turn(
        updated,
        task_update={"next_step": "should not double count"},
        trace=[],
        skills_loaded=[],
        user_message="why did CPA rise",
        reply="Check learning state.",
        stopped_reason="final",
        turn_id=updated["progress"]["last_turn_id"],
    )
    assert retried is updated
    assert retried["progress"]["turn_count"] == 1

def test_context_includes_full_instructions_for_active_skill() -> None:
    catalog = SkillCatalog(Path("backend/skills"))
    loaded = catalog.load("account_brief")
    package = ContextAssembler().assemble(
        base_instructions="base",
        history=[],
        summary={},
        task_state={"goal": "account brief"},
        memories=[],
        account_context={},
        active_skills=[loaded],
    )

    assert "Active project Skills for this task" in package.instructions
    assert "account_brief" in package.instructions
    assert "Read tools allowed for this skill" in package.instructions
    assert package.manifest["active_skill_ids"] == ["account_brief"]

class DedupeSessionRepository:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.append_calls = 0
        self.version = 1

    def get_message_for_turn(self, session_id: str, turn_id: str, role: str) -> dict[str, Any] | None:
        for item in self.messages:
            metadata = item.get("metadata_json") or {}
            if item["session_id"] == session_id and metadata.get("turn_id") == turn_id and item["role"] == role:
                return item
        return None

    def append_message(self, session_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> str:
        self.append_calls += 1
        message_id = f"msg_{self.append_calls}"
        self.messages.append(
            {
                "id": message_id,
                "session_id": session_id,
                "role": role,
                "content": content,
                "metadata_json": dict(metadata or {}),
                "created_at": datetime.now(timezone.utc),
            }
        )
        return message_id

    def save_state(self, _session_id: str, _state: dict[str, Any], *, expected_version: int = 1) -> int:
        assert expected_version == self.version
        self.version += 1
        return self.version


def test_message_append_is_idempotent_for_same_turn(monkeypatch) -> None:
    repository = DedupeSessionRepository()
    monkeypatch.setattr(session_store, "SessionRepository", lambda: repository)
    state = session_store.SessionState("s1", {"history": []}, version=1)

    first = session_store.append_message(state, "user", "hello", turn_id="turn_1")
    second = session_store.append_message(state, "user", "hello", turn_id="turn_1")

    assert first == second
    assert repository.append_calls == 1
    assert len(state["history"]) == 1


def test_compact_tool_outputs_keeps_results_when_under_budget() -> None:
    items = [
        {"type": "function_call_output", "call_id": f"call_{index}", "output": json.dumps({"data": ["x" * 200]})}
        for index in range(6)
    ]
    call_kinds = {f"call_{index}": "mcp" for index in range(6)}

    result = compact_tool_outputs(items, call_kinds, max_tokens=10_000)

    assert result is items


def test_compact_tool_outputs_terminates_when_preserved_results_exceed_budget() -> None:
    items = [
        {"type": "function_call_output", "call_id": f"call_{index}", "output": json.dumps({"data": "x" * 4_000})}
        for index in range(4)
    ]
    call_kinds = {f"call_{index}": "mcp" for index in range(4)}

    result = compact_tool_outputs(items, call_kinds, keep_recent_mcp=3, max_tokens=10, max_iterations=8)

    assert len(result) == len(items)
    assert json.loads(result[0]["output"])["context_compacted"] is True
    assert "Observation omitted" in json.loads(result[0]["output"])["note"]
    assert result[1:] == items[1:]


def test_task_state_carries_at_most_eight_active_skills() -> None:
    repository = FakeTaskRepository()
    service = TaskStateService(repository=repository)
    task = {
        "id": "task_1",
        "account_id": "act_1",
        "goal": "launch preparation",
        "status": "active",
        "progress": {"turn_count": 0, "recent": []},
        "constraints": [],
        "tool_ledger": [],
        "active_skill_ids": ["account_brief"],
    }

    updated = service.apply_turn(
        task,
        task_update={},
        trace=[],
        skills_loaded=["skill_2", "skill_3", "skill_4", "skill_5", "skill_6", "skill_7", "skill_8", "skill_9"],
        user_message="continue",
        reply="done",
        stopped_reason="final",
    )

    assert updated["active_skill_ids"] == ["account_brief", "skill_2", "skill_3", "skill_4", "skill_5", "skill_6", "skill_7", "skill_8"]


def test_context_preserves_instructions_for_eight_active_skills() -> None:
    catalog = SkillCatalog(Path("backend/skills"))
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
    active_skills = [catalog.load(skill_id) for skill_id in skill_ids]
    package = ContextAssembler().assemble(
        base_instructions="base",
        history=[],
        summary={},
        task_state={"goal": "launch preparation"},
        memories=[],
        account_context={},
        active_skills=active_skills,
    )

    assert package.manifest["active_skill_ids"] == skill_ids
    for skill_id in skill_ids:
        assert f"### Skill: {skill_id}" in package.instructions
