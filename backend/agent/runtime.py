from __future__ import annotations

import json
from datetime import datetime, timezone
from queue import Empty, Queue
from threading import Thread
from time import monotonic
from typing import Any, Callable, Protocol

from ..config import active_llm_model, active_llm_provider, agent_max_steps, agent_turn_timeout_seconds, ga4_enabled, openai_api_key, openai_model, openai_reasoning_effort, openai_timeout_seconds
from .deepseek import DeepSeekChatClient
from .context import (
    ContextAssembler,
    compact_tool_outputs,
    estimate_tokens,
    fallback_summary,
    parse_summary_response,
    split_recent_rounds,
    summary_prompt,
)
from .policy import ensure_tool_allowed
from .prompts import SYSTEM_PROMPT
from .skills import SkillCatalog, SkillCatalogError
from .state import AgentState
from .tools import MetaToolRegistry, _draft_target, is_direct_draft_create_tool, is_direct_draft_mutation_tool, is_write_tool
from ..services.account_cache import MCPToolResultCache
from ..services.ga4_gateway import Ga4Gateway
from ..services.long_term_memory import validate_memory_tool_args
from ..services.task_state import validate_task_update


LOCAL_TRACE_TOOLS = {"tool_search", "ask_user", "load_skill", "read_skill_reference", "submit_result", "save_memory", "update_task"}
SENSITIVE_ARGUMENT_MARKERS = (
    "access_token",
    "authorization",
    "api_key",
    "client_secret",
    "cookie",
    "data_url",
    "image_data",
    "video_data",
    "credential",
    "password",
    "private_key",
    "secret",
)


class AgentRuntimeError(RuntimeError):
    def __init__(self, message: str, *, code: str = "agent_runtime_failed", retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class AgentTimeoutError(AgentRuntimeError):
    def __init__(self, message: str = "Agent turn exceeded its time limit.") -> None:
        super().__init__(message, code="agent_timeout", retryable=True)


TurnEventHandler = Callable[[str, dict[str, Any]], None]


class LLMClient(Protocol):
    def complete(
        self,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        ...


class OpenAIResponsesClient:
    """Responses API client for deferred tools and tool search."""

    supports_tool_search = True

    def __init__(self, model: str = "", api_key: str = "", reasoning_effort: str = "") -> None:
        key = api_key or openai_api_key()
        if not key:
            raise AgentRuntimeError("OPENAI_API_KEY is not configured.")
        from openai import OpenAI

        self.model = model or openai_model()
        self.reasoning_effort = reasoning_effort or openai_reasoning_effort()
        self.client = OpenAI(api_key=key, timeout=openai_timeout_seconds())

    def complete(
        self,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": input_items,
            "tools": _responses_tools(tools),
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "store": False,
        }
        if self.reasoning_effort:
            request["reasoning"] = {"effort": self.reasoning_effort}
        try:
            request_timeout = openai_timeout_seconds()
            if timeout_seconds is not None:
                request_timeout = max(1, min(request_timeout, int(timeout_seconds)))
            response = self.client.responses.create(**request, timeout=request_timeout)
        except Exception as exc:
            code = "agent_timeout" if "timeout" in type(exc).__name__.lower() else "model_failed"
            raise AgentRuntimeError(
                f"OpenAI response failed: {type(exc).__name__}: {exc}",
                code=code,
                retryable=True,
            ) from exc

        output_items = [item.model_dump(exclude_none=True) for item in getattr(response, "output", []) or []]
        tool_calls: list[dict[str, Any]] = []
        for item in getattr(response, "output", []) or []:
            if getattr(item, "type", "") != "function_call":
                continue
            tool_calls.append(
                {
                    "id": str(getattr(item, "call_id", "") or getattr(item, "id", "")),
                    "name": str(getattr(item, "name", "")),
                    "namespace": str(getattr(item, "namespace", "") or ""),
                    "arguments": str(getattr(item, "arguments", "") or "{}"),
                }
            )
        usage = getattr(response, "usage", None)
        usage_payload = {
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        } if usage is not None else {}
        return {
            "content": str(getattr(response, "output_text", "") or ""),
            "output_items": output_items,
            "tool_calls": tool_calls,
            "usage": usage_payload,
        }



def _default_llm_client() -> LLMClient:
    if active_llm_provider() == "deepseek":
        return DeepSeekChatClient()
    return OpenAIResponsesClient()


def _ask_user_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "ask_user",
        "description": "Stop and ask one focused question when required context is missing.",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    }


def _complete_model_with_deadline(
    llm: LLMClient,
    instructions: str,
    input_items: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    timeout_seconds: float,
    on_event: TurnEventHandler | None,
    step: int,
    event_context: str,
) -> dict[str, Any]:
    timeout = max(0.1, float(timeout_seconds))
    provider = active_llm_provider()
    model = active_llm_model()
    _emit_event(
        on_event,
        "model.started",
        {
            "step": step,
            "context": event_context,
            "provider": provider,
            "model": model,
            "input_item_count": len(input_items),
            "tool_count": len(tools),
        },
    )
    started = monotonic()
    result_queue: Queue[tuple[str, Any]] = Queue(maxsize=1)

    def worker() -> None:
        try:
            result_queue.put(("ok", llm.complete(instructions, input_items, tools, timeout_seconds=timeout)))
        except BaseException as exc:
            result_queue.put(("error", exc))

    thread = Thread(target=worker, name=f"model-{event_context}-{step}", daemon=True)
    thread.start()
    try:
        status, payload = result_queue.get(timeout=timeout)
    except Empty as exc:
        _emit_event(
            on_event,
            "model.failed",
            {
                "step": step,
                "context": event_context,
                "provider": provider,
                "model": model,
                "reason": "hard_timeout",
                "timeout_seconds": timeout,
                "duration_ms": int((monotonic() - started) * 1000),
            },
        )
        raise AgentTimeoutError("Model provider did not respond before the turn deadline.") from exc
    if status == "error":
        error = payload
        _emit_event(
            on_event,
            "model.failed",
            {
                "step": step,
                "context": event_context,
                "provider": provider,
                "model": model,
                "reason": type(error).__name__,
                "duration_ms": int((monotonic() - started) * 1000),
            },
        )
        raise error
    response = payload if isinstance(payload, dict) else {}
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    _emit_event(
        on_event,
        "model.finished",
        {
            "step": step,
            "context": event_context,
            "provider": provider,
            "model": model,
            "duration_ms": int((monotonic() - started) * 1000),
            "tool_call_count": len(response.get("tool_calls") or []),
            "content_chars": len(str(response.get("content") or "")),
            "finish_reason": str(response.get("finish_reason") or ""),
            "usage": usage,
        },
    )
    return response

def _responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in tools:
        tool_type = str(item.get("type") or "")
        if tool_type == "function" and isinstance(item.get("function"), dict):
            function = item["function"]
            output.append(
                {
                    "type": "function",
                    "name": str(function.get("name") or ""),
                    "description": str(function.get("description") or ""),
                    "parameters": function.get("parameters") or {"type": "object"},
                    **({"defer_loading": True} if item.get("defer_loading") else {}),
                }
            )
            continue
        if tool_type == "namespace":
            functions = []
            for function in item.get("tools") or []:
                if not isinstance(function, dict) or function.get("type") != "function":
                    continue
                functions.append(
                    {
                        "type": "function",
                        "name": str(function.get("name") or ""),
                        "description": str(function.get("description") or ""),
                        "parameters": function.get("parameters") or {"type": "object"},
                        **({"defer_loading": True} if function.get("defer_loading") else {}),
                    }
                )
            output.append(
                {
                    "type": "namespace",
                    "name": str(item.get("name") or ""),
                    "description": str(item.get("description") or ""),
                    "tools": functions,
                }
            )
            continue
        output.append(json.loads(json.dumps(item)))
    return output


class AgentRuntime:
    def __init__(
        self,
        llm: LLMClient | None = None,
        tools: MetaToolRegistry | None = None,
        skills: SkillCatalog | None = None,
        max_steps: int | None = None,
        turn_timeout_seconds: float | None = None,
    ) -> None:
        try:
            self.tools = tools or MetaToolRegistry(
                result_cache=MCPToolResultCache(),
                ga4_gateway=Ga4Gateway() if ga4_enabled() else None,
            )
        except Exception as exc:
            raise AgentRuntimeError(
                f"MCP tool discovery failed: {type(exc).__name__}: {exc}",
                code="runtime_init_failed",
                retryable=True,
            ) from exc
        try:
            self.skills = skills or SkillCatalog()
        except Exception as exc:
            raise AgentRuntimeError(
                f"Skill contract loading failed: {type(exc).__name__}: {exc}",
                code="runtime_init_failed",
                retryable=True,
            ) from exc
        self.llm = llm or _default_llm_client()
        self.max_steps = max(1, min(int(max_steps if max_steps is not None else agent_max_steps()), 24))
        self.turn_timeout_seconds = max(
            0.1,
            float(turn_timeout_seconds if turn_timeout_seconds is not None else agent_turn_timeout_seconds()),
        )
        self.context = ContextAssembler()

    def run_turn(
        self,
        message: str,
        history: list[dict[str, Any]] | None = None,
        account_id: str = "",
        frontend_context: dict[str, Any] | None = None,
        summary: dict[str, Any] | None = None,
        task_state: dict[str, Any] | None = None,
        memories: list[dict[str, Any]] | None = None,
        account_context: dict[str, Any] | None = None,
        active_skill_ids: list[str] | None = None,
        session_id: str = "",
        task_id: str = "",
        user_message_id: str = "",
        draft_creation_authorized: bool = False,
        on_event: TurnEventHandler | None = None,
    ) -> dict[str, Any]:
        deadline = monotonic() + self.turn_timeout_seconds
        set_deadline = getattr(self.tools, "set_deadline", None)
        if callable(set_deadline):
            set_deadline(deadline)
        state = AgentState(
            message=message,
            account_id=account_id,
            max_steps=self.max_steps,
            source_messages=list(history or []),
            user_message_id=user_message_id,
            session_id=session_id,
            task_id=task_id,
        )
        self.tools.set_context(account_id, message)
        if isinstance(account_context, dict) and account_context.get("freshness") in {"fresh", "stale"}:
            for tool_name in account_context.get("source_tools") or []:
                name = str(tool_name).strip()
                if name and name not in state.read_tools:
                    state.read_tools.append(name)
        available_tools = set(self.tools.tools_by_name)
        self._preload_skills(active_skill_ids or [], state, available_tools)
        older, _ = split_recent_rounds(history, self.context.recent_rounds)
        summary_update = dict(summary or {})
        if older:
            self._check_deadline(deadline)
            summary_update = self._summarize_history(older, summary_update, self._remaining_seconds(deadline), on_event)
        state.summary_update = summary_update
        portable_tools = not bool(getattr(self.llm, "supports_tool_search", True))
        base_instructions = "\n\n".join(
            [
                SYSTEM_PROMPT,
                self.skills.catalog_text(),
                (
                    "The runtime exposes each active Skill's tools directly after load_skill. "
                    "Tool search is unavailable in this provider mode."
                    if portable_tools
                    else "Use tool_search to load only the tools needed for the active Skill."
                ),
            ]
        )
        package = self.context.assemble(
            base_instructions=base_instructions,
            history=history,
            summary=summary_update,
            task_state=task_state,
            memories=memories,
            account_context=account_context,
            active_skills=[item for item in state.loaded_skills if item.get("instructions")],
        )
        instructions = package.instructions
        local_tool_schemas = [
            _load_skill_tool(self.skills.catalog_entries()),
            _read_skill_reference_tool(self.skills.catalog_entries()),
            _submit_result_tool(),
            _save_memory_tool(),
            _update_task_tool(),
        ]
        tool_schemas = [_ask_user_tool(), *local_tool_schemas] if portable_tools else self.tools.schemas() + local_tool_schemas
        input_items: list[dict[str, Any]] = [
            {"role": item["role"], "content": item["content"]} for item in package.recent_messages
        ]
        input_items.append({"role": "user", "content": message})
        manifest = dict(package.manifest)
        manifest["current_message_tokens"] = estimate_tokens(message)
        manifest["tool_schema_tokens"] = estimate_tokens(tool_schemas)
        manifest["account_evidence_tools"] = list(state.read_tools)
        manifest["model_provider"] = active_llm_provider()
        manifest["model_name"] = active_llm_model()
        manifest["estimated_input_tokens"] = (
            manifest.get("instructions_tokens", 0)
            + manifest.get("history_tokens", 0)
            + manifest["current_message_tokens"]
        )
        state.context_manifest = manifest
        call_kinds: dict[str, str] = {}

        for step in range(1, self.max_steps + 1):
            self._check_deadline(deadline)
            state.step = step
            _emit_event(on_event, "step.started", {"step": step, "max_steps": self.max_steps})
            input_items = compact_tool_outputs(input_items, call_kinds, deadline=deadline)
            if portable_tools:
                allowed_tools = self.skills.allowed_tools(state.loaded_skills)
                tool_schemas = self.tools.portable_schemas(allowed_tools) + [_ask_user_tool(), *local_tool_schemas]
                state.context_manifest["tool_schema_tokens"] = estimate_tokens(tool_schemas)
                state.context_manifest["portable_tool_count"] = len(tool_schemas)
            response = _complete_model_with_deadline(
                self.llm,
                instructions,
                input_items,
                tool_schemas,
                timeout_seconds=self._remaining_seconds(deadline),
                on_event=on_event,
                step=step,
                event_context="turn",
            )
            self._check_deadline(deadline)
            usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
            if usage:
                state.context_manifest["actual_input_tokens"] = usage.get("input_tokens", 0)
                state.context_manifest["actual_output_tokens"] = usage.get("output_tokens", 0)
                state.context_manifest["provider_request_count"] = int(state.context_manifest.get("provider_request_count") or 0) + 1
            output_items = response.get("output_items") or []
            input_items.extend(output_items)
            _record_tool_search(state, output_items)
            tool_calls = response.get("tool_calls") or []
            if tool_calls:
                for call in tool_calls:
                    self._check_deadline(deadline)
                    name = str(call.get("name") or "")
                    namespace = str(call.get("namespace") or "")
                    call_id = str(call.get("id") or "")
                    trace_name = f"{namespace}.{name}" if namespace else name
                    arguments = _parse_arguments(call.get("arguments"))
                    arguments_summary = _compact_arguments(arguments)
                    loaded_skill_names_before = {str(item.get("name") or "") for item in state.loaded_skills}
                    loaded_references_before = {
                        (str(item.get("skill") or ""), str(item.get("reference") or ""))
                        for item in state.loaded_references
                    }
                    call_started_at = monotonic()
                    call_kinds[call_id] = "local" if name in LOCAL_TRACE_TOOLS else "mcp"
                    _emit_event(
                        on_event,
                        "tool.started",
                        {
                            "step": step,
                            "call_id": call_id,
                            "tool": trace_name,
                            "arguments_summary": arguments_summary,
                        },
                    )
                    try:
                        if "__argument_parse_error__" in arguments:
                            raise ValueError(f"Invalid JSON arguments for {trace_name}: {arguments['__argument_parse_error__']}")
                        ensure_tool_allowed(name, available_tools)
                        if name == "load_skill":
                            result = self._load_skill(arguments, state, available_tools)
                        elif name == "read_skill_reference":
                            result = self._read_skill_reference(arguments, state)
                        elif name == "submit_result":
                            result = self._submit_result(arguments, state)
                        elif name == "save_memory":
                            result = self._save_memory(arguments, state)
                        elif name == "update_task":
                            result = self._update_task(arguments, state)
                        elif name == "ask_user":
                            result = self.tools.execute(name, arguments)
                        else:
                            allowed_tools = self.skills.allowed_tools(state.loaded_skills)
                            if name not in allowed_tools and not self.tools.is_core_tool(name):
                                raise PermissionError(
                                    "Tool is outside the loaded skill scope. Call load_skill for a relevant skill first."
                                )
                            schema = self.tools.tools_by_name[name].get("inputSchema") or self.tools.tools_by_name[name].get("input_schema") or {}
                            missing_inputs = _input_gate_errors(name, arguments, state, schema, self.tools.selected_account_id)
                            if missing_inputs:
                                result = {
                                    "error": "Missing required inputs: " + ", ".join(missing_inputs),
                                    "missing_inputs": missing_inputs,
                                }
                            elif is_write_tool(name):
                                if is_direct_draft_create_tool(name) and not draft_creation_authorized:
                                    result = {
                                        "error": "New Draft creation requires explicit user confirmation.",
                                        "confirmation_required": True,
                                        "confirmation_phrase": "确认创建草稿",
                                    }
                                else:
                                    draft_errors = _draft_evidence_errors(name, arguments, state)
                                    mutation_requested = is_direct_draft_mutation_tool(name) and bool(arguments.get("draft_only"))
                                    mutation_errors = (
                                        _draft_mutation_evidence_errors(name, arguments, state)
                                        if mutation_requested
                                        else []
                                    )
                                    verified_state: dict[str, Any] | None = None
                                    state_errors: list[str] = []
                                    if not draft_errors and not mutation_errors and not mutation_requested:
                                        verified_state, state_errors = _verified_optimization_current_state(
                                            name,
                                            arguments,
                                            state,
                                        )
                                    validation_errors = sorted(set([*draft_errors, *mutation_errors, *state_errors]))
                                    if validation_errors:
                                        result = {
                                            "error": "Draft evidence is incomplete.",
                                            "missing_evidence": validation_errors,
                                        }
                                    else:
                                        if verified_state is not None:
                                            arguments = {**arguments, "current_state": verified_state}
                                        if mutation_requested:
                                            updated = self.tools.mutate_draft(name, arguments)
                                            if isinstance(updated, dict) and not updated.get("error"):
                                                state.direct_draft_mutations.append(updated)
                                            result = updated
                                        elif is_direct_draft_create_tool(name):
                                            created = self.tools.create_paused_draft(name, arguments)
                                            if isinstance(created, dict) and created.get("created"):
                                                state.direct_drafts.append(created)
                                            result = created
                                        else:
                                            staged = self.tools.stage_write(name, arguments)
                                            if isinstance(staged, dict) and not staged.get("error"):
                                                staged_id = f"staged_{len(state.staged_actions) + 1}"
                                                staged["staged_action_id"] = staged_id
                                                state.staged_actions.append(staged)
                                                result = {
                                                    "staged_action_id": staged_id,
                                                    "status": "staged",
                                                    "tool": name,
                                                    "target_level": staged.get("target_level"),
                                                    "target_id": staged.get("target_id"),
                                                    "target_name": staged.get("target_name"),
                                                }
                                            else:
                                                result = staged
                            else:
                                result = self.tools.execute(name, arguments)
                                if isinstance(result, dict) and result.get("tool") and not result.get("error") and not result.get("draft_id"):
                                    state.read_tools.append(name)
                                    if not self.tools.is_core_tool(name) and not (isinstance(result.get("_cache"), dict) and result["_cache"].get("hit")):
                                        state.live_read_tools.append(name)
                                        state.live_read_evidence.append(
                                            _build_live_read_evidence(
                                                name,
                                                arguments,
                                                result,
                                                self.tools.selected_account_id,
                                            )
                                        )
                    except PermissionError as exc:
                        result = {"error": str(exc)}
                    except AgentTimeoutError:
                        raise
                    except Exception as exc:
                        result = {"error": f"Tool {trace_name} failed: {type(exc).__name__}: {exc}"}
                    compact_result = _compact_result(result)
                    state.trace.append(
                        {
                            "step": step,
                            "tool": trace_name,
                            "arguments": arguments_summary,
                            "result": compact_result,
                        }
                    )
                    state.tool_ledger.append(
                        {
                            "step": step,
                            "tool": trace_name,
                            "arguments": _ledger_arguments(arguments),
                            "result": compact_result,
                        }
                    )
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps(result, ensure_ascii=False),
                        }
                    )
                    _emit_event(
                        on_event,
                        "tool.finished",
                        {
                            "step": step,
                            "call_id": call_id,
                            "tool": trace_name,
                            "status": "error" if isinstance(result, dict) and result.get("error") else "ok",
                            "result_summary": compact_result,
                            "duration_ms": max(0, int((monotonic() - call_started_at) * 1000)),
                        },
                    )
                    if name == "load_skill" and isinstance(result, dict) and not result.get("error"):
                        new_skills = [
                            {
                                "id": str(item.get("name") or ""),
                                "name": str(item.get("name") or ""),
                                "version": str(item.get("version") or ""),
                            }
                            for item in state.loaded_skills
                            if str(item.get("name") or "") not in loaded_skill_names_before
                        ]
                        if new_skills:
                            _emit_event(on_event, "skill.loaded", {"skills": new_skills})
                    if name == "read_skill_reference" and isinstance(result, dict) and not result.get("error"):
                        reference_key = (str(result.get("skill") or ""), str(result.get("reference") or ""))
                        if reference_key not in loaded_references_before:
                            _emit_event(
                                on_event,
                                "reference.loaded",
                                {
                                    "skill": reference_key[0],
                                    "reference": reference_key[1],
                                    "chars": int(result.get("chars") or 0),
                                    "truncated": bool(result.get("truncated")),
                                },
                            )
                    if isinstance(result, dict) and result.get("staged_action_id"):
                        _emit_event(
                            on_event,
                            "draft.staged",
                            {
                                "staged_action_id": result.get("staged_action_id"),
                                "tool": result.get("tool") or name,
                                "target_level": result.get("target_level"),
                                "target_id": result.get("target_id"),
                                "target_name": result.get("target_name"),
                            },
                        )
                    if isinstance(result, dict) and result.get("final"):
                        submitted = result.get("result") if isinstance(result.get("result"), dict) else {}
                        _emit_event(
                            on_event,
                            "result.validated",
                            {
                                "resolved_decision": submitted.get("resolved_decision"),
                                "skill_count": len(submitted.get("skill_results") or {}),
                                "conflict_count": len(submitted.get("conflicts") or []),
                            },
                        )
                        return _result(state, str(result.get("reply") or ""), "final")
                    if isinstance(result, dict) and result.get("needs_user_input"):
                        return _result(state, str(result.get("question") or "I need one more detail."), "ask_user")
                    if isinstance(result, dict) and result.get("draft_id"):
                        _append_draft(state, result)
                continue

            reply = str(response.get("content") or "").strip()
            if reply:
                if state.loaded_skills and not state.submitted_result:
                    requirements = _output_requirements(state)
                    input_items.append(
                        {
                            "role": "user",
                            "content": (
                                "Your final answer was rejected because the active Skills require structured output. "
                                "Call submit_result with a non-empty reply and a result object. "
                                f"Required output: {requirements}"
                            ),
                        }
                    )
                    continue
                return _result(state, reply, "final")
            if any(item.get("type") == "tool_search_call" for item in output_items):
                continue
            return _result(state, "I need one more detail before I can continue.", "final")

        return _result(
            state,
            "I stopped after the maximum number of tool steps. Review the trace and refine the question.",
            "max_steps",
        )

    @staticmethod
    def _check_deadline(deadline: float) -> None:
        if monotonic() >= deadline:
            raise AgentTimeoutError()

    @staticmethod
    def _remaining_seconds(deadline: float) -> float:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise AgentTimeoutError()
        return remaining

    def _preload_skills(
        self,
        skill_ids: list[str],
        state: AgentState,
        available_tools: set[str],
    ) -> None:
        for skill_id in list(dict.fromkeys(str(item).strip() for item in skill_ids if str(item).strip()))[: self.skills.max_loaded_skills]:
            try:
                loaded = self.skills.load(skill_id, available_tools)
            except SkillCatalogError:
                continue
            state.loaded_skills.append(
                {
                    "name": loaded["name"],
                    "version": loaded["version"],
                    "advertiser_job": loaded["advertiser_job"],
                    "allowed_tools": loaded["allowed_tools"],
                    "input_gates": loaded.get("input_gates", {}),
                    "evidence_gates": loaded.get("evidence_gates", {}),
                    "evidence_requirements": loaded.get("evidence_requirements", {}),
                    "output_contract": loaded.get("output_contract", {}),
                    "instructions": loaded.get("instructions", ""),
                }
            )
        if state.loaded_skills:
            self.tools.set_advertiser_job(self.skills.advertiser_job(state.loaded_skills))

    def _summarize_history(
        self,
        older_messages: list[dict[str, Any]],
        existing_summary: dict[str, Any],
        timeout_seconds: float,
        on_event: TurnEventHandler | None = None,
    ) -> dict[str, Any]:
        instructions, payload = summary_prompt(existing_summary, older_messages)
        try:
            response = _complete_model_with_deadline(
                self.llm,
                instructions,
                [{"role": "user", "content": payload}],
                [],
                timeout_seconds=timeout_seconds,
                on_event=on_event,
                step=0,
                event_context="conversation_summary",
            )
            return parse_summary_response(str(response.get("content") or ""), existing_summary, older_messages)
        except Exception:
            return fallback_summary(existing_summary, older_messages)

    def _save_memory(self, arguments: dict[str, Any], state: AgentState) -> dict[str, Any]:
        payload, error = validate_memory_tool_args(arguments, account_id=state.account_id)
        if error or payload is None:
            return {"error": error or "Invalid Memory write."}
        payload["source_text"] = state.message
        payload["source_role"] = "user"
        state.memory_writes.append(payload)
        return {
            "saved": True,
            "memory_candidate": {
                "kind": payload["kind"],
                "scope": payload["scope"],
                "content": payload["content"],
                "confidence": payload["confidence"],
            },
            "note": "Memory will be persisted after this turn. Inferred records may remain candidates until confirmed.",
        }

    def _update_task(self, arguments: dict[str, Any], state: AgentState) -> dict[str, Any]:
        update, error = validate_task_update(arguments)
        if error or update is None:
            return {"error": error or "Invalid task update."}
        state.task_update.update(update)
        return {"updated": True, "task_update": state.task_update}

    def _load_skill(
        self,
        arguments: dict[str, Any],
        state: AgentState,
        available_tools: set[str],
    ) -> dict[str, Any]:
        raw_ids = arguments.get("skill_ids")
        skill_ids: list[str] = []
        if isinstance(raw_ids, list):
            skill_ids.extend(str(item).strip() for item in raw_ids if str(item).strip())
        elif raw_ids not in (None, ""):
            return {"error": "skill_ids must be an array of skill ids."}
        single = str(arguments.get("skill_id") or "").strip()
        if single:
            skill_ids.insert(0, single)
        unique_ids = list(dict.fromkeys(skill_ids))
        if not unique_ids:
            return {"error": "load_skill requires skill_id or skill_ids."}

        loaded_items: list[dict[str, Any]] = []
        errors: list[str] = []
        already_loaded = {str(item.get("name") or "") for item in state.loaded_skills}
        for skill_id in unique_ids:
            if skill_id in already_loaded:
                try:
                    loaded_items.append(self.skills.load(skill_id, available_tools))
                except SkillCatalogError as exc:
                    errors.append(str(exc))
                continue
            if len(state.loaded_skills) >= self.skills.max_loaded_skills:
                errors.append(f"At most {self.skills.max_loaded_skills} skills can be loaded in one turn.")
                break
            try:
                loaded = self.skills.load(skill_id, available_tools)
            except SkillCatalogError as exc:
                errors.append(str(exc))
                continue
            loaded_items.append(loaded)
            state.loaded_skills.append(
                {
                    "name": loaded["name"],
                    "version": loaded["version"],
                    "advertiser_job": loaded["advertiser_job"],
                    "allowed_tools": loaded["allowed_tools"],
                    "input_gates": loaded.get("input_gates", {}),
                    "evidence_gates": loaded.get("evidence_gates", {}),
                    "evidence_requirements": loaded.get("evidence_requirements", {}),
                    "output_contract": loaded.get("output_contract", {}),
                    "instructions": loaded.get("instructions", ""),
                }
            )
            already_loaded.add(skill_id)
            self.tools.set_advertiser_job(self.skills.advertiser_job(state.loaded_skills))

        if not loaded_items:
            return {"error": "; ".join(errors) or "No skills loaded."}
        if len(loaded_items) == 1:
            result = dict(loaded_items[0])
            if errors:
                result["errors"] = errors
            return result
        return {
            "name": " + ".join(str(item.get("name") or "") for item in loaded_items),
            "version": "multi",
            "instructions": "\n\n".join(str(item.get("instructions") or "") for item in loaded_items),
            "read_tools": sorted({tool for item in loaded_items for tool in item.get("read_tools", [])}),
            "optional_read_tools": sorted({tool for item in loaded_items for tool in item.get("optional_read_tools", [])}),
            "draft_tools": sorted({tool for item in loaded_items for tool in item.get("draft_tools", [])}),
            "allowed_tools": sorted({tool for item in loaded_items for tool in item.get("allowed_tools", [])}),
            "references": [
                ref
                for item in loaded_items
                for ref in item.get("references", [])
            ],
            "skills": [str(item.get("name") or "") for item in loaded_items],
            "errors": errors,
        }


    def _submit_result(self, arguments: dict[str, Any], state: AgentState) -> dict[str, Any]:
        if not state.loaded_skills:
            return {"error": "Load at least one skill before submitting a final result."}
        reply = str(arguments.get("reply") or "").strip()
        if not reply:
            return {"error": "submit_result requires a non-empty reply."}
        skill_results = arguments.get("skill_results")
        legacy_result = arguments.get("result")
        if not isinstance(skill_results, dict):
            if len(state.loaded_skills) == 1 and isinstance(legacy_result, dict):
                skill_results = {str(state.loaded_skills[0].get("name")): legacy_result}
            else:
                return {"error": "submit_result requires skill_results keyed by skill id when multiple Skills are active."}
        resolved_decision = str(arguments.get("resolved_decision") or "").strip()
        conflicts = arguments.get("conflicts") or []
        if not isinstance(conflicts, list):
            return {"error": "conflicts must be an array of strings."}
        conflicts = [str(item).strip() for item in conflicts if str(item).strip()]
        draft_action_ids = arguments.get("draft_action_ids") or []
        if not isinstance(draft_action_ids, list):
            return {"error": "draft_action_ids must be an array of strings."}
        draft_action_ids = [str(item).strip() for item in draft_action_ids if str(item).strip()]
        staged_by_id = {str(item.get("staged_action_id") or ""): item for item in state.staged_actions}
        unknown_actions = [action_id for action_id in draft_action_ids if action_id not in staged_by_id]
        if unknown_actions:
            return {"error": "Unknown staged actions: " + ", ".join(unknown_actions)}
        if draft_action_ids and resolved_decision in {"HOLD", "INVESTIGATE"}:
            return {"error": "No draft can be committed while the resolved decision is HOLD or INVESTIGATE."}
        if len(state.loaded_skills) == 1 and not resolved_decision:
            only = skill_results.get(str(state.loaded_skills[0].get("name"))) or {}
            resolved_decision = str(only.get("decision") or only.get("verdict") or "")
        evidence_errors = _evidence_gate_errors(state, skill_results)
        output_errors = _output_contract_errors(state, skill_results, resolved_decision, conflicts)
        if evidence_errors or output_errors["missing_fields"] or output_errors["invalid_fields"] or output_errors["missing_conflicts"]:
            return {
                "error": "Output contract validation failed.",
                "missing_evidence": evidence_errors,
                **output_errors,
            }
        committed: list[dict[str, Any]] = []
        for action_id in draft_action_ids:
            draft = self.tools.commit_staged_action(staged_by_id[action_id])
            if isinstance(draft, dict) and draft.get("error"):
                return {"error": f"Staged action {action_id} could not be committed.", "draft_errors": [draft["error"]]}
            _append_draft(state, draft)
            committed.append(draft)
        state.submitted_result = {
            "reply": reply,
            "resolved_decision": resolved_decision,
            "skill_results": skill_results,
            "conflicts": conflicts,
            "draft_action_ids": draft_action_ids,
        }
        return {"final": True, "reply": reply, "result": state.submitted_result, "drafts": committed}


    def _read_skill_reference(self, arguments: dict[str, Any], state: AgentState) -> dict[str, Any]:
        skill_id = str(arguments.get("skill_id") or "").strip()
        reference_id = str(arguments.get("reference_id") or "").strip()
        if not skill_id or not reference_id:
            return {"error": "read_skill_reference requires skill_id and reference_id."}
        loaded_skill_ids = {str(item.get("name") or "") for item in state.loaded_skills}
        if skill_id not in loaded_skill_ids:
            return {"error": f"Load skill {skill_id} before reading its references."}
        loaded_keys = {(str(item.get("skill") or ""), str(item.get("reference") or "")) for item in state.loaded_references}
        if (skill_id, reference_id) not in loaded_keys:
            if len(state.loaded_references) >= self.skills.max_loaded_references:
                return {"error": f"At most {self.skills.max_loaded_references} references can be loaded in one turn."}
            try:
                result = self.skills.read_reference(skill_id, reference_id)
            except SkillCatalogError as exc:
                return {"error": str(exc)}
            state.loaded_references.append({"skill": skill_id, "reference": reference_id})
            return result
        try:
            return self.skills.read_reference(skill_id, reference_id)
        except SkillCatalogError as exc:
            return {"error": str(exc)}


def _input_gate_errors(
    name: str,
    arguments: dict[str, Any],
    state: AgentState,
    schema: dict[str, Any],
    selected_account_id: str,
) -> list[str]:
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    account_present = bool(
        str(arguments.get("ad_account_id") or arguments.get("account_id") or selected_account_id or "").strip()
    )
    window_present = bool(
        arguments.get("date_preset")
        or arguments.get("time_range")
        or (arguments.get("date_from") and arguments.get("date_to"))
    )
    errors: list[str] = []
    for item in state.loaded_skills:
        skill = str(item.get("name") or "")
        gates = item.get("input_gates") or {}
        if gates.get("account") and ("ad_account_id" in props or "account_id" in props) and not account_present:
            errors.append(f"{skill}: ad_account_id")
        if gates.get("date_window") and any(key in props for key in ("date_preset", "time_range", "date_from", "date_to")):
            if not window_present:
                errors.append(f"{skill}: date window")
        if gates.get("entity_level") and ("level" in props or "analysis_level" in props):
            if not (arguments.get("level") or arguments.get("analysis_level")):
                errors.append(f"{skill}: entity level")
        if gates.get("target_entity") and any(
            key in props for key in ("entity_id", "campaign_id", "ad_set_id", "adset_id", "ad_id")
        ):
            if not any(arguments.get(key) for key in ("entity_id", "campaign_id", "ad_set_id", "adset_id", "ad_id")):
                errors.append(f"{skill}: target entity")
        if gates.get("catalog_or_account") and ("catalog_id" in props or "ad_account_id" in props or "account_id" in props):
            if not (arguments.get("catalog_id") or account_present):
                errors.append(f"{skill}: catalog_id or account")
        if name == "ads_library_search" and gates.get("search_terms_or_page_ids"):
            if not (arguments.get("search_terms") or arguments.get("page_ids")):
                errors.append(f"{skill}: search_terms or page_ids")
        if name == "ads_library_search" and gates.get("countries") and not arguments.get("countries"):
            errors.append(f"{skill}: countries")
    return sorted(set(errors))


def _evidence_gate_errors(state: AgentState, skill_results: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for item in state.loaded_skills:
        skill = str(item.get("name") or "")
        result = skill_results.get(skill)
        if not isinstance(result, dict):
            errors.append(f"{skill}: missing skill result")
            continue
        gates = item.get("evidence_gates") or {}
        try:
            required = int(gates.get("min_reads") or 0)
        except (TypeError, ValueError):
            required = 0
        if len(state.read_tools) < required:
            errors.append(f"{skill}: successful read calls {len(state.read_tools)} < required {required}")
        requirements = item.get("evidence_requirements") or {}
        for field in requirements.get("required_fields") or []:
            if field not in result:
                errors.append(f"{skill}: evidence field {field}")
        source_tools = result.get("source_tools")
        if "source_tools" in (requirements.get("required_fields") or []):
            if not isinstance(source_tools, list) or not source_tools:
                errors.append(f"{skill}: source_tools must be a non-empty list")
            else:
                unsupported = sorted(str(tool) for tool in source_tools if str(tool) not in state.read_tools)
                if unsupported:
                    errors.append(f"{skill}: source_tools not read this turn: {', '.join(unsupported)}")
        any_tools = requirements.get("required_any_tools") or []
        if any_tools and not any(str(tool) in state.read_tools for tool in any_tools):
            errors.append(f"{skill}: required read tool missing from {list(any_tools)}")
    return errors


_LIVE_READ_ID_KEYS = {
    "id",
    "entity_id",
    "ad_object_id",
    "parent_ad_object_id",
    "campaign_id",
    "ad_set_id",
    "adset_id",
    "ad_id",
    "creative_id",
    "ad_creative_id",
}


def _build_live_read_evidence(
    name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
    selected_account_id: str,
) -> dict[str, Any]:
    raw_result = result.get("result") if isinstance(result, dict) else None
    account_id = _canonical_entity_id(
        str(arguments.get("ad_account_id") or arguments.get("account_id") or selected_account_id or "")
    )
    target_ids = _collect_entity_ids(raw_result)
    target_ids.update(
        _canonical_entity_id(str(arguments.get(key) or ""))
        for key in _LIVE_READ_ID_KEYS
        if arguments.get(key)
    )
    if account_id:
        target_ids.add(account_id)
    return {
        "tool": name,
        "account_id": account_id,
        "object_state": str(arguments.get("object_state") or "live").strip().lower() or "live",
        "target_ids": sorted(item for item in target_ids if item),
        "states_by_target": _collect_entity_states(raw_result),
        "date_window": {
            key: arguments.get(key)
            for key in ("date_preset", "time_range", "date_from", "date_to")
            if arguments.get(key)
        },
        "force_refresh": bool(arguments.get("force_refresh")),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def _collect_entity_ids(value: Any, depth: int = 0) -> set[str]:
    if depth > 5:
        return set()
    ids: set[str] = set()
    if isinstance(value, dict):
        for key, item in list(value.items())[:60]:
            normalized_key = str(key).lower()
            if normalized_key in _LIVE_READ_ID_KEYS and isinstance(item, (str, int)):
                candidate = _canonical_entity_id(str(item))
                if candidate:
                    ids.add(candidate)
            else:
                ids.update(_collect_entity_ids(item, depth + 1))
    elif isinstance(value, list):
        for item in value[:50]:
            ids.update(_collect_entity_ids(item, depth + 1))
    return ids


def _canonical_entity_id(value: str) -> str:
    text = str(value or "").strip()
    return text.removeprefix("act_") if text.startswith("act_") else text


_ENTITY_STATE_FIELDS = (
    "status",
    "validation_status",
    "action",
    "effective_status",
    "daily_budget",
    "lifetime_budget",
    "learning_state",
    "learning_stage_info",
    "impressions",
    "clicks",
    "reach",
    "results",
)


def _collect_entity_states(value: Any, depth: int = 0) -> dict[str, dict[str, Any]]:
    if depth > 5:
        return {}
    states: dict[str, dict[str, Any]] = {}
    if isinstance(value, dict):
        entity_id = ""
        for key in (
            "id",
            "entity_id",
            "ad_object_id",
            "campaign_id",
            "adset_id",
            "ad_set_id",
            "ad_id",
            "creative_id",
            "ad_creative_id",
        ):
            if value.get(key):
                entity_id = _canonical_entity_id(str(value[key]))
                break
        if entity_id:
            compact = {
                key: value[key]
                for key in _ENTITY_STATE_FIELDS
                if value.get(key) not in (None, "")
            }
            if compact:
                states.setdefault(entity_id, {}).update(compact)
        for item in list(value.values())[:60]:
            if len(states) >= 50:
                break
            for target_id, target_state in _collect_entity_states(item, depth + 1).items():
                states.setdefault(target_id, {}).update(target_state)
    elif isinstance(value, list):
        for item in value[:50]:
            for target_id, target_state in _collect_entity_states(item, depth + 1).items():
                states.setdefault(target_id, {}).update(target_state)
    return states


def _canonical_window(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("date_preset"):
            return _canonical_window(value["date_preset"])
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    text = str(value or "").strip().lower()
    aliases = {
        "previous_7d": "last_7d",
        "past_7d": "last_7d",
        "last_7_days": "last_7d",
    }
    return aliases.get(text, text)


def _state_value_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and _state_value_matches(actual[key], value) for key, value in expected.items())
    if isinstance(expected, (int, float)) or isinstance(actual, (int, float)):
        try:
            return float(actual) == float(expected)
        except (TypeError, ValueError):
            return False
    return str(actual or "").strip().casefold() == str(expected or "").strip().casefold()


def _learning_state(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("status", "learning_stage", "value"):
            if value.get(key) not in (None, ""):
                return str(value[key]).strip()
        return ""
    return str(value or "").strip()


def _verified_optimization_current_state(
    name: str,
    arguments: dict[str, Any],
    state: AgentState,
) -> tuple[dict[str, Any] | None, list[str]]:
    if not any(str(item.get("name") or "") == "optimization_draft" for item in state.loaded_skills):
        return None, []

    account_id = _canonical_entity_id(
        str(arguments.get("ad_account_id") or arguments.get("account_id") or state.account_id or "")
    )
    target_level, target_key = _draft_target(name, arguments)
    target_id = _canonical_entity_id(str(arguments.get(target_key) or ""))
    candidates = [
        item
        for item in state.live_read_evidence
        if bool(item.get("force_refresh"))
        and str(item.get("account_id") or "") == account_id
        and target_id in set(item.get("target_ids") or [])
    ]
    if not candidates:
        return None, [f"matching live read for current_state {target_level}:{target_id}"]
    evidence = candidates[-1]
    entity = (evidence.get("states_by_target") or {}).get(target_id)
    if not isinstance(entity, dict) or not entity:
        return None, [f"live read did not expose current state for {target_level}:{target_id}"]

    expected = arguments.get("current_state") if isinstance(arguments.get("current_state"), dict) else {}
    errors: list[str] = []

    status_values = [
        value
        for value in (entity.get("effective_status"), entity.get("status"))
        if value not in (None, "")
    ]
    expected_status = expected.get("current_status")
    selected_status = next(
        (value for value in status_values if _state_value_matches(value, expected_status)),
        status_values[0] if status_values else "",
    )
    if not selected_status:
        errors.append("live read did not expose current_state.current_status")
    elif expected_status not in (None, "") and not _state_value_matches(selected_status, expected_status):
        errors.append("current_state.current_status does not match live read")

    budget_values = [
        value
        for value in (entity.get("daily_budget"), entity.get("lifetime_budget"))
        if value not in (None, "")
    ]
    expected_budget = expected.get("current_budget")
    selected_budget = next(
        (value for value in budget_values if _state_value_matches(value, expected_budget)),
        budget_values[0] if budget_values else "",
    )
    if selected_budget in (None, ""):
        errors.append("live read did not expose current_state.current_budget")
    elif expected_budget not in (None, "") and not _state_value_matches(selected_budget, expected_budget):
        errors.append("current_state.current_budget does not match live read")

    sample_size = {
        key: entity[key]
        for key in ("impressions", "clicks", "reach", "results")
        if entity.get(key) not in (None, "")
    }
    expected_sample = expected.get("sample_size")
    if not sample_size:
        errors.append("live read did not expose current_state.sample_size")
    elif not isinstance(expected_sample, dict):
        errors.append("current_state.sample_size must be an object")
    else:
        for key, value in expected_sample.items():
            if key not in sample_size:
                errors.append(f"live read did not expose current_state.sample_size.{key}")
            elif not _state_value_matches(sample_size[key], value):
                errors.append(f"current_state.sample_size.{key} does not match live read")

    learning_state = _learning_state(entity.get("learning_state") or entity.get("learning_stage_info"))
    if not learning_state:
        errors.append("live read did not expose current_state.learning_state")
    elif expected.get("learning_state") not in (None, "") and not _state_value_matches(
        learning_state,
        expected.get("learning_state"),
    ):
        errors.append("current_state.learning_state does not match live read")

    comparison_window = _canonical_window(evidence.get("date_window"))
    if not comparison_window:
        errors.append("live read did not expose current_state.comparison_window")
    elif expected.get("comparison_window") not in (None, "") and not _state_value_matches(
        comparison_window,
        _canonical_window(expected.get("comparison_window")),
    ):
        errors.append("current_state.comparison_window does not match live read")

    if errors:
        return None, sorted(set(errors))
    return {
        "current_budget": selected_budget,
        "current_status": selected_status,
        "sample_size": sample_size,
        "learning_state": learning_state,
        "comparison_window": comparison_window,
    }, []


def _draft_mutation_evidence_errors(name: str, arguments: dict[str, Any], state: AgentState) -> list[str]:
    if not is_direct_draft_mutation_tool(name) or not bool(arguments.get("draft_only")):
        return []
    account_id = _canonical_entity_id(
        str(arguments.get("ad_account_id") or arguments.get("account_id") or state.account_id or "")
    )
    target_level, target_key = _draft_target(name, arguments)
    target_id = _canonical_entity_id(str(arguments.get(target_key) or ""))
    if not target_id:
        return [f"draft target {target_level} id"]
    candidates = [
        item
        for item in state.live_read_evidence
        if bool(item.get("force_refresh"))
        and str(item.get("account_id") or "") == account_id
        and str(item.get("object_state") or "") == "draft"
        and target_id in set(item.get("target_ids") or [])
    ]
    if not candidates:
        return [f"draft read with object_state=draft and force_refresh=true for draft target {target_level}:{target_id}"]
    status = str((candidates[-1].get("states_by_target") or {}).get(target_id, {}).get("status") or "").upper()
    if status not in {"EDITING", "VALIDATED"}:
        return [f"draft target {target_level}:{target_id} must have status EDITING or VALIDATED"]
    return []


def _draft_evidence_errors(name: str, arguments: dict[str, Any], state: AgentState) -> list[str]:
    errors: list[str] = []
    current_state = arguments.get("current_state")
    if not isinstance(current_state, dict) or not current_state:
        errors.append("current_state must be a non-empty object")

    draft_account = _canonical_entity_id(
        str(arguments.get("ad_account_id") or arguments.get("account_id") or state.account_id or "")
    )
    matching_account = [
        item
        for item in state.live_read_evidence
        if draft_account and str(item.get("account_id") or "") == draft_account
    ]
    refreshed = [item for item in matching_account if bool(item.get("force_refresh"))]
    if not state.live_read_evidence:
        errors.append("successful live read tool call")
    elif not matching_account:
        errors.append("successful live read tool call for draft account")
    elif not refreshed:
        errors.append("live read with force_refresh=true for draft account")

    target_level, target_key = _draft_target(name, arguments)
    target_id = _canonical_entity_id(str(arguments.get(target_key) or ""))
    if refreshed and target_level != "account" and target_id and target_id != "pending":
        if not any(target_id in set(item.get("target_ids") or []) for item in refreshed):
            errors.append(f"live read for draft target {target_level}:{target_id}")

    for item in state.loaded_skills:
        if str(item.get("name") or "") != "optimization_draft":
            continue
        required_keys = ("current_budget", "current_status", "sample_size", "learning_state", "comparison_window")
        if isinstance(current_state, dict):
            errors.extend(f"current_state.{key}" for key in required_keys if key not in current_state)
        requirements = item.get("evidence_requirements") or {}
        any_tools = requirements.get("required_any_tools") or []
        if any_tools and not any(str(tool) in state.read_tools for tool in any_tools):
            errors.append(f"required read tool missing from {list(any_tools)}")
    return sorted(set(errors))


def _output_contract_errors(
    state: AgentState,
    skill_results: dict[str, Any],
    resolved_decision: str,
    conflicts: list[str],
) -> dict[str, list[str]]:
    missing: list[str] = []
    invalid: list[str] = []
    missing_conflicts: list[str] = []
    allowed_modes: set[str] = set()
    differing: list[str] = []
    for item in state.loaded_skills:
        skill = str(item.get("name") or "")
        result = skill_results.get(skill)
        if not isinstance(result, dict):
            missing.append(f"{skill}.result")
            continue
        output = item.get("output_contract") or {}
        for field in output.get("required_fields") or []:
            if field not in result:
                missing.append(f"{skill}.{field}")
        modes = output.get("decision_modes") or []
        allowed_modes.update(str(mode) for mode in modes)
        for field in ("decision", "verdict"):
            if field in result and modes and result[field] not in modes:
                invalid.append(f"{skill}.{field}={result[field]!r}; allowed={list(modes)}")
        if "requires_approval" in (output.get("required_fields") or []) and not isinstance(result.get("requires_approval"), bool):
            invalid.append(f"{skill}.requires_approval must be boolean")
        skill_decision = str(result.get("decision") or result.get("verdict") or "")
        if skill_decision and resolved_decision and skill_decision != resolved_decision:
            differing.append(f"{skill}:{skill_decision}")
    if allowed_modes:
        if not resolved_decision:
            missing.append("resolved_decision")
        elif resolved_decision not in allowed_modes:
            invalid.append(f"resolved_decision={resolved_decision!r}; allowed={sorted(allowed_modes)}")
    if differing and not conflicts:
        missing_conflicts.append("conflicts explanation required for: " + ", ".join(differing))
    return {
        "missing_fields": sorted(set(missing)),
        "invalid_fields": sorted(set(invalid)),
        "missing_conflicts": missing_conflicts,
    }


def _output_requirements(state: AgentState) -> str:
    parts: list[str] = []
    for item in state.loaded_skills:
        output = item.get("output_contract") or {}
        parts.append(
            f"{item.get('name')}: fields={output.get('required_fields') or []}, "
            f"decision_modes={output.get('decision_modes') or []}"
        )
    return " | ".join(parts)


def _submit_result_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "submit_result",
        "description": "Submit final structured results. Multiple active Skills use skill_results keyed by skill id and a model-chosen resolved_decision. Conflicts must be explained.",
        "parameters": {
            "type": "object",
            "properties": {
                "reply": {"type": "string", "description": "Short user-facing final answer."},
                "skill_results": {
                    "type": "object",
                    "additionalProperties": {"type": "object"},
                    "description": "Map from skill id to that Skill's validated result object.",
                },
                "resolved_decision": {"type": "string", "description": "Model-selected final decision or verdict after comparing all Skill results."},
                "conflicts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Short explanations for differing per-Skill decisions.",
                },
                "draft_action_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Staged action ids to commit as local drafts after the final decision passes validation.",
                },
                "result": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Legacy single-Skill result object.",
                },
            },
            "required": ["reply"],
        },
    }


def _save_memory_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "save_memory",
        "description": "Save a durable user or account Memory when the user states a preference, habit, confirmed decision, account profile, or completed outcome. Inferred memories remain candidates unless supported by an exact source quote.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["preference", "habit", "decision", "account_profile", "outcome"]},
                "scope": {"type": "string", "enum": ["user", "account"]},
                "content": {"type": "string", "description": "Concise durable memory content."},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "source_quote": {"type": "string", "description": "Exact supporting quote from the conversation when available."},
                "supersedes_memory_id": {"type": "string", "description": "Existing memory id superseded by this correction."},
            },
            "required": ["kind", "scope", "content"],
        },
    }


def _update_task_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "update_task",
        "description": "Update the current task goal, progress, next step, blockers, constraints, or completion status. Use it whenever the task advances materially.",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "status": {"type": "string", "enum": ["active", "paused", "completed"]},
                "completed_steps": {"type": "array", "items": {"type": "string"}},
                "next_step": {"type": "string"},
                "blocker_summary": {"type": "string"},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "progress": {"type": "object", "additionalProperties": True},
            },
            "required": [],
        },
    }

def _load_skill_tool(entries: list[dict[str, str]]) -> dict[str, Any]:
    skill_ids = [str(entry.get("id") or "") for entry in entries if entry.get("id")]
    return {
        "type": "function",
        "name": "load_skill",
        "description": "Load one or more project skills from the closed catalog. Call before Meta tools; at most eight skills per turn.",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "enum": skill_ids},
                "skill_ids": {
                    "type": "array",
                    "items": {"type": "string", "enum": skill_ids},
                    "maxItems": 8,
                    "description": "Batch form for multi-intent requests. Use one or more ids.",
                },
                "reason": {"type": "string", "description": "Short reason these skills fit the request."},
            },
            "required": [],
        },
    }


def _read_skill_reference_tool(entries: list[dict[str, str]]) -> dict[str, Any]:
    skill_ids = [str(entry.get("id") or "") for entry in entries if entry.get("id")]
    return {
        "type": "function",
        "name": "read_skill_reference",
        "description": "Read one reference from a skill already loaded in this turn. Reference content is loaded only on demand.",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "enum": skill_ids},
                "reference_id": {"type": "string", "description": "Reference id from the loaded skill reference index."},
            },
            "required": ["skill_id", "reference_id"],
        },
    }


def _record_tool_search(state: AgentState, output_items: list[dict[str, Any]]) -> None:
    loaded: list[str] = []
    for item in output_items:
        if item.get("type") != "tool_search_output":
            continue
        for namespace in item.get("tools") or []:
            for tool in namespace.get("tools") or []:
                if isinstance(tool, dict) and tool.get("name"):
                    loaded.append(str(tool["name"]))
    for item in output_items:
        if item.get("type") != "tool_search_call":
            continue
        arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
        state.trace.append(
            {
                "step": state.step,
                "tool": "tool_search",
                "arguments": _compact_arguments(arguments),
                "result": {"tools_loaded": loaded[:20], "count": len(loaded)},
            }
        )


def _append_draft(state: AgentState, result: dict[str, Any]) -> None:
    state.drafts.append(
        {
            "draft_id": str(result.get("draft_id") or ""),
            "action_id": str(result.get("action_id") or ""),
            "status": str(result.get("draft_status") or "draft"),
            "requires_approval": bool(result.get("requires_approval")),
            "target_level": str(result.get("target_level") or ""),
            "target_id": str(result.get("target_id") or ""),
            "target_name": str(result.get("target_name") or ""),
            "evidence": str(result.get("evidence") or ""),
            "recommendation": str(result.get("recommendation") or ""),
            "risk_level": str(result.get("risk_level") or ""),
            "preflight": result.get("preflight") if isinstance(result.get("preflight"), dict) else {},
        }
    )


def _result(state: AgentState, reply: str, stopped_reason: str) -> dict[str, Any]:
    tools_used = [str(item.get("tool") or "") for item in state.trace]
    skills_loaded = [str(item.get("name") or "") for item in state.loaded_skills if item.get("name")]
    references_loaded = [f"{item.get('skill')}.{item.get('reference')}" for item in state.loaded_references]
    used_meta = any(tool not in LOCAL_TRACE_TOOLS for tool in tools_used)
    intent_type = "action" if (state.drafts or state.direct_drafts) else ("read_data" if used_meta else "chat")
    return {
        "reply": reply,
        "trace": state.trace,
        "drafts": state.drafts,
        "direct_drafts": state.direct_drafts,
        "direct_draft_mutations": state.direct_draft_mutations,
        "tool_calls": tools_used,
        "skills_loaded": skills_loaded,
        "references_loaded": references_loaded,
        "structured_result": state.submitted_result or {},
        "steps": state.step,
        "stopped_reason": stopped_reason,
        "intent_type": intent_type,
        "context_manifest": state.context_manifest,
        "summary_update": state.summary_update or {},
        "memory_writes": state.memory_writes,
        "task_update": state.task_update,
        "tool_ledger": state.tool_ledger,
    }


def _parse_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError as exc:
        return {"__argument_parse_error__": str(exc)[:300]}
    if not isinstance(parsed, dict):
        return {"__argument_parse_error__": "arguments must be a JSON object"}
    return parsed


def _context_block(account_id: str, frontend_context: dict[str, Any] | None) -> str:
    frontend = frontend_context or {}
    lines = ["Runtime context:"]
    if account_id:
        lines.append(f"- selected_account_id: {account_id}")
    if frontend.get("current_mode"):
        lines.append(f"- current_mode: {frontend.get('current_mode')}")
    if not account_id:
        lines.append("- No account is selected. Use ads_get_ad_accounts or ask_user.")
    return "\n".join(lines)


def _ledger_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): _ledger_value(value)
        for key, value in list(arguments.items())[:24]
        if not _is_sensitive_key(key)
    }


def _ledger_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {
            str(key): _ledger_value(item)
            for key, item in list(value.items())[:24]
            if not _is_sensitive_key(key)
        }
    if isinstance(value, list):
        return [_ledger_value(item) for item in value[:24]]
    return str(value)[:1000]

def _compact_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): _compact_value(value)
        for key, value in list(arguments.items())[:12]
        if not _is_sensitive_key(key)
    }


def _compact_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"preview": _compact_value(result)}
    if "error" in result:
        payload = {"error": _safe_short_text(str(result["error"]), 500)}
        for key in ("missing_inputs", "missing_evidence", "missing_fields", "invalid_fields", "missing_conflicts", "schema_errors", "confirmation_required", "confirmation_phrase"):
            if key in result:
                payload[key] = _compact_value(result[key])
        return payload
    if "needs_user_input" in result:
        return {"needs_user_input": True, "question": _safe_short_text(str(result.get("question") or ""), 500)}
    if "staged_action_id" in result:
        return {
            "staged_action_id": result.get("staged_action_id"),
            "status": result.get("status"),
            "tool": result.get("tool"),
            "target_id": result.get("target_id"),
        }
    if result.get("draft_mode") and "created" in result:
        return {
            "tool": result.get("tool"),
            "created": bool(result.get("created")),
            "published": False,
            "status": result.get("status") or "DRAFT",
            "meta_draft_status": result.get("meta_draft_status"),
            "created_entity_id": result.get("created_entity_id"),
            "error": result.get("error"),
        }
    if "draft_id" in result:
        return {
            "draft_id": result.get("draft_id"),
            "draft_status": result.get("draft_status"),
            "requires_approval": result.get("requires_approval"),
            "action_record": result.get("action_record") or {},
        }
    if result.get("final"):
        payload = result.get("result") if isinstance(result.get("result"), dict) else {}
        return {
            "submitted": True,
            "resolved_decision": payload.get("resolved_decision"),
            "skill_count": len(payload.get("skill_results") or {}),
            "conflict_count": len(payload.get("conflicts") or []),
        }
    if "instructions" in result and "name" in result:
        return {
            "skill": result.get("name"),
            "version": result.get("version"),
            "read_tool_count": len(result.get("read_tools") or []),
            "draft_tool_count": len(result.get("draft_tools") or []),
            "reference_count": len(result.get("references") or []),
            "instruction_chars": len(str(result.get("instructions") or "")),
        }
    if "memory_candidate" in result:
        return {"saved": True, "memory": result.get("memory_candidate")}
    if "task_update" in result:
        return {"updated": bool(result.get("updated")), "task_keys": list((result.get("task_update") or {}).keys())}
    if "reference" in result and "content" in result:
        return {
            "skill": result.get("skill"),
            "reference": result.get("reference"),
            "chars": result.get("chars"),
            "truncated": bool(result.get("truncated")),
        }
    if "tool" in result and "result" in result:
        payload = {"tool": result.get("tool"), "summary": _summarize_mcp_result(result.get("result")), "truncated": bool(result.get("truncated"))}
        if isinstance(result.get("_cache"), dict):
            payload["cache"] = {key: result["_cache"].get(key) for key in ("hit", "fresh", "stale", "fetched_at", "fallback")}
        return payload
    return {"keys": list(result)[:12]}


def _summarize_mcp_result(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return {"type": "list", "count": len(value), "sample": _compact_value(value[:3])}
    if isinstance(value, dict):
        data = value.get("data")
        if isinstance(data, list):
            return {"type": "list", "count": len(data), "sample": _compact_value(data[:3])}
        media = value.get("media")
        if isinstance(media, list):
            return {"media_count": len(media), "media": _compact_value(media[:3])}
        return {"keys": list(value)[:12], "preview": _compact_value(value)}
    return {"preview": _compact_value(value)}


def _compact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_short_text(value, 300)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {
            str(key): _compact_value(item)
            for key, item in list(value.items())[:8]
            if not _is_sensitive_key(key)
        }
    if isinstance(value, list):
        return [_compact_value(item) for item in value[:5]]
    return _safe_short_text(str(value), 200)


def _is_sensitive_key(key: Any) -> bool:
    lowered = str(key).lower()
    return lowered == "token" or any(marker in lowered for marker in SENSITIVE_ARGUMENT_MARKERS)


def _safe_short_text(value: str, limit: int) -> Any:
    lowered = value.strip().lower()
    if lowered.startswith("data:") or "base64," in lowered[:160]:
        return {"data_omitted": True, "chars": len(value)}
    if (
        lowered.startswith("bearer ")
        or "authorization:" in lowered
        or "set-cookie:" in lowered
        or "access_token" in lowered
        or "api_key" in lowered
        or "client_secret" in lowered
        or "sk-" in lowered
    ):
        return "[redacted]"
    return value[:limit]


def _emit_event(
    on_event: TurnEventHandler | None,
    event_name: str,
    payload: dict[str, Any],
) -> None:
    if on_event is None:
        return
    try:
        on_event(event_name, payload)
    except Exception:
        return
