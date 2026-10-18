from __future__ import annotations

from typing import Any

from datetime import datetime
from sqlalchemy import desc, select, update
from sqlalchemy.dialects.postgresql import insert

from ..db import schema as s
from .base import Repository, clean_json, new_id, utc_now


class SessionVersionConflict(RuntimeError):
    pass


class SessionRepository(Repository):
    def get_record(self, session_id: str) -> tuple[dict[str, Any], int] | None:
        with self.tx() as conn:
            row = conn.execute(select(s.user_sessions).where(s.user_sessions.c.id == session_id)).mappings().first()
        if not row:
            return None
        return dict(row["state_json"] or {}), int(row.get("version") or 1)

    def get_state(self, session_id: str) -> dict[str, Any] | None:
        record = self.get_record(session_id)
        return record[0] if record else None

    def save_state(self, session_id: str, state: dict[str, Any], *, expected_version: int = 1) -> int:
        now = utc_now()
        compressed = state.get("compressed_context") if isinstance(state.get("compressed_context"), dict) else {}
        values = {
            "id": session_id,
            "status": "active",
            "state_json": clean_json(state),
            "compressed_context_json": clean_json(compressed),
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        with self.tx() as conn:
            next_version = conn.execute(
                insert(s.user_sessions)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[s.user_sessions.c.id],
                    set_={
                        "state_json": clean_json(state),
                        "compressed_context_json": clean_json(compressed),
                        "updated_at": now,
                        "version": s.user_sessions.c.version + 1,
                    },
                    where=s.user_sessions.c.version == expected_version,
                )
                .returning(s.user_sessions.c.version)
            ).scalar_one_or_none()
        if next_version is None:
            raise SessionVersionConflict(f"Session {session_id} changed during the turn.")
        return int(next_version)

    def get_message_for_turn(self, session_id: str, turn_id: str, role: str) -> dict[str, Any] | None:
        if not turn_id:
            return None
        with self.tx() as conn:
            row = conn.execute(
                select(s.chat_messages).where(
                    s.chat_messages.c.session_id == session_id,
                    s.chat_messages.c.role == role,
                    s.chat_messages.c.metadata_json["turn_id"].astext == turn_id,
                )
            ).mappings().first()
        return dict(row) if row else None

    def append_message(self, session_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> str:
        message_id = new_id("msg")
        with self.tx() as conn:
            conn.execute(
                insert(s.chat_messages).values(
                    id=message_id,
                    session_id=session_id,
                    role=role,
                    content=content,
                    metadata_json=clean_json(metadata or {}),
                    created_at=utc_now(),
                )
            )
        return message_id

    def list_messages(self, session_id: str, *, limit: int = 50, before: datetime | None = None) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        stmt = select(s.chat_messages).where(s.chat_messages.c.session_id == session_id)
        if before is not None:
            stmt = stmt.where(s.chat_messages.c.created_at < before)
        stmt = stmt.order_by(desc(s.chat_messages.c.created_at)).limit(safe_limit + 1)
        with self.tx() as conn:
            rows = [dict(row) for row in conn.execute(stmt).mappings()]
        return list(reversed(rows))

    def reset_state(self, session_id: str, state: dict[str, Any]) -> int:
        now = utc_now()
        compressed = clean_json(state.get("compressed_context") or {})
        with self.tx() as conn:
            next_version = conn.execute(
                insert(s.user_sessions)
                .values(
                    id=session_id,
                    status="active",
                    state_json=clean_json(state),
                    compressed_context_json=compressed,
                    created_at=now,
                    updated_at=now,
                    reset_at=now,
                    version=1,
                )
                .on_conflict_do_update(
                    index_elements=[s.user_sessions.c.id],
                    set_={
                        "state_json": clean_json(state),
                        "compressed_context_json": compressed,
                        "updated_at": now,
                        "reset_at": now,
                        "version": s.user_sessions.c.version + 1,
                    },
                )
                .returning(s.user_sessions.c.version)
            ).scalar_one()
        return int(next_version)
