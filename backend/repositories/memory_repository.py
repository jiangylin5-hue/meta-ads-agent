from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, desc, or_, select, update

from ..db import schema as s
from .base import Repository, clean_json, ensure_user_reference, new_id, utc_now


class MemoryRepository(Repository):
    def remember(
        self,
        *,
        user_id: str,
        scope_type: str,
        scope_id: str,
        account_id: str,
        kind: str,
        content: str,
        confidence: float,
        status: str,
        source_session_id: str,
        source_message_id: str,
        source_quote: str,
        supersedes_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.tx() as conn:
            ensure_user_reference(conn, user_id)
            resolved_supersedes_id = ""
            if supersedes_id:
                superseded = conn.execute(
                    select(s.agent_memory_records).where(
                        s.agent_memory_records.c.id == supersedes_id,
                        s.agent_memory_records.c.user_id == user_id,
                        s.agent_memory_records.c.scope_type == scope_type,
                        s.agent_memory_records.c.scope_id == scope_id,
                    )
                ).mappings().first()
                if superseded:
                    resolved_supersedes_id = supersedes_id
                    conn.execute(
                        update(s.agent_memory_records)
                        .where(s.agent_memory_records.c.id == supersedes_id)
                        .values(status="superseded", updated_at=now)
                    )
            existing = conn.execute(
                select(s.agent_memory_records)
                .where(
                    s.agent_memory_records.c.user_id == user_id,
                    s.agent_memory_records.c.scope_type == scope_type,
                    s.agent_memory_records.c.scope_id == scope_id,
                    s.agent_memory_records.c.kind == kind,
                    s.agent_memory_records.c.status == status,
                    s.agent_memory_records.c.content == content,
                )
                .order_by(desc(s.agent_memory_records.c.updated_at))
                .limit(1)
            ).mappings().first()
            values = {
                "account_id": account_id,
                "confidence": confidence,
                "status": status,
                "source_session_id": source_session_id or None,
                "source_message_id": source_message_id or None,
                "source_quote": source_quote,
                "supersedes_id": resolved_supersedes_id or None,
                "metadata_json": clean_json(metadata or {}),
                "updated_at": now,
            }
            if existing:
                memory_id = str(existing["id"])
                conn.execute(
                    update(s.agent_memory_records)
                    .where(s.agent_memory_records.c.id == memory_id)
                    .values(**values)
                )
            else:
                memory_id = new_id("mem")
                conn.execute(
                    s.agent_memory_records.insert().values(
                        id=memory_id,
                        user_id=user_id,
                        scope_type=scope_type,
                        scope_id=scope_id,
                        kind=kind,
                        content=content,
                        created_at=now,
                        **values,
                    )
                )
            row = conn.execute(
                select(s.agent_memory_records).where(s.agent_memory_records.c.id == memory_id)
            ).mappings().first()
        return _memory_row(row)

    def list_memories(
        self,
        *,
        user_id: str,
        account_id: str = "",
        include_candidates: bool = False,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        conditions = [
            s.agent_memory_records.c.user_id == user_id,
            _memory_visibility_clause(account_id),
        ]
        if not include_candidates:
            conditions.append(s.agent_memory_records.c.status == "active")
            conditions.append(
                or_(
                    s.agent_memory_records.c.expires_at.is_(None),
                    s.agent_memory_records.c.expires_at > datetime.now(timezone.utc),
                )
            )
        stmt = (
            select(s.agent_memory_records)
            .where(*conditions)
            .order_by(desc(s.agent_memory_records.c.updated_at))
            .limit(safe_limit)
        )
        with self.tx() as conn:
            rows = [dict(row) for row in conn.execute(stmt).mappings()]
        return [_memory_row(row) for row in rows]

    def update_candidate_status(self, *, user_id: str, memory_id: str, status: str) -> bool:
        if status not in {"active", "rejected"}:
            raise ValueError(f"Unsupported candidate status: {status}")
        now = utc_now()
        with self.tx() as conn:
            result = conn.execute(
                update(s.agent_memory_records)
                .where(
                    s.agent_memory_records.c.id == memory_id,
                    s.agent_memory_records.c.user_id == user_id,
                    s.agent_memory_records.c.status == "candidate",
                )
                .values(status=status, updated_at=now)
            )
        return bool(result.rowcount)

    def delete(self, *, user_id: str, memory_id: str) -> bool:
        now = utc_now()
        with self.tx() as conn:
            result = conn.execute(
                update(s.agent_memory_records)
                .where(
                    s.agent_memory_records.c.id == memory_id,
                    s.agent_memory_records.c.user_id == user_id,
                    s.agent_memory_records.c.status != "deleted",
                )
                .values(status="deleted", updated_at=now)
            )
        return bool(result.rowcount)


def _memory_visibility_clause(account_id: str):
    scopes = [s.agent_memory_records.c.scope_type == "user"]
    if account_id:
        scopes.append(
            and_(
                s.agent_memory_records.c.scope_type == "account",
                s.agent_memory_records.c.scope_id == account_id,
            )
        )
    return or_(*scopes)


def _memory_row(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    value = dict(row)
    for key in ("created_at", "updated_at", "expires_at"):
        if hasattr(value.get(key), "isoformat"):
            value[key] = value[key].isoformat()
    value["metadata"] = value.pop("metadata_json", {}) or {}
    return value