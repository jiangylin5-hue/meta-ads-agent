from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from queue import Empty, Queue
from threading import Thread
from typing import Any

from fastapi.responses import StreamingResponse

from ..agent.runtime import AgentRuntimeError, AgentTimeoutError
from .session_store import SessionVersionConflict
from .task_state import TaskVersionConflict
from .trace_service import sanitize_for_trace
from .turn_control import TurnConflictError


SSE_HEARTBEAT_SECONDS = 15
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
TurnWorker = Callable[[Callable[[str, dict[str, Any]], None]], dict[str, Any]]
TurnStartFailureHandler = Callable[[Exception], None]
_END = object()


class SSEEncoder:
    def __init__(self, turn_id: str) -> None:
        self.turn_id = turn_id
        self.seq = 0

    def event(self, event_name: str, payload: dict[str, Any] | None = None) -> str:
        self.seq += 1
        safe_payload = payload if event_name == "turn.completed" else sanitize_for_trace(payload or {})
        data = {**safe_payload, "turn_id": self.turn_id, "seq": self.seq}
        compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return f"id: {self.seq}\nevent: {event_name}\ndata: {compact}\n\n"


def stream_turn_response(
    worker: TurnWorker,
    *,
    turn_id: str,
    trace_id: str = "",
    heartbeat_seconds: float = SSE_HEARTBEAT_SECONDS,
    on_start_failure: TurnStartFailureHandler | None = None,
) -> StreamingResponse:
    return StreamingResponse(
        _event_iterator(
            worker,
            turn_id=turn_id,
            thread_name=f"agent-sse-{trace_id or turn_id}",
            heartbeat_seconds=heartbeat_seconds,
            on_start_failure=on_start_failure,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


def replay_turn_response(response: dict[str, Any]) -> StreamingResponse:
    turn_id = str(response.get("turn_id") or response.get("trace_id") or "")
    session_id = str(response.get("session_id") or "")
    task_state = response.get("task_state") if isinstance(response.get("task_state"), dict) else {}

    def iterator() -> Iterator[str]:
        encoder = SSEEncoder(turn_id)
        yield encoder.event(
            "turn.started",
            {
                "session_id": session_id,
                "user_message_id": str(response.get("user_message_id") or ""),
                "task_id": str(task_state.get("task_id") or ""),
            },
        )
        yield encoder.event("turn.completed", {"response": response})

    return StreamingResponse(iterator(), media_type="text/event-stream", headers=SSE_HEADERS)


def public_failure_payload(exc: Exception, *, validated: bool) -> dict[str, Any]:
    if isinstance(exc, AgentTimeoutError):
        return {
            "code": "agent_timeout",
            "message": "本轮处理超时，请缩小任务范围后重试。",
            "retryable": not validated,
        }
    if isinstance(exc, AgentRuntimeError):
        return {
            "code": str(getattr(exc, "code", "") or "agent_runtime_failed"),
            "message": "Agent 执行失败，请稍后重试。" if not validated else "结果已生成，但最终保存失败；请刷新会话核对后再操作。",
            "retryable": bool(getattr(exc, "retryable", True)) and not validated,
        }
    if isinstance(exc, TurnConflictError):
        return {
            "code": exc.code,
            "message": "本轮请求与其他请求冲突，请刷新会话后重试。",
            "retryable": False,
        }
    if isinstance(exc, (SessionVersionConflict, TaskVersionConflict)):
        return {
            "code": "state_version_conflict",
            "message": "会话或任务状态已变化，请刷新后重试。",
            "retryable": not validated,
        }
    return {
        "code": "turn_failed",
        "message": "本轮处理失败，请刷新会话核对状态。",
        "retryable": False,
    }


def _event_iterator(
    worker: TurnWorker,
    *,
    turn_id: str,
    thread_name: str,
    heartbeat_seconds: float,
    on_start_failure: TurnStartFailureHandler | None,
) -> Iterator[str]:
    queue: Queue[tuple[str, str | None, Any]] = Queue()
    status = {"validated": False}

    def emit(event_name: str, payload: dict[str, Any] | None = None) -> None:
        if event_name in {"turn.completed", "turn.failed"}:
            raise ValueError("The SSE stream owns terminal events.")
        if event_name == "result.validated":
            status["validated"] = True
        queue.put(("event", event_name, payload or {}))

    def run_worker() -> None:
        try:
            response = worker(emit)
            queue.put(("event", "turn.completed", {"response": response}))
        except Exception as exc:
            queue.put(("event", "turn.failed", public_failure_payload(exc, validated=bool(status["validated"]))))
        finally:
            queue.put(("end", None, None))

    thread = Thread(target=run_worker, name=thread_name, daemon=True)
    encoder = SSEEncoder(turn_id)
    try:
        thread.start()
    except Exception as exc:
        if on_start_failure is not None:
            try:
                on_start_failure(exc)
            except Exception:
                pass
        yield encoder.event(
            "turn.failed",
            {
                "code": "stream_start_failed",
                "message": "无法启动流式任务，请稍后重试。",
                "retryable": True,
            },
        )
        return

    while True:
        try:
            kind, event_name, payload = queue.get(timeout=max(0.1, heartbeat_seconds))
        except Empty:
            yield ": ping\n\n"
            continue
        if kind == "end":
            return
        if event_name is None:
            continue
        yield encoder.event(event_name, payload if isinstance(payload, dict) else {})


__all__ = [
    "SSEEncoder",
    "SSE_HEADERS",
    "SSE_HEARTBEAT_SECONDS",
    "public_failure_payload",
    "replay_turn_response",
    "stream_turn_response",
]
