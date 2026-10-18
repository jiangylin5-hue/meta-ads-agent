from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import ProgrammingError

from ..models import OptimizationActionDraftRequest
from ..services.action_drafts import create_action_draft
from ..services.action_operations import ActionNotFound, ActionStateConflict, action_operations_service
from ..services.trace_service import append_trace, start_trace

router = APIRouter()


def _is_missing_action_lifecycle_table(exc: ProgrammingError) -> bool:
    return "action_lifecycle_records" in str(exc)


def _schema_not_migrated_error() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "stage06_schema_not_migrated",
            "message": "Action lifecycle tables are not available in the configured database.",
            "action": "Run alembic upgrade head.",
        },
    )


def _runtime(source: str, summary: str) -> dict[str, str]:
    trace_id = start_trace(source, {"summary": summary})
    return {"trace_id": trace_id}


@router.post("/actions/drafts")
def actions_draft_create(request: OptimizationActionDraftRequest) -> dict[str, Any]:
    if not request.account_id.strip():
        raise HTTPException(status_code=400, detail="account_id is required.")
    draft = create_action_draft(request)
    try:
        action = action_operations_service().create_from_optimization_draft(draft)
    except ProgrammingError as exc:
        if _is_missing_action_lifecycle_table(exc):
            raise _schema_not_migrated_error() from exc
        raise
    runtime = _runtime("action_draft_create", draft.id)
    append_trace(runtime["trace_id"], "action_draft_created", {"draft_id": draft.id, "action_id": action.id})
    return {"draft": draft.model_dump(), "action": action.model_dump(), **runtime}


@router.get("/actions/queue")
def actions_queue(
    account_id: str = "",
    workspace_id: str = "",
    status: str = "",
    risk_level: str = "",
    search: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    statuses = [item.strip() for item in status.split(",") if item.strip()] if status else None
    risk_levels = [item.strip() for item in risk_level.split(",") if item.strip()] if risk_level else None
    try:
        return action_operations_service().get_queue(
            account_id=account_id,
            workspace_id=workspace_id,
            statuses=statuses,
            risk_levels=risk_levels,
            search=search,
            limit=limit,
        )
    except ProgrammingError as exc:
        if _is_missing_action_lifecycle_table(exc):
            raise _schema_not_migrated_error() from exc
        raise


@router.get("/actions/drafts/{draft_id}")
def actions_draft_detail(draft_id: str) -> dict[str, Any]:
    try:
        return action_operations_service().get_detail(draft_id)
    except ActionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/actions/drafts/{draft_id}/preflight")
def actions_draft_preflight(draft_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = payload or {}
    try:
        return action_operations_service().run_preflight(
            draft_id,
            current_value=body.get("current_value") if isinstance(body.get("current_value"), dict) else None,
            feature_flags=body.get("feature_flags") if isinstance(body.get("feature_flags"), dict) else None,
        )
    except ActionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/actions/drafts/{draft_id}/approve")
def actions_draft_approve(draft_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = payload or {}
    try:
        result = action_operations_service().approve_action(
            draft_id,
            approver=str(body.get("approver") or body.get("actor_user_id") or "local_user"),
            risk_summary=str(body.get("risk_summary") or body.get("note") or "Reviewed in the draft-only demo."),
            scope=body.get("scope") if isinstance(body.get("scope"), dict) else None,
        )
    except ActionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ActionStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime = _runtime("action_draft_approve", draft_id)
    append_trace(runtime["trace_id"], "action_approved", {"draft_id": draft_id})
    return {
        **result,
        "message": "Action draft approved. Execution remains disabled in the draft-only demo.",
        **runtime,
    }


@router.post("/actions/drafts/{draft_id}/confirm")
def actions_draft_confirm(draft_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = payload or {}
    try:
        return action_operations_service().confirm_action(
            draft_id,
            confirmed_by=str(body.get("confirmed_by") or body.get("actor_user_id") or "local_user"),
            confirmation_text=str(body.get("confirmation_text") or ""),
            confirmation_version=str(body.get("confirmation_version") or "v1"),
        )
    except ActionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ActionStateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/actions/drafts/{draft_id}/attempts")
def actions_draft_attempts(draft_id: str) -> dict[str, Any]:
    try:
        return action_operations_service().get_attempts(draft_id)
    except ActionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/actions/{action_id}/rollback-note")
def actions_rollback_note_create(action_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = payload or {}
    try:
        return action_operations_service().create_rollback_note(
            action_id,
            original_values=body.get("original_values") if isinstance(body.get("original_values"), dict) else {},
            recommended_manual_recovery=str(body.get("recommended_manual_recovery") or body.get("manual_recovery_note") or ""),
            created_by=str(body.get("created_by") or body.get("actor_user_id") or "local_user"),
        )
    except ActionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/actions/drafts/{draft_id}/execute")
def actions_draft_execute(draft_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    raise HTTPException(
        status_code=410,
        detail={
            "code": "execution_disabled_in_demo",
            "message": "Live execution is disabled in the draft-only demo.",
        },
    )


@router.post("/actions/{execution_id}/rollback")
def actions_rollback_create(execution_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    raise HTTPException(
        status_code=410,
        detail={
            "code": "execution_disabled_in_demo",
            "message": "Rollback execution is disabled in the draft-only demo.",
        },
    )


__all__ = [name for name in globals() if not name.startswith("__")]
