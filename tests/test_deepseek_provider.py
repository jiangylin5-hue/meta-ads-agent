from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from backend.agent.deepseek import DeepSeekChatClient, _chat_messages, _chat_tools
from backend.agent.runtime import AgentRuntime


class FakePortableLLM:
    supports_tool_search = False

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]] = []

    def complete(self, instructions: str, input_items: list[dict[str, Any]], tools: list[dict[str, Any]], **_kwargs: Any) -> dict[str, Any]:
        self.calls.append((instructions, input_items, tools))
        return self.responses.pop(0)


class PortableTools:
    selected_account_id = ""
    tools_by_name = {
        "ads_get_ad_accounts": {"name": "ads_get_ad_accounts", "description": "Accounts", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}}}
    }

    def set_context(self, account_id: str = "", request_text: str = "") -> None:
        self.selected_account_id = account_id

    def set_advertiser_job(self, _job: str) -> None:
        return

    def schemas(self) -> list[dict[str, Any]]:
        return []

    def portable_schemas(self, allowed_tools: set[str]) -> list[dict[str, Any]]:
        if "ads_get_ad_accounts" not in allowed_tools:
            return []
        return [
            {
                "type": "function",
                "name": "ads_get_ad_accounts",
                "description": "Accounts",
                "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
            }
        ]

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"tool": name, "result": {"data": [{"id": "act_1", "name": "Demo"}]}}


def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": "",
        "output_items": [
            {"type": "function_call", "call_id": f"call_{name}", "name": name, "namespace": "", "arguments": json.dumps(arguments)}
        ],
        "tool_calls": [{"id": f"call_{name}", "name": name, "namespace": "", "arguments": json.dumps(arguments)}],
    }


def test_chat_adapter_converts_tool_calls_and_outputs() -> None:
    messages = _chat_messages(
        "policy",
        [
            {"role": "user", "content": "hello"},
            {"type": "function_call", "call_id": "c1", "name": "echo", "arguments": "{\"text\":\"ping\"}"},
            {"type": "function_call_output", "call_id": "c1", "output": "{\"ok\":true}"},
        ],
    )
    tools = _chat_tools(
        [
            {"type": "tool_search"},
            {"type": "function", "name": "echo", "description": "Echo", "parameters": {"type": "object"}},
        ]
    )

    assert messages[0] == {"role": "system", "content": "policy"}
    assert messages[1] == {"role": "user", "content": "hello"}
    assert messages[2]["role"] == "assistant"
    assert messages[2]["tool_calls"][0]["function"]["name"] == "echo"
    assert messages[3] == {"role": "tool", "tool_call_id": "c1", "content": "{\"ok\":true}"}
    assert tools == [{"type": "function", "function": {"name": "echo", "description": "Echo", "parameters": {"type": "object"}}}]


def test_deepseek_client_maps_chat_tool_call(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class Completions:
        def create(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            message = SimpleNamespace(
                content="",
                tool_calls=[
                    SimpleNamespace(
                        id="call_1",
                        function=SimpleNamespace(name="echo", arguments="{\"text\":\"ping\"}"),
                    )
                ],
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message, finish_reason="tool_calls")],
                usage=SimpleNamespace(prompt_tokens=12, completion_tokens=4, total_tokens=16),
            )

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["client_options"] = kwargs
            self.chat = SimpleNamespace(completions=Completions())

    monkeypatch.setattr("openai.OpenAI", FakeClient)
    client = DeepSeekChatClient(api_key="test", model="deepseek-flash", base_url="https://api.deepseek.com", max_retries=0, reasoning_effort="high")
    result = client.complete(
        "policy",
        [{"role": "user", "content": "ping"}],
        [{"type": "function", "name": "echo", "description": "Echo", "parameters": {"type": "object"}}],
    )

    assert captured["model"] == "deepseek-flash"
    assert captured["reasoning_effort"] == "high"
    assert captured["client_options"]["max_retries"] == 0
    assert result["tool_calls"][0]["name"] == "echo"
    assert result["usage"]["input_tokens"] == 12
    assert result["output_items"][0]["type"] == "function_call"


def test_runtime_portable_mode_exposes_tools_only_after_skill_load() -> None:
    llm = FakePortableLLM(
        [
            _call("load_skill", {"skill_id": "account_brief"}),
            _call("ads_get_ad_accounts", {"limit": 3}),
            {
                "content": "",
                "output_items": [
                    {
                        "type": "function_call",
                        "call_id": "call_submit_result",
                        "name": "submit_result",
                        "namespace": "",
                        "arguments": json.dumps(
                            {
                                "reply": "One account.",
                                "result": {
                                    "facts": ["One readable account."],
                                    "missing_data": [],
                                    "source_tools": ["ads_get_ad_accounts"],
                                },
                            }
                        ),
                    }
                ],
                "tool_calls": [
                    {
                        "id": "call_submit_result",
                        "name": "submit_result",
                        "namespace": "",
                        "arguments": json.dumps(
                            {
                                "reply": "One account.",
                                "result": {
                                    "facts": ["One readable account."],
                                    "missing_data": [],
                                    "source_tools": ["ads_get_ad_accounts"],
                                },
                            }
                        ),
                    }
                ],
            },
        ]
    )
    result = AgentRuntime(llm=llm, tools=PortableTools(), max_steps=4).run_turn("Which accounts are readable?")

    first_tools = {tool.get("name") for tool in llm.calls[0][2]}
    second_tools = {tool.get("name") for tool in llm.calls[1][2]}
    assert "ads_get_ad_accounts" not in first_tools
    assert {"load_skill", "ask_user", "ads_get_ad_accounts"}.issubset(second_tools)
    assert "tool_search" not in second_tools
    assert result["stopped_reason"] == "final"
    assert result["trace"][1]["tool"] == "ads_get_ad_accounts"