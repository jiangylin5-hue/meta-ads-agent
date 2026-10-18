from datetime import datetime

from fastapi import APIRouter

from ..services.session_store import get_or_create_session, history, reset_session, summary, visible_history
from ..services.task_state import TaskStateService, task_for_context
from ..services.turn_control import TurnControlService

router = APIRouter()


@router.get("/sessions/{session_id}")
def session_detail(session_id: str, limit: int = 50, before: str = "") -> dict[str, object]:
    sid, state = get_or_create_session(session_id)
    safe_limit = max(1, min(limit, 100))
    before_dt = _parse_before(before)
    history_rows = visible_history(state, limit=safe_limit + 1, before=before_dt)
    has_more = len(history_rows) > safe_limit
    if has_more:
        history_rows = history_rows[1:]
    task: dict[str, object] = {}
    try:
        task_record = TaskStateService().repository.get(str(state.get("active_task_id") or ""))
        task = task_for_context(task_record)
    except Exception:
        task = {}
    return {
        "session_id": sid,
        "history": history_rows,
        "short_term_history": history(state),
        "compressed_context": summary(state),
        "task_state": task,
        "history_pagination": {
            "limit": safe_limit,
            "has_more": has_more,
            "next_before": history_rows[0]["created_at"] if has_more and history_rows else "",
        },
    }


def _parse_before(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.delete("/sessions/{session_id}")
def session_reset(session_id: str) -> dict[str, str]:
    TaskStateService().pause_session(session_id)
    TurnControlService().force_release_session(session_id)
    reset_session(session_id)
    return {"session_id": session_id, "status": "reset"}


__all__ = [name for name in globals() if not name.startswith("__")]