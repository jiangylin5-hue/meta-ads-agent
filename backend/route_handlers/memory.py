from typing import Any

from fastapi import APIRouter, HTTPException

from ..services.long_term_memory import DEFAULT_USER_ID, LongTermMemoryService

router = APIRouter()


@router.get("/memory")
def list_memory(user_id: str = DEFAULT_USER_ID, account_id: str = "") -> dict[str, Any]:
    service = LongTermMemoryService()
    try:
        rows = service.list_visible(user_id=user_id, account_id=account_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Memory store unavailable: {type(exc).__name__}: {exc}") from exc
    return {"user_id": user_id, "account_id": account_id, "memories": [_public(row) for row in rows]}


@router.post("/memory/{memory_id}/confirm")
def confirm_memory(memory_id: str, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
    return _resolve_candidate(memory_id, user_id, action="confirm")


@router.post("/memory/{memory_id}/reject")
def reject_memory(memory_id: str, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
    return _resolve_candidate(memory_id, user_id, action="reject")


@router.delete("/memory/{memory_id}")
def delete_memory(memory_id: str, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
    service = LongTermMemoryService()
    try:
        deleted = service.delete(user_id=user_id, memory_id=memory_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Memory store unavailable: {type(exc).__name__}: {exc}") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory record not found.")
    return {"id": memory_id, "status": "deleted"}


def _resolve_candidate(memory_id: str, user_id: str, *, action: str) -> dict[str, Any]:
    service = LongTermMemoryService()
    try:
        changed = (
            service.confirm_candidate(user_id=user_id, memory_id=memory_id)
            if action == "confirm"
            else service.reject_candidate(user_id=user_id, memory_id=memory_id)
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Memory store unavailable: {type(exc).__name__}: {exc}") from exc
    if not changed:
        raise HTTPException(status_code=404, detail="Candidate Memory record not found.")
    return {"id": memory_id, "status": "active" if action == "confirm" else "rejected"}


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "kind": row.get("kind"),
        "scope_type": row.get("scope_type"),
        "scope_id": row.get("scope_id"),
        "account_id": row.get("account_id"),
        "content": row.get("content"),
        "confidence": row.get("confidence"),
        "status": row.get("status"),
        "source_session_id": row.get("source_session_id"),
        "source_message_id": row.get("source_message_id"),
        "updated_at": row.get("updated_at"),
    }




__all__ = ["confirm_memory", "delete_memory", "list_memory", "reject_memory"]
