from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..repositories.task_repository import TaskRepository, TaskVersionConflict


TASK_STATUSES = {"active", "paused", "completed"}
DEFAULT_TASK_TTL_DAYS = 7


class TaskStateService:
    def __init__(self, repository: TaskRepository | None = None) -> None:
        self.repository = repository or TaskRepository()

    def get_or_create(
        self,
        *,
        session_id: str,
        account_id: str,
        goal: str,
        task_id: str = "",
        active_skill_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if task_id:
            task = self.repository.get(task_id)
            if task and task.get("status") == "active" and not _task_expired(task):
                if task.get("account_id") == account_id or not account_id:
                    return task
        task = self.repository.find_active(session_id, account_id)
        if task:
            return task
        self.repository.pause_active_for_session(session_id)
        return self.repository.create(
            session_id=session_id,
            account_id=account_id,
            goal=goal,
            active_skill_ids=active_skill_ids,
        )

    def pause_session(self, session_id: str) -> None:
        self.repository.pause_active_for_session(session_id)

    def apply_turn(
        self,
        task: dict[str, Any],
        *,
        task_update: dict[str, Any] | None,
        trace: list[dict[str, Any]],
        skills_loaded: list[str],
        user_message: str,
        reply: str,
        stopped_reason: str,
        turn_id: str = "",
    ) -> dict[str, Any]:
        task_id = str(task.get("id") or "")
        if not task_id:
            return task
        progress = dict(task.get("progress") or {})
        if turn_id and str(progress.get("last_turn_id") or "") == turn_id:
            return task
        recent = progress.get("recent") if isinstance(progress.get("recent"), list) else []
        recent.append(
            {
                "user": user_message[:800],
                "assistant": reply[:800],
                "stopped_reason": stopped_reason,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        progress["turn_count"] = int(progress.get("turn_count") or 0) + 1
        progress["recent"] = recent[-8:]
        if turn_id:
            progress["last_turn_id"] = turn_id
        update = dict(task_update or {})
        if isinstance(update.get("progress"), dict):
            progress.update(update["progress"])
        completed_steps = update.get("completed_steps")
        if isinstance(completed_steps, list) and completed_steps:
            progress["completed_steps"] = list(dict.fromkeys([*(progress.get("completed_steps") or []), *[str(item)[:500] for item in completed_steps]]))[-20:]
        for key in ("next_step", "blocker_summary"):
            if update.get(key):
                progress[key] = str(update[key])[:1000]
        constraints = list(task.get("constraints") or [])
        if isinstance(update.get("constraints"), list):
            constraints = list(dict.fromkeys([*constraints, *[str(item)[:500] for item in update["constraints"]]]))[-24:]
        tool_ledger = list(task.get("tool_ledger") or [])
        for item in trace:
            if not isinstance(item, dict):
                continue
            tool_ledger.append(
                {
                    "step": item.get("step"),
                    "tool": str(item.get("tool") or ""),
                    "arguments": item.get("arguments") if isinstance(item.get("arguments"), dict) else {},
                    "result": item.get("result") if isinstance(item.get("result"), dict) else {},
                }
            )
        active_skill_ids = list(dict.fromkeys([*(task.get("active_skill_ids") or []), *skills_loaded]))[:8]
        status = str(update.get("status") or task.get("status") or "active")
        if status not in TASK_STATUSES:
            status = "active"
        goal = str(update.get("goal") or task.get("goal") or "").strip()
        return self.repository.update(
            task_id,
            goal=goal,
            status=status,
            progress=progress,
            constraints=constraints,
            tool_ledger=tool_ledger[-40:],
            active_skill_ids=active_skill_ids,
            metadata={**(task.get("metadata") or {}), "last_stopped_reason": stopped_reason},
            expires_at=datetime.now(timezone.utc) + timedelta(days=DEFAULT_TASK_TTL_DAYS),
            expected_version=int(task.get("version") or 1),
        ) or task


def validate_task_update(arguments: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    status = str(arguments.get("status") or "").strip()
    if status and status not in TASK_STATUSES:
        return None, f"status must be one of {sorted(TASK_STATUSES)}"
    update: dict[str, Any] = {}
    for key in ("goal", "next_step", "blocker_summary"):
        value = str(arguments.get(key) or "").strip()
        if value:
            update[key] = value[:1000]
    for key in ("completed_steps", "constraints"):
        value = arguments.get(key)
        if isinstance(value, list):
            update[key] = [str(item)[:500] for item in value if str(item).strip()][:20]
    progress = arguments.get("progress")
    if isinstance(progress, dict):
        update["progress"] = {str(key): value for key, value in list(progress.items())[:20]}
    if status:
        update["status"] = status
    if not update:
        return None, "update_task requires at least one field"
    return update, ""


def _task_expired(task: dict[str, Any]) -> bool:
    value = task.get("expires_at")
    if not value:
        return False
    try:
        expires_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if not expires_at.tzinfo:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


def task_for_context(task: dict[str, Any] | None) -> dict[str, Any]:
    if not task:
        return {}
    return {
        "task_id": task.get("id"),
        "account_id": task.get("account_id"),
        "goal": task.get("goal"),
        "status": task.get("status"),
        "progress": task.get("progress") or {},
        "constraints": task.get("constraints") or [],
        "active_skill_ids": task.get("active_skill_ids") or [],
        "tool_ledger": (task.get("tool_ledger") or [])[-12:],
        "updated_at": task.get("updated_at"),
    }


__all__ = ["TaskStateService", "TASK_STATUSES", "TaskVersionConflict", "task_for_context", "validate_task_update"]