from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agent.runtime import AgentRuntime, AgentRuntimeError
from backend.agent.tools import MetaToolRegistry
from backend.services.agent_sse import SSEEncoder, stream_turn_response


TOOL_DEFINITIONS = [
    {
        "name": "ads_get_ad_accounts",
        "description": "Accounts",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    }
]


class FakeMCP:
    def list_tools(self) -> list[dict[str, Any]]:
        return TOOL_DEFINITIONS

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return {"data": [{"id": "cmp_1", "campaign_id": "cmp_1", "name": "Demo Campaign", "status": "ACTIVE", "effective_status": "ACTIVE", "daily_budget": "6250", "learning_stage_info": "ACTIVE", "impressions": 12000, "clicks": 300, "results": 40}]}


class FakeLLM:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)

    def complete(self, _instructions: str, _input_items: list[dict[str, Any]], _tools: list[dict[str, Any]], **_kwargs: Any) -> dict[str, Any]:
        return self.responses.pop(0)


def call(name: str, arguments: dict[str, Any], namespace: str = "") -> dict[str, Any]:
    call_id = f"call_{name}_{len(arguments)}"
    return {
        "content": "",
        "output_items": [
            {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "namespace": namespace,
                "arguments": json.dumps(arguments),
            }
        ],
        "tool_calls": [{"id": call_id, "name": name, "namespace": namespace, "arguments": json.dumps(arguments)}],
    }


def registry() -> MetaToolRegistry:
    return MetaToolRegistry(mcp_client=FakeMCP(), tool_definitions=TOOL_DEFINITIONS)


def test_runtime_emits_ordered_tool_lifecycle_and_validation_events() -> None:
    llm = FakeLLM(
        [
            call("load_skill", {"skill_id": "account_brief"}),
            call("ads_get_ad_accounts", {"limit": 3}, namespace="meta_ads"),
            call(
                "submit_result",
                {
                    "reply": "Account is readable.",
                    "result": {
                        "facts": ["One account was returned."],
                        "missing_data": ["No selected account."],
                        "source_tools": ["ads_get_ad_accounts"],
                    },
                },
            ),
        ]
    )
    events: list[tuple[str, dict[str, Any]]] = []
    result = AgentRuntime(llm=llm, tools=registry(), max_steps=4).run_turn(
        "Which accounts are readable?",
        account_id="act_1",
        on_event=lambda name, payload: events.append((name, payload)),
    )

    names = [name for name, _payload in events]
    assert names.count("step.started") == 3
    assert names.count("model.started") == 3
    assert names.count("model.finished") == 3
    assert names.index("model.started") > names.index("step.started")
    assert names.count("tool.started") == 3
    assert names.count("tool.finished") == 3
    assert names.index("skill.loaded") > names.index("tool.finished")
    assert names[-1] == "result.validated"
    assert result["stopped_reason"] == "final"

    started = [payload["call_id"] for name, payload in events if name == "tool.started"]
    finished = [payload["call_id"] for name, payload in events if name == "tool.finished"]
    assert started == finished
    assert events[-1][1] == {"resolved_decision": "", "skill_count": 1, "conflict_count": 0}


def test_runtime_event_arguments_redact_tokens_and_data_urls() -> None:
    llm = FakeLLM(
        [
            call(
                "update_task",
                {
                    "next_step": "review",
                    "access_token": "secret-token-value",
                    "progress": {"data_url": "data:image/png;base64,abcdef"},
                },
            ),
            {"content": "Done.", "output_items": [], "tool_calls": []},
        ]
    )
    events: list[tuple[str, dict[str, Any]]] = []
    AgentRuntime(llm=llm, tools=registry(), max_steps=2).run_turn(
        "Update the task.",
        on_event=lambda name, payload: events.append((name, payload)),
    )

    encoded = json.dumps(events, ensure_ascii=False)
    assert "secret-token-value" not in encoded
    assert "data:image/png;base64" not in encoded
    started = next(payload for name, payload in events if name == "tool.started")
    assert "access_token" not in started["arguments_summary"]
    assert "data_url" not in started["arguments_summary"]["progress"]


def _parse_events(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        if not block or block.startswith(":"):
            continue
        event_name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        if event_name and data:
            events.append((event_name, json.loads(data)))
    return events


def test_stream_response_has_headers_sequence_and_single_terminal_event() -> None:
    app = FastAPI()

    @app.get("/stream")
    def stream() -> Any:
        def worker(emit: Any) -> dict[str, Any]:
            emit("turn.started", {"session_id": "s1", "user_message_id": "m1", "task_id": "t1"})
            emit("step.started", {"step": 1, "max_steps": 3})
            emit("tool.started", {"step": 1, "call_id": "c1", "tool": "update_task", "arguments_summary": {}})
            emit("tool.finished", {"step": 1, "call_id": "c1", "tool": "update_task", "status": "ok", "result_summary": {}, "duration_ms": 1})
            emit("result.validated", {"resolved_decision": "HOLD", "skill_count": 1, "conflict_count": 0})
            return {"reply": "第一行\n第二行", "trace_id": "trace_1"}

        return stream_turn_response(worker, turn_id="turn_1", trace_id="trace_1")

    response = TestClient(app).get("/stream")
    events = _parse_events(response.text)

    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert [name for name, _payload in events] == [
        "turn.started",
        "step.started",
        "tool.started",
        "tool.finished",
        "result.validated",
        "turn.completed",
    ]
    assert [payload["seq"] for _name, payload in events] == [1, 2, 3, 4, 5, 6]
    assert all(payload["turn_id"] == "turn_1" for _name, payload in events)
    assert sum(name in {"turn.completed", "turn.failed"} for name, _payload in events) == 1
    assert events[-1][1]["response"]["reply"] == "第一行\n第二行"


def test_stream_start_failure_runs_cleanup(monkeypatch) -> None:
    import backend.services.agent_sse as sse_module

    class FailThread:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("thread unavailable")

    monkeypatch.setattr(sse_module, "Thread", FailThread)
    cleanup: list[str] = []
    app = FastAPI()

    @app.get("/stream")
    def stream() -> Any:
        return stream_turn_response(
            lambda _emit: {"reply": "never"},
            turn_id="turn_cleanup",
            trace_id="trace_cleanup",
            on_start_failure=lambda exc: cleanup.append(str(exc)),
        )

    events = _parse_events(TestClient(app).get("/stream").text)

    assert cleanup == ["thread unavailable"]
    assert [name for name, _payload in events] == ["turn.failed"]
    assert events[0][1]["turn_id"] == "turn_cleanup"
    assert events[0][1]["code"] == "stream_start_failed"


def test_stream_failure_returns_only_turn_failed_terminal() -> None:
    app = FastAPI()

    @app.get("/stream")
    def stream() -> Any:
        def worker(emit: Any) -> dict[str, Any]:
            emit("turn.started", {"session_id": "s1", "user_message_id": "m1", "task_id": "t1"})
            raise AgentRuntimeError("internal detail", code="model_failed", retryable=True)

        return stream_turn_response(worker, turn_id="turn_fail", trace_id="trace_fail")

    events = _parse_events(TestClient(app).get("/stream").text)

    assert [name for name, _payload in events] == ["turn.started", "turn.failed"]
    assert events[-1][1]["code"] == "model_failed"
    assert events[-1][1]["retryable"] is True
    assert "internal detail" not in json.dumps(events[-1][1], ensure_ascii=False)


def test_stream_sends_heartbeat_while_worker_is_busy() -> None:
    app = FastAPI()

    @app.get("/stream")
    def stream() -> Any:
        def worker(emit: Any) -> dict[str, Any]:
            emit("turn.started", {"session_id": "s1", "user_message_id": "m1", "task_id": "t1"})
            time.sleep(0.15)
            return {"reply": "done"}

        return stream_turn_response(worker, turn_id="turn_ping", trace_id="trace_ping", heartbeat_seconds=0.01)

    body = TestClient(app).get("/stream").text
    assert ": ping\n\n" in body


def test_sse_encoder_redacts_sensitive_event_payloads() -> None:
    encoded = SSEEncoder("trace_redaction").event(
        "tool.started",
        {"arguments_summary": {"access_token": "secret", "file": "data:image/png;base64,abcdef"}},
    )

    assert "secret" not in encoded
    assert "data:image/png;base64" not in encoded
    assert "event: tool.started" in encoded
    data = next(line[6:] for line in encoded.splitlines() if line.startswith("data: "))
    payload = json.loads(data)
    assert payload["turn_id"] == "trace_redaction"
    assert payload["seq"] == 1


def test_agent_turn_route_returns_sse_and_json_compatible_completion(monkeypatch) -> None:
    import backend.routes.agent_routes as route_module
    from backend.main import app

    class FakeExecution:
        turn_id = "turn_test"
        session_id = "session_test"

        def __init__(self, **_kwargs: Any) -> None:
            self.trace_id = "trace_test"

        def prepare(self) -> "FakeExecution":
            return self

        def execute(self, on_event: Any = None) -> dict[str, Any]:
            if on_event:
                on_event("turn.started", {"session_id": "session_test", "user_message_id": "msg_user", "task_id": "task_test"})
                on_event("step.started", {"step": 1, "max_steps": 12})
            return {
                "session_id": "session_test",
                "status": "completed",
                "reply": "done",
                "trace_id": "trace_test",
                "turn_id": "turn_test",
                "user_message_id": "msg_user",
                "task_state": {"task_id": "task_test"},
            }

        def record_failure(self, _code: str) -> None:
            return

    class FakeTurnService:
        def begin(self, **_kwargs: Any) -> tuple[str, None]:
            return "turn_test", None

        def complete(self, _turn_id: str, _response: dict[str, Any]) -> None:
            return

        def fail(self, _turn_id: str, _error: str) -> None:
            return

        def release(self, **_kwargs: Any) -> None:
            return

    monkeypatch.setattr(route_module, "AgentTurnExecution", FakeExecution)
    monkeypatch.setattr(route_module, "TurnControlService", lambda: FakeTurnService())
    monkeypatch.setattr(route_module, "get_or_create_session", lambda _session_id: ("session_test", {}))

    response = TestClient(app).post(
        "/api/agent/turn",
        json={"message": "hello", "session_id": "session_test", "idempotency_key": "key_1"},
        headers={"Accept": "text/event-stream"},
    )
    events = _parse_events(response.text)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert [name for name, _payload in events] == ["turn.started", "step.started", "turn.completed"]
    assert events[-1][1]["response"]["reply"] == "done"


def test_agent_turn_route_failure_does_not_send_completion(monkeypatch) -> None:
    import backend.routes.agent_routes as route_module
    from backend.main import app

    class FakeExecution:
        turn_id = "turn_fail"
        session_id = "session_fail"

        def __init__(self, **_kwargs: Any) -> None:
            self.trace_id = "trace_fail_route"

        def prepare(self) -> "FakeExecution":
            return self

        def execute(self, on_event: Any = None) -> dict[str, Any]:
            if on_event:
                on_event("turn.started", {"session_id": "session_fail", "user_message_id": "msg_fail", "task_id": "task_fail"})
            raise AgentRuntimeError("provider details", code="model_failed", retryable=True)

        def record_failure(self, _code: str) -> None:
            return

    class FakeTurnService:
        def begin(self, **_kwargs: Any) -> tuple[str, None]:
            return "turn_fail", None

        def complete(self, _turn_id: str, _response: dict[str, Any]) -> None:
            raise AssertionError("failed turn must not complete")

        def fail(self, _turn_id: str, _error: str) -> None:
            return

        def release(self, **_kwargs: Any) -> None:
            return

    monkeypatch.setattr(route_module, "AgentTurnExecution", FakeExecution)
    monkeypatch.setattr(route_module, "TurnControlService", lambda: FakeTurnService())
    monkeypatch.setattr(route_module, "get_or_create_session", lambda _session_id: ("session_fail", {}))

    response = TestClient(app).post(
        "/api/agent/turn",
        json={"message": "fail", "session_id": "session_fail", "idempotency_key": "key_2"},
        headers={"Accept": "text/event-stream"},
    )
    events = _parse_events(response.text)

    assert [name for name, _payload in events] == ["turn.started", "turn.failed"]
    assert events[-1][1]["code"] == "model_failed"
    assert "provider details" not in response.text


def test_runtime_raises_agent_timeout_after_deadline() -> None:
    class SlowLLM:
        def complete(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            time.sleep(0.15)
            return {"content": "late", "output_items": [], "tool_calls": []}

    events: list[tuple[str, dict[str, Any]]] = []
    runtime = AgentRuntime(llm=SlowLLM(), tools=registry(), max_steps=1, turn_timeout_seconds=0.1)
    try:
        runtime.run_turn("slow request", on_event=lambda name, payload: events.append((name, payload)))
    except Exception as exc:
        assert type(exc).__name__ == "AgentTimeoutError"
        assert getattr(exc, "code") == "agent_timeout"
    else:
        raise AssertionError("timeout was not raised")
    assert [name for name, _payload in events] == ["step.started", "model.started", "model.failed"]
    assert events[-1][1]["reason"] == "hard_timeout"


def test_failure_after_validation_is_not_retryable() -> None:
    app = FastAPI()

    @app.get("/stream")
    def stream() -> Any:
        def worker(emit: Any) -> dict[str, Any]:
            emit("turn.started", {"session_id": "s1", "user_message_id": "m1", "task_id": "t1"})
            emit("result.validated", {"resolved_decision": "HOLD", "skill_count": 1, "conflict_count": 0})
            raise AgentRuntimeError("final save failed", code="persistence_failed", retryable=True)

        return stream_turn_response(worker, turn_id="turn_retry", trace_id="trace_retry")

    events = _parse_events(TestClient(app).get("/stream").text)
    assert events[-1][0] == "turn.failed"
    assert events[-1][1]["retryable"] is False


def test_closing_consumer_does_not_cancel_worker() -> None:
    finished = []

    def worker(emit: Any) -> dict[str, Any]:
        emit("turn.started", {"session_id": "s1", "user_message_id": "m1", "task_id": "t1"})
        time.sleep(0.05)
        finished.append(True)
        return {"reply": "done"}

    response = stream_turn_response(worker, turn_id="turn_disconnect", trace_id="trace_disconnect")

    async def consume_and_close() -> None:
        iterator = response.body_iterator
        first_chunk = await anext(iterator)
        assert "turn.started" in first_chunk
        await iterator.aclose()

    asyncio.run(consume_and_close())
    time.sleep(0.15)
    assert finished == [True]


def test_runtime_emits_draft_staged_without_creating_final_draft() -> None:
    definitions = [
        {
            "name": "ads_get_ad_entities",
            "description": "Entities",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ad_account_id": {"type": "string"},
                    "date_preset": {"type": "string"},
                    "level": {"type": "string"},
                },
                "required": ["ad_account_id", "date_preset", "level"],
            },
        },
        {
            "name": "ads_update_entity",
            "description": "Update",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ad_account_id": {"type": "string"},
                    "entity_id": {"type": "string"},
                    "entity_type": {"type": "string"},
                    "fields": {"type": "object"},
                    "evidence": {"type": "string"},
                    "recommendation": {"type": "string"},
                    "risk_level": {"type": "string"},
                    "current_state": {"type": "object"},
                },
                "required": ["ad_account_id", "entity_id", "entity_type", "fields", "evidence", "recommendation", "risk_level", "current_state"],
            },
        },
    ]
    llm = FakeLLM(
        [
            call("load_skill", {"skill_id": "optimization_draft"}),
            call(
                "ads_get_ad_entities",
                {"ad_account_id": "act_1", "date_preset": "last_7d", "level": "campaign", "force_refresh": True},
                namespace="meta_ads",
            ),
            call(
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
                namespace="meta_ads",
            ),
        ]
    )
    events: list[tuple[str, dict[str, Any]]] = []
    tools = MetaToolRegistry(mcp_client=FakeMCP(), tool_definitions=definitions)
    result = AgentRuntime(llm=llm, tools=tools, max_steps=3).run_turn(
        "Reduce the budget.",
        account_id="act_1",
        on_event=lambda name, payload: events.append((name, payload)),
    )

    staged = next(payload for name, payload in events if name == "draft.staged")
    assert staged["staged_action_id"] == "staged_1"
    assert result["drafts"] == []


def test_agent_turn_route_replays_completed_turn_as_sse(monkeypatch) -> None:
    import backend.routes.agent_routes as route_module
    from backend.main import app

    class FakeTurnService:
        def begin(self, **_kwargs: Any) -> tuple[str, dict[str, Any]]:
            return "turn_cached", {
                "session_id": "session_replay",
                "reply": "cached",
                "trace_id": "trace_replay",
                "trace": [],
                "drafts": [],
                "runtime": "react",
                "turn_id": "turn_cached",
                "user_message_id": "msg_user",
                "task_state": {"task_id": "task_replay"},
            }

    monkeypatch.setattr(route_module, "get_or_create_session", lambda _session_id: ("session_replay", {}))
    monkeypatch.setattr(route_module, "TurnControlService", lambda: FakeTurnService())

    response = TestClient(app).post(
        "/api/agent/turn",
        json={"message": "hello", "session_id": "session_replay", "idempotency_key": "key_3"},
        headers={"Accept": "text/event-stream"},
    )
    events = _parse_events(response.text)

    assert [name for name, _payload in events] == ["turn.started", "turn.completed"]
    assert events[-1][1]["response"]["idempotent_replay"] is True
    assert events[-1][1]["response"]["reply"] == "cached"
    assert all(payload["turn_id"] == "turn_cached" for _name, payload in events)
