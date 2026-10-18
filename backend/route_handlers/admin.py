from typing import Any

from fastapi import APIRouter, HTTPException

from ..services.persistent_store import store

router = APIRouter()


@router.get("/execution-logs")
def execution_logs(client_id: str = "", account_id: str = "", limit: int = 50) -> dict[str, Any]:
    logs = store().list_execution_logs(client_id=client_id, account_id=account_id, limit=limit)
    return {"logs": [log.model_dump() for log in logs]}


@router.get("/execution-logs/{execution_id}")
def execution_log_detail(execution_id: str) -> dict[str, Any]:
    log = store().get_execution_log(execution_id)
    if not log:
        raise HTTPException(status_code=404, detail="Execution log not found.")
    return {"execution_log": log.model_dump()}


__all__ = [name for name in globals() if not name.startswith("__")]
