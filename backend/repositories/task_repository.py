from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, or_, select, update

from ..db import schema as s
from .base import Repository, clean_json, new_id, utc_now


class TaskVersionConflict(RuntimeError):
    pass


class TaskRepository(Repository):
    def get(self, task_id: str) -> dict[str, Any] | None:
        with self.tx() as conn:
            row = conn.execute(select(s.agent_tasks).where(s.agent_tasks.c.id == task_id)).mappings().first()
        return _task_row(row)

    def find_active(self, session_id: str, account_id: str = "") -> dict[str, Any] | None:
        stmt = select(s.agent_tasks).where(
            s.agent_tasks.c.session_id == session_id,
            s.agent_tasks.c.status == "active",
            or_(
                s.agent_tasks.c.expires_at.is_(None),
                s.agent_tasks.c.expires_at > utc_now(),
            ),
        )
        if account_id:
            stmt = stmt.where(s.agent_tasks.c.account_id == account_id)
        stmt = stmt.order_by(desc(s.agent_tasks.c.updated_at)).limit(1)
        with self.tx() as conn:
            row = conn.execute(stmt).mappings().first()
        return _task_row(row)

    def create(
        self,
        *,
        session_id: str,
        account_id: str,
        goal: str,
        active_skill_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        task_id = new_id("task")
        with self.tx() as conn:
            conn.execute(
                s.agent_tasks.insert().values(
                    id=task_id,
                    session_id=session_id,
                    account_id=account_id,
                    goal=goal[:4000],
                    status="active",
                    progress_json={"turn_count": 0, "recent": []},
                    constraints_json=[],
                    tool_ledger_json=[],
                    active_skill_ids_json=list(active_skill_ids or []),
                    metadata_json={},
                    version=1,
                    expires_at=now + timedelta(days=7),
                    created_at=now,
                    updated_at=now,
                )
            )
            row = conn.execute(select(s.agent_tasks).where(s.agent_tasks.c.id == task_id)).mappings().first()
        return _task_row(row) or {}

    def pause_active_for_session(self, session_id: str, *, except_id: str = "") -> None:
        now = utc_now()
        conditions = [s.agent_tasks.c.session_id == session_id, s.agent_tasks.c.status == "active"]
        if except_id:
            conditions.append(s.agent_tasks.c.id != except_id)
        with self.tx() as conn:
            conn.execute(update(s.agent_tasks).where(*conditions).values(status="paused", updated_at=now))

    def update(
        self,
        task_id: str,
        *,
        goal: str | None = None,
        status: str | None = None,
        progress: dict[str, Any] | None = None,
        constraints: list[str] | None = None,
        tool_ledger: list[dict[str, Any]] | None = None,
        active_skill_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        values: dict[str, Any] = {"updated_at": now, "version": s.agent_tasks.c.version + 1}
        if goal is not None:
            values["goal"] = goal[:4000]
        if status is not None:
            values["status"] = status
        if progress is not None:
            values["progress_json"] = clean_json(progress)
        if constraints is not None:
            values["constraints_json"] = clean_json(constraints[-24:])
        if tool_ledger is not None:
            values["tool_ledger_json"] = clean_json(tool_ledger[-40:])
        if active_skill_ids is not None:
            values["active_skill_ids_json"] = [str(item) for item in active_skill_ids[:4]]
        if metadata is not None:
            values["metadata_json"] = clean_json(metadata)
        if expires_at is not None:
            values["expires_at"] = expires_at
        conditions = [s.agent_tasks.c.id == task_id]
        if expected_version is not None:
            conditions.append(s.agent_tasks.c.version == expected_version)
        with self.tx() as conn:
            changed = conn.execute(
                update(s.agent_tasks)
                .where(*conditions)
                .values(**values)
                .returning(s.agent_tasks.c.id)
            ).scalar_one_or_none()
            if changed is None:
                raise TaskVersionConflict(f"Task {task_id} changed during the turn.")
            row = conn.execute(select(s.agent_tasks).where(s.agent_tasks.c.id == task_id)).mappings().first()
        return _task_row(row)


def _task_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    value = dict(row)
    value["progress"] = value.pop("progress_json", {}) or {}
    value["constraints"] = value.pop("constraints_json", []) or []
    value["tool_ledger"] = value.pop("tool_ledger_json", []) or []
    value["active_skill_ids"] = value.pop("active_skill_ids_json", []) or []
    value["metadata"] = value.pop("metadata_json", {}) or {}
    for key in ("created_at", "updated_at", "expires_at"):
        if hasattr(value.get(key), "isoformat"):
            value[key] = value[key].isoformat()
    return value