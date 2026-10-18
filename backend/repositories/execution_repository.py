from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..db import schema as s
from ..models import ExecutionLogRecord, RollbackRecord
from .base import Repository, account_record_id, clean_json, ensure_account_reference, ensure_user_reference, iso, new_id, provider_account_id, utc_now


class ExecutionRepository(Repository):
    def save_execution_log(self, log: ExecutionLogRecord) -> ExecutionLogRecord:
        now = utc_now()
        if not log.id:
            log.id = new_id("exec")
        if not log.created_at:
            log.created_at = iso(now)
        with self.tx() as conn:
            client_id = log.client_id or None
            account_id = log.account_id or None
            actor_user_id = ensure_user_reference(conn, log.actor_user_id)
            if log.account_id:
                client_id, account_id = ensure_account_reference(conn, log.account_id, client_id=log.client_id)
            conn.execute(
                insert(s.execution_logs).values(
                    id=log.id,
                    client_id=client_id,
                    account_id=account_id,
                    source_type=log.source_type,
                    source_id=log.source_id,
                    actor_user_id=actor_user_id,
                    status=log.status,
                    before_snapshot_id=log.before_snapshot_id or None,
                    after_snapshot_id=log.after_snapshot_id or None,
                    request_summary_json=clean_json(log.request_summary),
                    result_json=clean_json(log.result),
                    error=log.error,
                    created_at=now,
                )
            )
            for item in _execution_entities(log.result):
                conn.execute(
                    insert(s.execution_log_entities).values(
                        id=new_id("exec_entity"),
                        execution_id=log.id,
                        entity_type=str(item.get("entity_type") or ""),
                        entity_ref=str(item.get("entity_ref") or ""),
                        provider_entity_id=str(item.get("id") or item.get("provider_entity_id") or ""),
                        status=str(item.get("status") or ("failed" if item.get("error") else "succeeded")),
                        error=str(item.get("error") or ""),
                        payload_json=clean_json(item),
                    )
                )
        return log

    def list_execution_logs(self, client_id: str = "", account_id: str = "", limit: int = 50) -> list[ExecutionLogRecord]:
        query = select(s.execution_logs)
        if client_id:
            query = query.where(s.execution_logs.c.client_id == client_id)
        if account_id:
            query = query.where(s.execution_logs.c.account_id == account_record_id(client_id, account_id))
        query = query.order_by(s.execution_logs.c.created_at.desc()).limit(max(1, min(limit, 200)))
        with self.tx() as conn:
            rows = conn.execute(query).mappings().all()
        return [_execution_log(row) for row in rows]

    def get_execution_log(self, execution_id: str) -> ExecutionLogRecord | None:
        with self.tx() as conn:
            row = conn.execute(select(s.execution_logs).where(s.execution_logs.c.id == execution_id)).mappings().first()
        return _execution_log(row) if row else None

    def save_rollback_record(self, record: RollbackRecord) -> RollbackRecord:
        now = utc_now()
        if not record.id:
            record.id = new_id("rollback")
        if not record.created_at:
            record.created_at = iso(now)
        with self.tx() as conn:
            actor_user_id = ensure_user_reference(conn, record.actor_user_id)
            conn.execute(
                insert(s.rollback_records).values(
                    id=record.id,
                    execution_id=record.execution_id,
                    actor_user_id=actor_user_id,
                    status=record.status,
                    plan_json=clean_json(record.plan),
                    result_json=clean_json(record.result),
                    created_at=now,
                    executed_at=None,
                )
            )
        return record


def _execution_log(row: Any) -> ExecutionLogRecord:
    return ExecutionLogRecord(
        id=str(row["id"]),
        client_id=str(row["client_id"] or ""),
        account_id=provider_account_id(str(row["account_id"] or "")),
        source_type=row["source_type"],
        source_id=str(row["source_id"]),
        actor_user_id=str(row["actor_user_id"]),
        status=row["status"],
        before_snapshot_id=str(row["before_snapshot_id"] or ""),
        after_snapshot_id=str(row["after_snapshot_id"] or ""),
        request_summary=dict(row["request_summary_json"] or {}),
        result=dict(row["result_json"] or {}),
        error=str(row["error"] or ""),
        created_at=iso(row["created_at"]),
    )


def _execution_entities(result: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    rows = []
    for key in ("created_entities", "failed_entities"):
        value = result.get(key)
        if isinstance(value, list):
            rows.extend([item for item in value if isinstance(item, dict)])
    return rows
