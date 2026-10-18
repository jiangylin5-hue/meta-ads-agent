from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..agent.context import DEFAULT_RECENT_ROUNDS, split_recent_rounds
from ..repositories.session_repository import SessionRepository, SessionVersionConflict


VISIBLE_HISTORY_DEFAULT_LIMIT = 50
MAX_STATE_HISTORY_MESSAGES = 60


class SessionState(dict):
    def __init__(self, session_id: str, *args: Any, version: int = 0, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.session_id = session_id
        self.version = int(version)


def get_or_create_session(session_id: str = "") -> tuple[str, SessionState]:
    sid = session_id or uuid4().hex
    repo = SessionRepository()
    record = repo.get_record(sid)
    if record is None:
        state = SessionState(sid, _empty_state(), version=0)
        state.version = repo.save_state(sid, dict(state), expected_version=0)
        return sid, state
    state_data, version = record
    return sid, SessionState(sid, state_data, version=version)


def append_message(
    state: SessionState,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    turn_id: str = "",
) -> str:
    safe_metadata = clean_metadata(metadata or {})
    if turn_id:
        safe_metadata["turn_id"] = turn_id
    repo = SessionRepository()
    existing = repo.get_message_for_turn(state.session_id, turn_id, role) if turn_id else None
    if existing:
        message_id = str(existing.get("id") or "")
        history_items = state.setdefault("history", [])
        if message_id and not any(str(item.get("id") or "") == message_id for item in history_items):
            history_items.append(
                {
                    "id": message_id,
                    "role": str(existing.get("role") or role),
                    "content": str(existing.get("content") or content),
                    "metadata": existing.get("metadata_json") if isinstance(existing.get("metadata_json"), dict) else {},
                    "created_at": existing.get("created_at").isoformat()
                    if hasattr(existing.get("created_at"), "isoformat")
                    else str(existing.get("created_at") or ""),
                }
            )
            _save_state(state)
        return message_id
    message_id = repo.append_message(state.session_id, role, content, metadata=safe_metadata)
    history_items = state.setdefault("history", [])
    history_items.append(
        {
            "id": message_id,
            "role": role,
            "content": content,
            "metadata": safe_metadata,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if len(history_items) > MAX_STATE_HISTORY_MESSAGES:
        del history_items[:-MAX_STATE_HISTORY_MESSAGES]
    _save_state(state)
    return message_id


def history(state: SessionState) -> list[dict[str, Any]]:
    return [dict(item) for item in state.get("history", []) if isinstance(item, dict)]


def summary(state: SessionState) -> dict[str, Any]:
    value = state.get("compressed_context")
    return dict(value) if isinstance(value, dict) else {}


def apply_summary_update(state: SessionState, summary_update: dict[str, Any] | None) -> None:
    if not isinstance(summary_update, dict) or not summary_update:
        return
    state["compressed_context"] = dict(summary_update)
    older, recent = split_recent_rounds(history(state), DEFAULT_RECENT_ROUNDS)
    if older:
        state["history"] = recent
    _save_state(state)


def trim_to_recent_rounds(state: SessionState, rounds: int = DEFAULT_RECENT_ROUNDS) -> None:
    _, recent = split_recent_rounds(history(state), rounds)
    if len(recent) != len(history(state)):
        state["history"] = recent
        _save_state(state)


def set_active_task(state: SessionState, task_id: str) -> None:
    state["active_task_id"] = str(task_id or "")
    _save_state(state)


def active_task_id(state: SessionState) -> str:
    return str(state.get("active_task_id") or "")


def visible_history(
    state: SessionState,
    limit: int = VISIBLE_HISTORY_DEFAULT_LIMIT,
    before: datetime | None = None,
) -> list[dict[str, Any]]:
    rows = SessionRepository().list_messages(state.session_id, limit=limit, before=before)
    if not rows:
        return history(state)
    return [
        {
            "id": str(row.get("id") or ""),
            "role": str(row.get("role") or ""),
            "content": str(row.get("content") or ""),
            "metadata": row.get("metadata_json") if isinstance(row.get("metadata_json"), dict) else {},
            "created_at": row.get("created_at").isoformat()
            if hasattr(row.get("created_at"), "isoformat")
            else str(row.get("created_at") or ""),
        }
        for row in rows
    ]


def reset_session(session_id: str) -> None:
    SessionRepository().reset_state(session_id, _empty_state())


def clean_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {"access_token", "token", "cookie", "cookies", "data_url", "authorization", "password"}:
                continue
            output[str(key)] = clean_metadata(item)
        return output
    if isinstance(value, list):
        return [clean_metadata(item) for item in value[:50]]
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered.startswith("data:") or "base64," in lowered[:120]:
            return {"data_omitted": True, "chars": len(value)}
        return value[:8_000]
    return value


def _empty_state() -> dict[str, Any]:
    return {"history": [], "compressed_context": {}, "active_task_id": ""}


def _save_state(state: SessionState) -> None:
    expected = int(getattr(state, "version", 0) or 0)
    state.version = SessionRepository().save_state(
        state.session_id,
        dict(state),
        expected_version=expected,
    )


__all__ = [
    "SessionState",
    "active_task_id",
    "append_message",
    "apply_summary_update",
    "get_or_create_session",
    "history",
    "reset_session",
    "set_active_task",
    "SessionVersionConflict",
    "summary",
    "trim_to_recent_rounds",
    "visible_history",
]