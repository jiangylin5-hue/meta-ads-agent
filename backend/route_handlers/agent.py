from typing import Any

from fastapi import APIRouter, HTTPException

from ..agent.runtime import AgentRuntimeError
from ..models import AgentTurnRequest
from ..services.agent_turn_service import AgentTurnExecution
from ..services.session_store import SessionVersionConflict, get_or_create_session
from ..services.task_state import TaskVersionConflict
from ..services.turn_control import TurnConflictError, TurnControlService, request_fingerprint

router = APIRouter()


@router.post("/agent/turn")
def agent_turn(request: AgentTurnRequest) -> dict[str, Any]:
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required.")

    session_id, state = get_or_create_session(request.session_id)
    turn_service = TurnControlService()
    try:
        turn_id, replay = turn_service.begin(
            session_id=session_id,
            idempotency_key=request.idempotency_key,
            request_hash=request_fingerprint(
                session_id=session_id,
                account_id=request.account_id,
                message=message,
            ),
        )
    except TurnConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    if replay is not None:
        return {**replay, "idempotent_replay": True}

    execution: AgentTurnExecution | None = None
    try:
        execution = AgentTurnExecution(
            request=request,
            message=message,
            session_id=session_id,
            state=state,
            turn_id=turn_id,
        ).prepare()
        response = execution.execute()
        turn_service.complete(turn_id, response)
        return response
    except AgentRuntimeError as exc:
        if execution is not None:
            execution.record_failure("agent_runtime_failed")
        turn_service.fail(turn_id, str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (SessionVersionConflict, TaskVersionConflict) as exc:
        if execution is not None:
            execution.record_failure("state_version_conflict")
        turn_service.fail(turn_id, str(exc))
        raise HTTPException(
            status_code=409,
            detail={"code": "state_version_conflict", "message": str(exc)},
        ) from exc
    except HTTPException as exc:
        if execution is not None:
            execution.record_failure("http_error")
        turn_service.fail(turn_id, str(exc.detail))
        raise
    except Exception as exc:
        if execution is not None:
            execution.record_failure(f"{type(exc).__name__}: {exc}")
        turn_service.fail(turn_id, f"{type(exc).__name__}: {exc}")
        raise
    finally:
        turn_service.release(session_id=session_id, turn_id=turn_id)


__all__ = ["agent_turn", "router"]