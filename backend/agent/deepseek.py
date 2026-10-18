from __future__ import annotations

import json
import time
from typing import Any

from ..config import (
    active_llm_model,
    deepseek_api_key,
    deepseek_base_url,
    llm_max_output_tokens,
    llm_max_retries,
    llm_reasoning_effort,
    llm_timeout_seconds,
)


class DeepSeekChatClient:
    """OpenAI-compatible Chat Completions provider for DeepSeek."""

    supports_tool_search = False

    def __init__(
        self,
        model: str = "",
        api_key: str = "",
        base_url: str = "",
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        key = api_key or deepseek_api_key()
        if not key:
            from .runtime import AgentRuntimeError

            raise AgentRuntimeError("DEEPSEEK_API_KEY is not configured.", code="provider_init_failed", retryable=False)
        try:
            from openai import OpenAI
        except Exception as exc:
            from .runtime import AgentRuntimeError

            raise AgentRuntimeError(f"OpenAI-compatible SDK is unavailable: {exc}", code="provider_init_failed") from exc
        self.model = model or active_llm_model()
        self.base_url = base_url or deepseek_base_url()
        self.timeout_seconds = max(30, int(timeout_seconds or llm_timeout_seconds()))
        self.max_retries = max(0, int(llm_max_retries() if max_retries is None else max_retries))
        self.max_output_tokens = llm_max_output_tokens()
        self.reasoning_effort = llm_reasoning_effort() if reasoning_effort is None else reasoning_effort
        self.client = OpenAI(api_key=key, base_url=self.base_url, timeout=self.timeout_seconds, max_retries=0)

    def complete(
        self,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        from .runtime import AgentRuntimeError

        request_timeout = self.timeout_seconds
        if timeout_seconds is not None:
            request_timeout = max(1, min(self.timeout_seconds, int(timeout_seconds)))
        request = {
            "model": self.model,
            "messages": _chat_messages(instructions, input_items),
            "max_tokens": self.max_output_tokens,
            "parallel_tool_calls": False,
        }
        if self.reasoning_effort:
            request["reasoning_effort"] = self.reasoning_effort
        chat_tools = _chat_tools(tools)
        if chat_tools:
            request["tools"] = chat_tools
            request["tool_choice"] = "auto"

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(**request, timeout=request_timeout)
                return _map_chat_response(response)
            except Exception as exc:
                last_error = exc
                if not _retryable_provider_error(exc) or attempt >= self.max_retries:
                    break
                time.sleep(min(4.0, 2.0 ** attempt))
        code = "agent_timeout" if "timeout" in type(last_error).__name__.lower() else "model_failed"
        raise AgentRuntimeError(
            f"DeepSeek response failed: {type(last_error).__name__}: {last_error}",
            code=code,
            retryable=True,
        ) from last_error


def _chat_messages(instructions: str, input_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": instructions}]
    pending_content = ""
    pending_calls: list[dict[str, Any]] = []

    def flush_assistant() -> None:
        nonlocal pending_content, pending_calls
        if not pending_content and not pending_calls:
            return
        message: dict[str, Any] = {
            "role": "assistant",
            "content": pending_content or None,
        }
        if pending_calls:
            message["tool_calls"] = pending_calls
        messages.append(message)
        pending_content = ""
        pending_calls = []

    for item in input_items:
        item_type = str(item.get("type") or "")
        if item_type == "function_call":
            call_id = str(item.get("call_id") or item.get("id") or "")
            pending_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": str(item.get("name") or ""),
                        "arguments": str(item.get("arguments") or "{}"),
                    },
                }
            )
            continue
        if item_type in {"tool_search_call", "tool_search_output", "reasoning"}:
            continue
        if item_type == "function_call_output":
            flush_assistant()
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(item.get("call_id") or ""),
                    "content": str(item.get("output") or "{}"),
                }
            )
            continue
        role = str(item.get("role") or "")
        content = item.get("content")
        if role == "assistant":
            if isinstance(content, str):
                pending_content += content
            continue
        if role in {"user", "system"}:
            flush_assistant()
            if isinstance(content, str):
                messages.append({"role": role, "content": content})
            continue
        flush_assistant()
        if isinstance(content, str) and content:
            messages.append({"role": "user", "content": content})
    flush_assistant()
    return messages


def _chat_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        tool_type = str(tool.get("type") or "")
        if tool_type == "tool_search":
            continue
        if tool_type == "function" and isinstance(tool.get("function"), dict):
            function = tool["function"]
        elif tool_type == "function" and tool.get("name"):
            function = {
                "name": str(tool.get("name") or ""),
                "description": str(tool.get("description") or ""),
                "parameters": tool.get("parameters") or {"type": "object"},
            }
        elif tool_type == "namespace":
            for nested in tool.get("tools") or []:
                if not isinstance(nested, dict) or nested.get("type") != "function":
                    continue
                name = str(nested.get("name") or "")
                if not name or name in seen:
                    continue
                seen.add(name)
                output.append(
                    {
                        "type": "function",
                        "function": {
                            "name": name,
                            "description": str(nested.get("description") or ""),
                            "parameters": nested.get("parameters") or {"type": "object"},
                        },
                    }
                )
            continue
        else:
            continue
        name = str(function.get("name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        output.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(function.get("description") or ""),
                    "parameters": function.get("parameters") or {"type": "object"},
                },
            }
        )
    return output


def _map_chat_response(response: Any) -> dict[str, Any]:
    choice = response.choices[0]
    message = choice.message
    content = str(getattr(message, "content", "") or "")
    tool_calls: list[dict[str, Any]] = []
    output_items: list[dict[str, Any]] = []
    if content:
        output_items.append({"type": "message", "role": "assistant", "content": content})
    for call in getattr(message, "tool_calls", None) or []:
        function = getattr(call, "function", None)
        if function is None:
            continue
        call_id = str(getattr(call, "id", "") or "")
        name = str(getattr(function, "name", "") or "")
        arguments = str(getattr(function, "arguments", "") or "{}")
        tool_calls.append({"id": call_id, "name": name, "namespace": "", "arguments": arguments})
        output_items.append(
            {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "namespace": "",
                "arguments": arguments,
            }
        )
    usage = getattr(response, "usage", None)
    usage_payload = {
        "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    } if usage is not None else {}
    return {
        "content": content,
        "output_items": output_items,
        "tool_calls": tool_calls,
        "usage": usage_payload,
        "finish_reason": str(getattr(choice, "finish_reason", "") or ""),
    }


def _retryable_provider_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    if any(marker in name for marker in ("authentication", "permission", "badrequest")):
        return False
    return any(marker in name for marker in ("connection", "timeout", "ratelimit", "internalserver", "apistatus"))


__all__ = ["DeepSeekChatClient"]