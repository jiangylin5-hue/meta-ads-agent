from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..agent.runtime import AgentRuntimeError
from ..models import AgentTurnRequest
from ..services.agent_sse import replay_turn_response, stream_turn_response
from ..services.agent_turn_service import AgentTurnExecution
from ..services.session_store import SessionVersionConflict, get_or_create_session
from ..services.task_state import TaskVersionConflict
from ..services.turn_control import TurnConflictError, TurnControlService, request_fingerprint


router = APIRouter()


@router.post("/agent/turn")
def agent_turn(request: AgentTurnRequest, http_request: Request) -> Any:
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
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc

    if replay is not None:
        replayed = {**replay, "idempotent_replay": True}
        if _wants_event_stream(http_request):
            return replay_turn_response(replayed)
        return replayed

    execution = AgentTurnExecution(
        request=request,
        message=message,
        session_id=session_id,
        state=state,
        turn_id=turn_id,
    )
    try:
        execution.prepare()
    except (SessionVersionConflict, TaskVersionConflict) as exc:
        _record_turn_failure(execution, turn_service, "state_version_conflict", exc)
        _release_turn(turn_service, session_id, turn_id)
        raise HTTPException(
            status_code=409,
            detail={"code": "state_version_conflict", "message": str(exc)},
        ) from exc
    except Exception as exc:
        _record_turn_failure(execution, turn_service, "turn_preparation_failed", exc)
        _release_turn(turn_service, session_id, turn_id)
        raise

    if _wants_event_stream(http_request):
        return _stream_execution(execution, turn_service)

    try:
        response = execution.execute()
        turn_service.complete(turn_id, response)
        return response
    except AgentRuntimeError as exc:
        _record_turn_failure(execution, turn_service, str(getattr(exc, "code", "") or "agent_runtime_failed"), exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (SessionVersionConflict, TaskVersionConflict) as exc:
        _record_turn_failure(execution, turn_service, "state_version_conflict", exc)
        raise HTTPException(
            status_code=409,
            detail={"code": "state_version_conflict", "message": str(exc)},
        ) from exc
    except Exception as exc:
        _record_turn_failure(execution, turn_service, "turn_failed", exc)
        raise
    finally:
        _release_turn(turn_service, session_id, turn_id)


def _stream_execution(execution: AgentTurnExecution, turn_service: TurnControlService) -> Any:
    def worker(emit: Any) -> dict[str, Any]:
        try:
            response = execution.execute(on_event=emit)
            turn_service.complete(execution.turn_id, response)
            return response
        except Exception as exc:
            _record_turn_failure(execution, turn_service, _failure_code(exc), exc)
            raise
        finally:
            _release_turn(turn_service, execution.session_id, execution.turn_id)

    def on_start_failure(exc: Exception) -> None:
        _record_turn_failure(execution, turn_service, "stream_start_failed", exc)
        _release_turn(turn_service, execution.session_id, execution.turn_id)

    return stream_turn_response(
        worker,
        turn_id=execution.turn_id,
        trace_id=execution.trace_id,
        on_start_failure=on_start_failure,
    )


def _record_turn_failure(
    execution: AgentTurnExecution,
    turn_service: TurnControlService,
    code: str,
    exc: Exception | None = None,
) -> None:
    execution.record_failure(code)
    detail = code if exc is None else f"{code}: {type(exc).__name__}: {str(exc)[:500]}"
    try:
        turn_service.fail(execution.turn_id, detail)
    except Exception:
        return


def _release_turn(turn_service: TurnControlService, session_id: str, turn_id: str) -> None:
    try:
        turn_service.release(session_id=session_id, turn_id=turn_id)
    except Exception:
        return


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, AgentRuntimeError):
        return str(getattr(exc, "code", "") or "agent_runtime_failed")
    if isinstance(exc, (SessionVersionConflict, TaskVersionConflict)):
        return "state_version_conflict"
    return "turn_failed"


def _wants_event_stream(request: Request) -> bool:
    return "text/event-stream" in request.headers.get("accept", "").lower()


__all__ = ["agent_turn", "router"]
