from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from ..db import schema as s
from ..models import (
    ActionApprovalEvent,
    ActionAuditEvent,
    ActionConfirmationEvent,
    ActionExecutionAttempt,
    ActionLifecycleRecord,
    ActionPreflightCheck,
    ActionRollbackNote,
)
from .base import (
    DEFAULT_CLIENT_ID,
    Repository,
    account_record_id,
    clean_json,
    ensure_account_reference,
    ensure_user_reference,
    iso,
    new_id,
    provider_account_id,
    utc_now,
)


class ActionRepository(Repository):
    def save_lifecycle_record(self, record: ActionLifecycleRecord, client_id: str = "") -> ActionLifecycleRecord:
        now = utc_now()
        created_at = _dt(record.created_at) or now
        updated_at = _dt(record.updated_at) or now
        with self.tx() as conn:
            _, account_pk = ensure_account_reference(conn, record.account_id, client_id=client_id)
            created_by = ensure_user_reference(conn, record.created_by)
            conn.execute(
                insert(s.action_lifecycle_records)
                .values(
                    id=record.id,
                    workspace_id=record.workspace_id,
                    account_id=account_pk,
                    entity_type=record.entity_type,
                    entity_id=record.entity_id,
                    operation=record.operation,
                    status=record.status,
                    risk_level=record.risk_level,
                    created_by=created_by,
                    evidence_json=clean_json(record.evidence),
                    assumptions_json=clean_json(record.assumptions),
                    missing_data_json=clean_json(record.missing_data),
                    current_value_json=clean_json(record.current_value),
                    proposed_value_json=clean_json(record.proposed_value),
                    metadata_json=clean_json(record.metadata),
                    created_at=created_at,
                    updated_at=updated_at,
                )
                .on_conflict_do_update(
                    index_elements=[s.action_lifecycle_records.c.id],
                    set_={
                        "workspace_id": record.workspace_id,
                        "status": record.status,
                        "risk_level": record.risk_level,
                        "evidence_json": clean_json(record.evidence),
                        "assumptions_json": clean_json(record.assumptions),
                        "missing_data_json": clean_json(record.missing_data),
                        "current_value_json": clean_json(record.current_value),
                        "proposed_value_json": clean_json(record.proposed_value),
                        "metadata_json": clean_json(record.metadata),
                        "updated_at": updated_at,
                    },
                )
            )
        return record.model_copy(update={"created_at": iso(created_at), "updated_at": iso(updated_at)})

    def get_lifecycle_record(self, action_id: str) -> ActionLifecycleRecord | None:
        with self.tx() as conn:
            row = conn.execute(select(s.action_lifecycle_records).where(s.action_lifecycle_records.c.id == action_id)).mappings().first()
        return _lifecycle(row) if row else None

    def list_queue_records(
        self,
        account_id: str = "",
        workspace_id: str = "",
        statuses: list[str] | None = None,
        risk_levels: list[str] | None = None,
        search: str = "",
        limit: int = 100,
    ) -> list[ActionLifecycleRecord]:
        query = select(s.action_lifecycle_records)
        if account_id:
            query = query.where(s.action_lifecycle_records.c.account_id == account_record_id(DEFAULT_CLIENT_ID, account_id))
        if workspace_id:
            query = query.where(s.action_lifecycle_records.c.workspace_id == workspace_id)
        if statuses:
            query = query.where(s.action_lifecycle_records.c.status.in_(statuses))
        if risk_levels:
            query = query.where(s.action_lifecycle_records.c.risk_level.in_(risk_levels))
        if search.strip():
            pattern = f"%{search.strip()}%"
            query = query.where(
                or_(
                    s.action_lifecycle_records.c.id.ilike(pattern),
                    s.action_lifecycle_records.c.entity_type.ilike(pattern),
                    s.action_lifecycle_records.c.entity_id.ilike(pattern),
                    s.action_lifecycle_records.c.operation.ilike(pattern),
                    s.action_lifecycle_records.c.status.ilike(pattern),
                    s.action_lifecycle_records.c.risk_level.ilike(pattern),
                )
            )
        query = query.order_by(s.action_lifecycle_records.c.updated_at.desc()).limit(max(1, min(limit, 200)))
        with self.tx() as conn:
            rows = conn.execute(query).mappings().all()
        return [_lifecycle(row) for row in rows]

    def save_preflight_check(self, check: ActionPreflightCheck) -> ActionPreflightCheck:
        now = utc_now()
        checked_at = _dt(check.checked_at) or now
        row_id = check.id or new_id("preflight")
        with self.tx() as conn:
            conn.execute(
                insert(s.action_preflight_checks).values(
                    id=row_id,
                    action_id=check.action_id,
                    result=check.result,
                    blocked_reasons_json=clean_json(check.blocked_reasons),
                    missing_data_json=clean_json(check.missing_data),
                    feature_flags_json=clean_json(check.feature_flags),
                    stale_fields_json=clean_json(check.stale_fields),
                    checked_at=checked_at,
                )
            )
        return check.model_copy(update={"id": row_id, "checked_at": iso(checked_at)})

    def list_preflight_checks(self, action_id: str) -> list[ActionPreflightCheck]:
        query = (
            select(s.action_preflight_checks)
            .where(s.action_preflight_checks.c.action_id == action_id)
            .order_by(s.action_preflight_checks.c.checked_at)
        )
        with self.tx() as conn:
            rows = conn.execute(query).mappings().all()
        return [_preflight_check(row) for row in rows]

    def save_approval_event(self, event: ActionApprovalEvent) -> ActionApprovalEvent:
        now = utc_now()
        created_at = _dt(event.created_at) or now
        row_id = event.id or new_id("approval")
        with self.tx() as conn:
            approver = ensure_user_reference(conn, event.approver)
            conn.execute(
                insert(s.action_approval_events).values(
                    id=row_id,
                    action_id=event.action_id,
                    approver=approver,
                    approval_status=event.approval_status,
                    risk_summary=event.risk_summary,
                    scope_json=clean_json(event.scope),
                    created_at=created_at,
                )
            )
        return event.model_copy(update={"id": row_id, "created_at": iso(created_at)})

    def list_approval_events(self, action_id: str) -> list[ActionApprovalEvent]:
        query = (
            select(s.action_approval_events)
            .where(s.action_approval_events.c.action_id == action_id)
            .order_by(s.action_approval_events.c.created_at)
        )
        with self.tx() as conn:
            rows = conn.execute(query).mappings().all()
        return [_approval_event(row) for row in rows]

    def save_confirmation_event(self, event: ActionConfirmationEvent) -> ActionConfirmationEvent:
        now = utc_now()
        created_at = _dt(event.created_at) or now
        row_id = event.id or new_id("confirmation")
        with self.tx() as conn:
            confirmed_by = ensure_user_reference(conn, event.confirmed_by)
            conn.execute(
                insert(s.action_confirmation_events).values(
                    id=row_id,
                    action_id=event.action_id,
                    confirmed_by=confirmed_by,
                    confirmation_text=event.confirmation_text,
                    confirmation_version=event.confirmation_version,
                    created_at=created_at,
                )
            )
        return event.model_copy(update={"id": row_id, "created_at": iso(created_at)})

    def list_confirmation_events(self, action_id: str) -> list[ActionConfirmationEvent]:
        query = (
            select(s.action_confirmation_events)
            .where(s.action_confirmation_events.c.action_id == action_id)
            .order_by(s.action_confirmation_events.c.created_at)
        )
        with self.tx() as conn:
            rows = conn.execute(query).mappings().all()
        return [_confirmation_event(row) for row in rows]

    def save_execution_attempt(self, attempt: ActionExecutionAttempt) -> ActionExecutionAttempt:
        now = utc_now()
        created_at = _dt(attempt.created_at) or now
        finished_at = _dt(attempt.finished_at)
        row_id = attempt.id or new_id("attempt")
        attempt_id = attempt.attempt_id or row_id
        with self.tx() as conn:
            conn.execute(
                insert(s.action_execution_attempts)
                .values(
                    id=row_id,
                    action_id=attempt.action_id,
                    attempt_id=attempt_id,
                    idempotency_key=attempt.idempotency_key,
                    provider_mode=attempt.provider_mode,
                    result=attempt.result,
                    error_class=attempt.error_class,
                    trace_id=attempt.trace_id,
                    request_summary_json=clean_json(attempt.request_summary),
                    provider_response_summary_json=clean_json(attempt.provider_response_summary),
                    created_at=created_at,
                    finished_at=finished_at,
                )
                .on_conflict_do_update(
                    index_elements=[s.action_execution_attempts.c.idempotency_key],
                    set_={
                        "result": attempt.result,
                        "error_class": attempt.error_class,
                        "trace_id": attempt.trace_id,
                        "provider_response_summary_json": clean_json(attempt.provider_response_summary),
                        "finished_at": finished_at,
                    },
                )
            )
        return attempt.model_copy(update={"id": row_id, "attempt_id": attempt_id, "created_at": iso(created_at), "finished_at": iso(finished_at) if finished_at else ""})

    def get_execution_attempt_by_idempotency_key(self, idempotency_key: str) -> ActionExecutionAttempt | None:
        with self.tx() as conn:
            row = (
                conn.execute(
                    select(s.action_execution_attempts).where(
                        s.action_execution_attempts.c.idempotency_key == idempotency_key
                    )
                )
                .mappings()
                .first()
            )
        return _execution_attempt(row) if row else None

    def list_execution_attempts(self, action_id: str) -> list[ActionExecutionAttempt]:
        query = (
            select(s.action_execution_attempts)
            .where(s.action_execution_attempts.c.action_id == action_id)
            .order_by(s.action_execution_attempts.c.created_at)
        )
        with self.tx() as conn:
            rows = conn.execute(query).mappings().all()
        return [_execution_attempt(row) for row in rows]

    def save_audit_event(self, event: ActionAuditEvent) -> ActionAuditEvent:
        now = utc_now()
        created_at = _dt(event.created_at) or now
        row_id = event.id or new_id("audit")
        with self.tx() as conn:
            actor = ensure_user_reference(conn, event.actor)
            conn.execute(
                insert(s.action_audit_events).values(
                    id=row_id,
                    action_id=event.action_id,
                    from_status=event.from_status,
                    to_status=event.to_status,
                    actor=actor,
                    event_type=event.event_type,
                    metadata_summary_json=clean_json(event.metadata),
                    created_at=created_at,
                )
            )
        return event.model_copy(update={"id": row_id, "created_at": iso(created_at)})

    def list_audit_events(self, action_id: str) -> list[ActionAuditEvent]:
        query = (
            select(s.action_audit_events)
            .where(s.action_audit_events.c.action_id == action_id)
            .order_by(s.action_audit_events.c.created_at)
        )
        with self.tx() as conn:
            rows = conn.execute(query).mappings().all()
        return [_audit_event(row) for row in rows]

    def save_rollback_note(self, note: ActionRollbackNote) -> ActionRollbackNote:
        now = utc_now()
        created_at = _dt(note.created_at) or now
        row_id = note.id or new_id("rollback_note")
        with self.tx() as conn:
            created_by = ensure_user_reference(conn, note.created_by)
            conn.execute(
                insert(s.action_rollback_notes).values(
                    id=row_id,
                    action_id=note.action_id,
                    original_values_json=clean_json(note.original_values),
                    recommended_manual_recovery=note.recommended_manual_recovery,
                    created_by=created_by,
                    created_at=created_at,
                )
            )
        return note.model_copy(update={"id": row_id, "created_at": iso(created_at)})

    def list_rollback_notes(self, action_id: str) -> list[ActionRollbackNote]:
        query = (
            select(s.action_rollback_notes)
            .where(s.action_rollback_notes.c.action_id == action_id)
            .order_by(s.action_rollback_notes.c.created_at)
        )
        with self.tx() as conn:
            rows = conn.execute(query).mappings().all()
        return [_rollback_note(row) for row in rows]


def _lifecycle(row: Any) -> ActionLifecycleRecord:
    return ActionLifecycleRecord(
        id=str(row["id"]),
        workspace_id=str(row["workspace_id"] or ""),
        account_id=provider_account_id(str(row["account_id"])),
        entity_type=str(row["entity_type"]),
        entity_id=str(row["entity_id"]),
        operation=str(row["operation"]),
        status=row["status"],
        risk_level=str(row["risk_level"]),
        created_by=str(row["created_by"]),
        evidence=list(row["evidence_json"] or []),
        assumptions=list(row["assumptions_json"] or []),
        missing_data=list(row["missing_data_json"] or []),
        current_value=dict(row["current_value_json"] or {}),
        proposed_value=dict(row["proposed_value_json"] or {}),
        metadata=dict(row["metadata_json"] or {}),
        created_at=iso(row["created_at"]),
        updated_at=iso(row["updated_at"]),
    )


def _preflight_check(row: Any) -> ActionPreflightCheck:
    return ActionPreflightCheck(
        id=str(row["id"]),
        action_id=str(row["action_id"]),
        result=row["result"],
        blocked_reasons=list(row["blocked_reasons_json"] or []),
        missing_data=list(row["missing_data_json"] or []),
        feature_flags=dict(row["feature_flags_json"] or {}),
        stale_fields=list(row["stale_fields_json"] or []),
        checked_at=iso(row["checked_at"]),
    )


def _approval_event(row: Any) -> ActionApprovalEvent:
    return ActionApprovalEvent(
        id=str(row["id"]),
        action_id=str(row["action_id"]),
        approver=str(row["approver"]),
        approval_status=row["approval_status"],
        risk_summary=str(row["risk_summary"] or ""),
        scope=dict(row["scope_json"] or {}),
        created_at=iso(row["created_at"]),
    )


def _confirmation_event(row: Any) -> ActionConfirmationEvent:
    return ActionConfirmationEvent(
        id=str(row["id"]),
        action_id=str(row["action_id"]),
        confirmed_by=str(row["confirmed_by"]),
        confirmation_text=str(row["confirmation_text"]),
        confirmation_version=str(row["confirmation_version"] or "v1"),
        created_at=iso(row["created_at"]),
    )


def _execution_attempt(row: Any) -> ActionExecutionAttempt:
    return ActionExecutionAttempt(
        id=str(row["id"]),
        action_id=str(row["action_id"]),
        attempt_id=str(row["attempt_id"]),
        idempotency_key=str(row["idempotency_key"]),
        provider_mode=row["provider_mode"],
        result=row["result"],
        error_class=str(row["error_class"] or ""),
        trace_id=str(row["trace_id"] or ""),
        request_summary=dict(row["request_summary_json"] or {}),
        provider_response_summary=dict(row["provider_response_summary_json"] or {}),
        created_at=iso(row["created_at"]),
        finished_at=iso(row["finished_at"]) if row["finished_at"] else "",
    )


def _audit_event(row: Any) -> ActionAuditEvent:
    return ActionAuditEvent(
        id=str(row["id"]),
        action_id=str(row["action_id"]),
        from_status=str(row["from_status"] or ""),
        to_status=str(row["to_status"] or ""),
        actor=str(row["actor"] or ""),
        event_type=str(row["event_type"]),
        metadata=dict(row["metadata_summary_json"] or {}),
        created_at=iso(row["created_at"]),
    )


def _rollback_note(row: Any) -> ActionRollbackNote:
    return ActionRollbackNote(
        id=str(row["id"]),
        action_id=str(row["action_id"]),
        original_values=dict(row["original_values_json"] or {}),
        recommended_manual_recovery=str(row["recommended_manual_recovery"] or ""),
        created_by=str(row["created_by"] or ""),
        created_at=iso(row["created_at"]),
    )


def _dt(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
