from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from ..db import schema as s
from .base import Repository, clean_json, new_id, utc_now


class TurnRepository(Repository):
    def get(self, turn_id: str) -> dict[str, Any] | None:
        with self.tx() as conn:
            row = conn.execute(select(s.agent_turns).where(s.agent_turns.c.id == turn_id)).mappings().first()
        return _turn_row(row)

    def get_by_idempotency(self, session_id: str, idempotency_key: str) -> dict[str, Any] | None:
        with self.tx() as conn:
            row = conn.execute(
                select(s.agent_turns).where(
                    s.agent_turns.c.session_id == session_id,
                    s.agent_turns.c.idempotency_key == idempotency_key,
                )
            ).mappings().first()
        return _turn_row(row)

    def create(self, *, session_id: str, idempotency_key: str, request_hash: str) -> dict[str, Any]:
        now = utc_now()
        turn_id = new_id("turn")
        with self.tx() as conn:
            conn.execute(
                s.agent_turns.insert().values(
                    id=turn_id,
                    session_id=session_id,
                    idempotency_key=idempotency_key or None,
                    request_hash=request_hash,
                    status="in_progress",
                    response_json={},
                    error_text="",
                    created_at=now,
                    updated_at=now,
                )
            )
            row = conn.execute(select(s.agent_turns).where(s.agent_turns.c.id == turn_id)).mappings().first()
        return _turn_row(row) or {}

    def mark_in_progress(self, turn_id: str, request_hash: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.tx() as conn:
            conn.execute(
                update(s.agent_turns)
                .where(s.agent_turns.c.id == turn_id)
                .values(status="in_progress", request_hash=request_hash, response_json={}, error_text="", updated_at=now)
            )
            row = conn.execute(select(s.agent_turns).where(s.agent_turns.c.id == turn_id)).mappings().first()
        return _turn_row(row)

    def get_lock(self, session_id: str) -> dict[str, Any] | None:
        with self.tx() as conn:
            row = conn.execute(
                select(s.agent_turn_locks).where(s.agent_turn_locks.c.session_id == session_id)
            ).mappings().first()
        return dict(row) if row else None

    def acquire_lock(self, *, session_id: str, turn_id: str, lease_seconds: int) -> bool:
        now = utc_now()
        expires_at = now + _lease_delta(lease_seconds)
        with self.tx() as conn:
            inserted = conn.execute(
                insert(s.agent_turn_locks)
                .values(session_id=session_id, turn_id=turn_id, acquired_at=now, expires_at=expires_at)
                .on_conflict_do_update(
                    index_elements=[s.agent_turn_locks.c.session_id],
                    set_={"turn_id": turn_id, "acquired_at": now, "expires_at": expires_at},
                    where=or_(
                        s.agent_turn_locks.c.expires_at < now,
                        s.agent_turn_locks.c.turn_id == turn_id,
                    ),
                )
                .returning(s.agent_turn_locks.c.turn_id)
            ).scalar_one_or_none()
        return inserted == turn_id

    def force_release_session(self, session_id: str) -> None:
        with self.tx() as conn:
            conn.execute(delete(s.agent_turn_locks).where(s.agent_turn_locks.c.session_id == session_id))

    def release_lock(self, *, session_id: str, turn_id: str) -> None:
        with self.tx() as conn:
            conn.execute(
                delete(s.agent_turn_locks).where(
                    s.agent_turn_locks.c.session_id == session_id,
                    s.agent_turn_locks.c.turn_id == turn_id,
                )
            )

    def complete(self, turn_id: str, response: dict[str, Any]) -> None:
        now = utc_now()
        with self.tx() as conn:
            conn.execute(
                update(s.agent_turns)
                .where(s.agent_turns.c.id == turn_id)
                .values(status="completed", response_json=clean_json(response), error_text="", updated_at=now)
            )

    def fail(self, turn_id: str, error: str) -> None:
        now = utc_now()
        with self.tx() as conn:
            conn.execute(
                update(s.agent_turns)
                .where(s.agent_turns.c.id == turn_id)
                .values(status="failed", error_text=error[:2000], updated_at=now)
            )


def _turn_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    value = dict(row)
    value["response"] = value.pop("response_json", {}) or {}
    for key in ("created_at", "updated_at"):
        if hasattr(value.get(key), "isoformat"):
            value[key] = value[key].isoformat()
    return value


def _lease_delta(seconds: int):
    from datetime import timedelta

    return timedelta(seconds=max(30, int(seconds)))