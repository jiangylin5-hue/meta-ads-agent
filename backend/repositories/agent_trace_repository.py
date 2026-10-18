from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert

from ..db import schema as s
from .base import Repository, clean_json, new_id, utc_now


class AgentTraceRepository(Repository):
    def ensure_trace(
        self,
        *,
        trace_id: str,
        source: str,
        workflow_id: str = "",
        session_id: str = "",
        runtime: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        with self.tx() as conn:
            conn.execute(
                insert(s.agent_traces)
                .values(
                    id=f"agent_trace_{trace_id.removeprefix('trace_')}",
                    session_id=session_id or None,
                    trace_id=trace_id,
                    workflow_id=workflow_id,
                    runtime=runtime,
                    source=source,
                    status="active",
                    metadata_json=clean_json(metadata or {}),
                    created_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_agent_traces_trace_id",
                    set_={
                        "workflow_id": workflow_id,
                        "runtime": runtime,
                        "source": source,
                        "metadata_json": clean_json(metadata or {}),
                    },
                )
            )

    def append_step(
        self,
        *,
        trace_id: str,
        event: str,
        data: dict[str, Any],
        agent: str = "",
        status: str = "",
    ) -> None:
        with self.tx() as conn:
            conn.execute(
                insert(s.agent_trace_steps).values(
                    id=new_id("trace_step"),
                    trace_id=trace_id,
                    agent=agent,
                    title=event,
                    detail="",
                    status=status,
                    data_json=clean_json(data),
                    created_at=utc_now(),
                )
            )
