from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..config import agent_trace_enabled


_TRACES: dict[str, dict[str, Any]] = {}
_SENSITIVE_TRACE_KEY_MARKERS = (
    "token",
    "secret",
    "api_key",
    "access_token",
    "data_url",
    "authorization",
    "cookie",
    "password",
    "credential",
    "private_key",
)
_COMPACT_TRACE_KEYS = {"payload", "raw", "creative_body"}


def public_runtime_label() -> str:
    return "react"


def start_trace(source: str, data: dict[str, Any] | None = None) -> str:
    trace_id = f"trace_{uuid4().hex[:12]}"
    if not agent_trace_enabled():
        return trace_id
    _TRACES[trace_id] = {
        "id": trace_id,
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "events": [],
    }
    _persist_trace(trace_id, source, data or {})
    append_trace(trace_id, "runtime_started", data or {})
    return trace_id


def append_trace(trace_id: str, event: str, data: dict[str, Any] | None = None) -> None:
    if not trace_id or not agent_trace_enabled():
        return
    trace = _TRACES.setdefault(
        trace_id,
        {
            "id": trace_id,
            "source": "unknown",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "events": [],
        },
    )
    trace.setdefault("events", []).append(
        {
            "event": event,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "data": sanitize_for_trace(data or {}),
        }
    )
    _persist_trace_step(trace_id, event, data or {})


def get_trace(trace_id: str) -> dict[str, Any]:
    return _TRACES.get(trace_id, {"id": trace_id, "events": []})


def sanitize_for_trace(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "[truncated]"
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in _SENSITIVE_TRACE_KEY_MARKERS):
                output[str(key)] = "[redacted]"
            elif lowered in _COMPACT_TRACE_KEYS:
                output[str(key)] = _compact_or_redact_trace_text(str(item), 180)
            else:
                output[str(key)] = sanitize_for_trace(item, depth + 1)
        return output
    if isinstance(value, list):
        return [sanitize_for_trace(item, depth + 1) for item in value[:12]]
    if isinstance(value, str):
        return _compact_or_redact_trace_text(value, 360)
    return value


def _compact_or_redact_trace_text(value: str, max_chars: int) -> str:
    if _looks_sensitive_trace_text(value):
        return "[redacted]"
    compact = " ".join(value.split())
    return compact if len(compact) <= max_chars else compact[: max_chars - 1] + "\u2026"


def _looks_sensitive_trace_text(value: str) -> bool:
    lowered = value.strip().lower()
    return (
        lowered.startswith("data:")
        or "data:image/" in lowered
        or lowered.startswith("bearer ")
        or "authorization:" in lowered
        or "set-cookie:" in lowered
        or "access_token" in lowered
        or "api_key" in lowered
        or "client_secret" in lowered
        or "sk-" in lowered
    )


def _persist_trace(trace_id: str, source: str, data: dict[str, Any]) -> None:
    try:
        from ..repositories.agent_trace_repository import AgentTraceRepository

        AgentTraceRepository().ensure_trace(
            trace_id=trace_id,
            source=source,
            workflow_id=str(data.get("workflow_id") or ""),
            session_id=str(data.get("session_id") or ""),
            runtime=public_runtime_label(),
            metadata=data,
        )
    except Exception:
        return


def _persist_trace_step(trace_id: str, event: str, data: dict[str, Any]) -> None:
    try:
        from ..repositories.agent_trace_repository import AgentTraceRepository

        AgentTraceRepository().append_step(
            trace_id=trace_id,
            event=event,
            data=sanitize_for_trace(data),
            agent=str(data.get("agent") or ""),
            status=str(data.get("status") or ""),
        )
    except Exception:
        return
