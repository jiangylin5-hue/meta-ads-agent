from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..agent.runtime import AgentRuntime
from ..integrations.meta_ads import MetaAdsProvider
from ..models import AgentTurnRequest
from .account_cache import AccountCacheService
from .account_gateway import gateway_for
from .long_term_memory import DEFAULT_USER_ID, LongTermMemoryService
from .session_store import (
    SessionState,
    active_task_id,
    append_message,
    apply_summary_update,
    history,
    set_active_task,
    summary,
)
from .task_state import TaskStateService, task_for_context
from .trace_service import append_trace, start_trace


TurnEventHandler = Callable[[str, dict[str, Any]], None]
DRAFT_CONFIRMATION_PHRASE = "确认创建草稿"


@dataclass
class AgentTurnExecution:
    """Shared JSON/SSE execution path for one persisted agent turn."""

    request: AgentTurnRequest
    message: str
    session_id: str
    state: SessionState
    turn_id: str

    def prepare(self) -> "AgentTurnExecution":
        self.prior_history = [
            item
            for item in history(self.state)
            if str((item.get("metadata") or {}).get("turn_id") or "") != self.turn_id
        ]
        self.user_id = str(self.request.frontend_context.get("user_id") or DEFAULT_USER_ID).strip() or DEFAULT_USER_ID
        self.task_service = TaskStateService()
        self.task = self.task_service.get_or_create(
            session_id=self.session_id,
            account_id=self.request.account_id,
            goal=self.message,
            task_id=active_task_id(self.state),
        )
        set_active_task(self.state, str(self.task.get("id") or ""))
        self.user_message_id = append_message(
            self.state,
            "user",
            self.message,
            metadata={
                "account_id": self.request.account_id,
                "task_id": self.task.get("id"),
                "user_id": self.user_id,
                "source": "agent_turn",
            },
            turn_id=self.turn_id,
        )
        self.trace_id = start_trace(
            "agent_turn",
            {
                "session_id": self.session_id,
                "message": self.message,
                "account_id": self.request.account_id,
                "task_id": self.task.get("id"),
                "turn_id": self.turn_id,
            },
        )
        return self

    def started_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_message_id": self.user_message_id,
            "task_id": str(self.task.get("id") or ""),
        }

    def execute(self, on_event: TurnEventHandler | None = None) -> dict[str, Any]:
        if on_event is not None:
            on_event("turn.started", self.started_payload())

        memory_service = LongTermMemoryService()
        try:
            memory_used = memory_service.context_for(
                user_id=self.user_id,
                account_id=self.request.account_id,
                query=self.message,
                task_state=task_for_context(self.task),
            )
        except Exception:
            memory_used = []
        account_context: dict[str, Any] = {}
        if self.request.account_id:
            try:
                account_context = AccountCacheService().for_turn(
                    self.request.account_id,
                    gateway_for("meta", MetaAdsProvider()),
                )
            except Exception as exc:
                account_context = {
                    "account_id": self.request.account_id,
                    "freshness": "unavailable",
                    "as_of": "",
                    "missing_data": [f"Account context unavailable: {type(exc).__name__}"],
                }

        runtime = AgentRuntime()
        task_context = task_for_context(self.task)
        pending_confirmation = bool((task_context.get("progress") or {}).get("pending_draft_confirmation"))
        runtime_kwargs: dict[str, Any] = {
            "message": self.message,
            "history": self.prior_history,
            "account_id": self.request.account_id,
            "frontend_context": self.request.frontend_context,
            "summary": summary(self.state),
            "task_state": task_context,
            "memories": memory_used,
            "account_context": account_context,
            "active_skill_ids": list(self.task.get("active_skill_ids") or []),
            "session_id": self.session_id,
            "task_id": str(self.task.get("id") or ""),
            "user_message_id": self.user_message_id,
            "draft_creation_authorized": pending_confirmation and is_explicit_draft_confirmation(self.message),
        }
        def emit_runtime_event(event_name: str, payload: dict[str, Any]) -> None:
            if event_name.startswith("model."):
                append_trace(self.trace_id, event_name, payload)
            if on_event is not None:
                on_event(event_name, payload)

        runtime_kwargs["on_event"] = emit_runtime_event
        result = runtime.run_turn(**runtime_kwargs)
        return self._persist_result(result, memory_service, memory_used, account_context)

    def record_failure(self, error_code: str) -> None:
        try:
            append_trace(self.trace_id, "turn_failed", {"code": error_code})
        except Exception:
            return

    def _persist_result(
        self,
        result: dict[str, Any],
        memory_service: LongTermMemoryService,
        memory_used: list[dict[str, Any]],
        account_context: dict[str, Any],
    ) -> dict[str, Any]:
        reply = str(result.get("reply") or "").strip() or "I need one more detail to continue."
        assistant_message_id = append_message(
            self.state,
            "assistant",
            reply,
            metadata={
                "account_id": self.request.account_id,
                "task_id": self.task.get("id"),
                "turn_id": self.turn_id,
                "user_id": self.user_id,
                "trace_id": self.trace_id,
                "skills_loaded": result.get("skills_loaded") or [],
                "tool_calls": result.get("tool_calls") or [],
                "context_manifest": result.get("context_manifest") or {},
            },
            turn_id=self.turn_id,
        )
        apply_summary_update(
            self.state,
            result.get("summary_update") if isinstance(result.get("summary_update"), dict) else {},
        )

        memory_writes = result.get("memory_writes") if isinstance(result.get("memory_writes"), list) else []
        saved_memories: list[dict[str, Any]] = []
        if memory_writes:
            try:
                saved_memories = memory_service.remember_many(
                    memory_writes,
                    user_id=self.user_id,
                    account_id=self.request.account_id,
                    session_id=self.session_id,
                    user_message_id=self.user_message_id,
                )
            except Exception:
                saved_memories = []

        stopped_reason = str(result.get("stopped_reason") or "")
        task_update = dict(result.get("task_update") or {}) if isinstance(result.get("task_update"), dict) else {}
        progress_update = dict(task_update.get("progress") or {}) if isinstance(task_update.get("progress"), dict) else {}
        draft_objects_touched = bool(result.get("direct_drafts") or result.get("direct_draft_mutations"))
        if draft_objects_touched:
            progress_update["pending_draft_confirmation"] = False
            progress_update.pop("draft_plan_summary", None)
        elif "campaign_plan" in (result.get("skills_loaded") or []) and DRAFT_CONFIRMATION_PHRASE in reply:
            progress_update["pending_draft_confirmation"] = True
            progress_update["draft_plan_summary"] = reply[:2000]
        if progress_update:
            task_update["progress"] = progress_update
        task_after = self.task_service.apply_turn(
            self.task,
            task_update=task_update,
            trace=result.get("tool_ledger") if isinstance(result.get("tool_ledger"), list) else (result.get("trace") or []),
            skills_loaded=result.get("skills_loaded") or [],
            user_message=self.message,
            reply=reply,
            stopped_reason=stopped_reason,
            turn_id=self.turn_id,
        )
        manifest = result.get("context_manifest") if isinstance(result.get("context_manifest"), dict) else {}
        append_trace(self.trace_id, "context_manifest", manifest)
        append_trace(
            self.trace_id,
            "memory_updated",
            {"used": public_memories(memory_used), "saved": public_memories(saved_memories)},
        )
        append_trace(self.trace_id, "task_updated", task_for_context(task_after))
        for item in result.get("trace", []):
            append_trace(self.trace_id, "agent_tool_call", item)

        drafts = list(result.get("drafts") or [])
        direct_drafts = list(result.get("direct_drafts") or [])
        direct_draft_mutations = list(result.get("direct_draft_mutations") or [])
        intent_type = str(result.get("intent_type") or "chat")
        presentation = "action_cards" if (drafts or direct_drafts) else ("dashboard" if intent_type == "read_data" else "chat")
        visible_steps = [
            {
                "agent": "Agent",
                "title": f"Called {item.get('tool') or 'tool'}",
                "status": "completed",
                "detail": tool_detail(item),
            }
            for item in result.get("trace", [])
        ]
        if not visible_steps:
            visible_steps = [{"agent": "Agent", "title": "Direct answer", "status": "completed", "detail": "No tool was called in this turn."}]
        missing_data = [
            str(item.get("result", {}).get("error"))
            for item in result.get("trace", [])
            if isinstance(item.get("result"), dict) and item["result"].get("error")
        ]
        if account_context.get("freshness") == "stale":
            missing_data.append("Account data came from a stale cache; as_of is provided.")
        decision_card = {
            "intent_type": intent_type,
            "judgement": reply,
            "facts": [f"{item.get('tool')} returned a compact observation." for item in result.get("trace", [])],
            "assumptions": [],
            "missing_data": missing_data,
            "recommendation": reply,
            "draft_actions": drafts,
            "risk": "Action drafts require approval and final confirmation." if drafts else "",
            "requires_approval": bool(drafts),
            "next_action": "review_action_draft" if drafts else "answer_user",
        }
        return {
            "session_id": self.session_id,
            "status": "completed",
            "reply": reply,
            "intent_type": intent_type,
            "presentation_mode": presentation,
            "visible_agent_steps": visible_steps,
            "decision_card": decision_card,
            "drafts": drafts,
            "direct_drafts": direct_drafts,
            "direct_draft_mutations": direct_draft_mutations,
            "trace": result.get("trace", []),
            "steps": result.get("steps", 0),
            "stopped_reason": stopped_reason,
            "skills_loaded": result.get("skills_loaded", []),
            "references_loaded": result.get("references_loaded", []),
            "structured_result": result.get("structured_result", {}),
            "context_manifest": manifest,
            "task_state": task_for_context(task_after),
            "memory_used": public_memories(memory_used),
            "memory_saved": public_memories(saved_memories),
            "account_context": public_account_context(account_context),
            "user_message_id": self.user_message_id,
            "assistant_message_id": assistant_message_id,
            "trace_id": self.trace_id,
            "turn_id": self.turn_id,
            "runtime": "react",
        }


def is_explicit_draft_confirmation(message: str) -> bool:
    normalized = " ".join(str(message or "").strip().lower().split())
    return (
        DRAFT_CONFIRMATION_PHRASE in normalized
        or "confirm create draft" in normalized
        or "confirm draft creation" in normalized
    )


def public_memories(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(item.get("id") or ""),
            "kind": str(item.get("kind") or ""),
            "scope_type": str(item.get("scope_type") or ""),
            "scope_id": str(item.get("scope_id") or ""),
            "content": str(item.get("content") or "")[:1000],
            "status": str(item.get("status") or ""),
            "confidence": item.get("confidence"),
            "updated_at": str(item.get("updated_at") or ""),
        }
        for item in rows
        if isinstance(item, dict)
    ]


def public_account_context(context: dict[str, Any]) -> dict[str, Any]:
    if not context:
        return {}
    return {
        "account_id": context.get("account_id"),
        "name": context.get("name"),
        "freshness": context.get("freshness"),
        "as_of": context.get("as_of"),
        "source_tools": context.get("source_tools") or [],
        "missing_data": context.get("missing_data") or [],
    }


def tool_detail(item: dict[str, Any]) -> str:
    result = item.get("result") if isinstance(item.get("result"), dict) else {}
    if result.get("error"):
        return str(result["error"])[:300]
    if result.get("staged_action_id"):
        return f"staged_action_id={result.get('staged_action_id')} status={result.get('status')}"
    if result.get("draft_id"):
        return f"draft_id={result.get('draft_id')} status={result.get('draft_status')}"
    if result.get("submitted"):
        keys = ", ".join(str(key) for key in result.get("result_keys", [])[:8])
        return f"validated_result_keys={keys}"
    if result.get("tools_loaded"):
        loaded = ", ".join(str(name) for name in result.get("tools_loaded", [])[:8])
        return f"loaded={loaded}"
    if result.get("skill"):
        if result.get("reference"):
            return f"skill={result.get('skill')} reference={result.get('reference')} chars={result.get('chars') or 0}"
        return f"skill={result.get('skill')} version={result.get('version') or '-'}"
    if result.get("memory"):
        memory = result.get("memory") if isinstance(result.get("memory"), dict) else {}
        return f"memory_saved={memory.get('kind')} scope={memory.get('scope')}"
    if result.get("task_update"):
        return "task_progress_updated=" + ", ".join(result.get("task_keys") or [])
    if result.get("draft_mode") and "created" in result:
        return f"created_entity_id={result.get('created_entity_id') or '-'} status={result.get('status') or 'DRAFT'} draft_status={result.get('meta_draft_status') or '-'} published=false"
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    cache = result.get("cache") if isinstance(result.get("cache"), dict) else {}
    suffix = " cache=fresh" if cache.get("hit") and not cache.get("stale") else (" cache=stale" if cache.get("stale") else "")
    if "count" in summary:
        return f"count={summary.get('count')}{suffix}"
    if "media_count" in summary:
        return f"media_count={summary.get('media_count')}{suffix}"
    if "count" in result:
        return f"count={result.get('count')}{suffix}"
    return suffix.strip()


__all__ = [
    "AgentTurnExecution",
    "DRAFT_CONFIRMATION_PHRASE",
    "TurnEventHandler",
    "is_explicit_draft_confirmation",
    "public_account_context",
    "public_memories",
    "tool_detail",
]
