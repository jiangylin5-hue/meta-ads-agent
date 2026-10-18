from __future__ import annotations

from typing import Any

from ..models import (
    ActionApprovalEvent,
    ActionAuditEvent,
    ActionConfirmationEvent,
    ActionLifecycleRecord,
    ActionLifecycleStatus,
    ActionPreflightCheck,
    ActionRollbackNote,
    OptimizationActionDraft,
)
from ..repositories.action_repository import ActionRepository


class ActionStateConflict(RuntimeError):
    pass


class ActionNotFound(RuntimeError):
    pass


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "suggested": {"draft_created", "cancelled", "blocked", "stale"},
    "draft_created": {"approved", "cancelled", "blocked", "stale", "dry_run_only"},
    "approved": {"confirmed", "cancelled", "blocked", "stale", "dry_run_only"},
    "confirmed": {"executing", "blocked", "stale", "dry_run_only"},
    "executing": {"executed", "failed", "blocked"},
    "stale": {"draft_created", "cancelled", "blocked"},
    "dry_run_only": {"approved", "confirmed", "cancelled", "blocked", "stale"},
    "executed": set(),
    "failed": set(),
    "blocked": set(),
    "cancelled": set(),
}


class ActionOperationsService:
    def __init__(self, repository: Any | None = None) -> None:
        self.repository = repository or ActionRepository()

    def transition_action(
        self,
        action_id: str,
        to_status: ActionLifecycleStatus,
        actor: str,
        event_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> ActionLifecycleRecord:
        record = self.repository.get_lifecycle_record(action_id)
        if not record:
            raise ActionNotFound(f"Action {action_id} not found.")
        allowed = ALLOWED_TRANSITIONS.get(record.status, set())
        if to_status not in allowed:
            raise ActionStateConflict(f"Illegal action transition: {record.status} -> {to_status}.")
        updated = record.model_copy(update={"status": to_status})
        saved = self.repository.save_lifecycle_record(updated)
        self.repository.save_audit_event(
            ActionAuditEvent(
                action_id=action_id,
                from_status=record.status,
                to_status=to_status,
                actor=actor,
                event_type=event_type,
                metadata=metadata or {},
            )
        )
        return saved

    def create_from_optimization_draft(self, draft: OptimizationActionDraft) -> ActionLifecycleRecord:
        action = draft.action or {}
        payload = draft.draft_payload or {}
        operation = str(payload.get("action_type") or action.get("action_type") or action.get("operation") or "manual_review")
        entity_type = str(payload.get("target_level") or action.get("target_level") or action.get("entity_type") or "unknown")
        entity_id = str(payload.get("target_id") or action.get("target_id") or action.get("entity_id") or "")
        evidence = _list_of_dicts(action.get("evidence_items") or payload.get("evidence") or action.get("evidence"))
        record = ActionLifecycleRecord(
            id=str(action.get("id") or f"act_{draft.id}"),
            workspace_id=str(action.get("session_id") or ""),
            account_id=draft.account_id,
            entity_type=entity_type,
            entity_id=entity_id,
            operation=operation,
            status="draft_created",
            risk_level=str(action.get("risk_level") or action.get("risk") or payload.get("risk_level") or "medium"),
            created_by=str(action.get("created_by") or "local_user"),
            evidence=evidence,
            assumptions=_list_of_strings(action.get("assumptions") or payload.get("assumptions")),
            missing_data=_list_of_strings(action.get("missing_data") or payload.get("missing_data")),
            current_value=_dict_value(action.get("current_value") or payload.get("current_value")),
            proposed_value=_dict_value(payload.get("proposed_changes") or action.get("proposed_value")),
            metadata={"optimization_draft_id": draft.id, "source": draft.source},
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )
        saved = self.repository.save_lifecycle_record(record)
        self.repository.save_audit_event(
            ActionAuditEvent(
                action_id=saved.id,
                from_status="",
                to_status="draft_created",
                actor=saved.created_by,
                event_type="draft_created",
                metadata={"optimization_draft_id": draft.id},
            )
        )
        return saved

    def get_queue(
        self,
        account_id: str = "",
        workspace_id: str = "",
        statuses: list[str] | None = None,
        risk_levels: list[str] | None = None,
        search: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        records = self.repository.list_queue_records(
            account_id=account_id,
            workspace_id=workspace_id,
            statuses=statuses,
            risk_levels=risk_levels,
            search=search,
            limit=limit,
        )
        items = [_queue_item(record) for record in records]
        return {"items": items, "actions": items, "total": len(items)}

    def run_preflight(
        self,
        action_id: str,
        current_value: dict[str, Any] | None = None,
        feature_flags: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = self.repository.get_lifecycle_record(action_id)
        if not record:
            raise ActionNotFound(f"Action {action_id} not found.")
        flags = feature_flags or {}
        result = "allowed"
        blocked_reasons: list[str] = []
        stale_fields: list[str] = []
        if current_value:
            for key, value in current_value.items():
                if key in record.current_value and record.current_value[key] != value:
                    stale_fields.append(key)
            if stale_fields:
                result = "stale"
                blocked_reasons.append("current value is stale")
        if result == "allowed" and record.missing_data:
            result = "blocked"
            blocked_reasons.append(f"missing data: {', '.join(record.missing_data)}")
        if result == "allowed" and "budget" in record.operation.lower() and not flags.get("allow_live_budget_write"):
            result = "dry_run_only"
            blocked_reasons.append("budget live write is disabled")
        check = self.repository.save_preflight_check(
            ActionPreflightCheck(
                action_id=action_id,
                result=result,  # type: ignore[arg-type]
                blocked_reasons=blocked_reasons,
                missing_data=record.missing_data,
                feature_flags=flags,
                stale_fields=stale_fields,
            )
        )
        return {"preflight": check.model_dump()}

    def approve_action(
        self,
        action_id: str,
        approver: str,
        risk_summary: str,
        scope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = self.repository.get_lifecycle_record(action_id)
        if not record:
            raise ActionNotFound(f"Action {action_id} not found.")
        latest_preflight = self._latest_preflight(action_id)
        if not latest_preflight or latest_preflight.result not in {"allowed", "dry_run_only"}:
            raise ActionStateConflict("Approval requires a latest allowed or dry_run_only preflight.")
        if not risk_summary.strip():
            raise ValueError("risk_summary is required.")
        approval = self.repository.save_approval_event(
            ActionApprovalEvent(
                action_id=action_id,
                approver=approver,
                approval_status="approved",
                risk_summary=risk_summary,
                scope=scope or {},
            )
        )
        action = self.transition_action(action_id, "approved", actor=approver, event_type="approved")
        return {"action": _detail_action(action), "approval": approval.model_dump()}

    def confirm_action(
        self,
        action_id: str,
        confirmed_by: str,
        confirmation_text: str,
        confirmation_version: str = "v1",
    ) -> dict[str, Any]:
        record = self.repository.get_lifecycle_record(action_id)
        if not record:
            raise ActionNotFound(f"Action {action_id} not found.")
        if record.status != "approved":
            raise ActionStateConflict("Final confirmation requires approved status.")
        latest_preflight = self._latest_preflight(action_id)
        if not latest_preflight or latest_preflight.result not in {"allowed", "dry_run_only"}:
            raise ActionStateConflict("Final confirmation requires a latest allowed or dry_run_only preflight.")
        if not confirmation_text.strip():
            raise ValueError("confirmation_text is required.")
        confirmation = self.repository.save_confirmation_event(
            ActionConfirmationEvent(
                action_id=action_id,
                confirmed_by=confirmed_by,
                confirmation_text=confirmation_text,
                confirmation_version=confirmation_version,
            )
        )
        action = self.transition_action(action_id, "confirmed", actor=confirmed_by, event_type="confirmed")
        return {"action": _detail_action(action), "confirmation": confirmation.model_dump()}

    def get_detail(self, action_id: str) -> dict[str, Any]:
        record = self.repository.get_lifecycle_record(action_id)
        if not record:
            raise ActionNotFound(f"Action {action_id} not found.")
        preflight_checks = self._list_records("list_preflight_checks", action_id)
        approval_events = self._list_records("list_approval_events", action_id)
        confirmation_events = self._list_records("list_confirmation_events", action_id)
        execution_attempts = self._list_records("list_execution_attempts", action_id)
        rollback_notes = self._list_records("list_rollback_notes", action_id)
        audit_events = self._list_records("list_audit_events", action_id)
        return {
            "action": _detail_action(record),
            "preflight_checks": [item.model_dump() for item in preflight_checks],
            "approval_events": [item.model_dump() for item in approval_events],
            "confirmation_events": [item.model_dump() for item in confirmation_events],
            "execution_attempts": [item.model_dump() for item in execution_attempts],
            "audit_timeline": [event.model_dump() for event in audit_events],
            "audit_events": [event.model_dump() for event in audit_events],
            "rollback_notes": [item.model_dump() for item in rollback_notes],
            "execution": {
                "has_execution_log": False,
                "account_change_claim_allowed": False,
            },
            "controls": self._controls(record),
        }

    def get_attempts(self, action_id: str) -> dict[str, Any]:
        if not self.repository.get_lifecycle_record(action_id):
            raise ActionNotFound(f"Action {action_id} not found.")
        attempts = self._list_records("list_execution_attempts", action_id)
        return {"attempts": [attempt.model_dump() for attempt in attempts]}

    def create_rollback_note(
        self,
        action_id: str,
        original_values: dict[str, Any] | None = None,
        recommended_manual_recovery: str = "",
        created_by: str = "local_user",
    ) -> dict[str, Any]:
        record = self.repository.get_lifecycle_record(action_id)
        if not record:
            raise ActionNotFound(f"Action {action_id} not found.")
        if not recommended_manual_recovery.strip():
            raise ValueError("recommended_manual_recovery is required.")
        note = self.repository.save_rollback_note(
            ActionRollbackNote(
                action_id=action_id,
                original_values=original_values or {},
                recommended_manual_recovery=recommended_manual_recovery,
                created_by=created_by,
            )
        )
        self.repository.save_audit_event(
            ActionAuditEvent(
                action_id=action_id,
                from_status=record.status,
                to_status=record.status,
                actor=created_by,
                event_type="rollback_note",
                metadata={"manual_recovery_only": True},
            )
        )
        return {"rollback_note": note.model_dump()}

    def _list_records(self, method_name: str, action_id: str) -> list[Any]:
        if not hasattr(self.repository, method_name):
            return []
        return list(getattr(self.repository, method_name)(action_id))

    def _latest_preflight(self, action_id: str) -> ActionPreflightCheck | None:
        if not hasattr(self.repository, "list_preflight_checks"):
            return None
        checks = self.repository.list_preflight_checks(action_id)
        return checks[-1] if checks else None

    def _latest_approval(self, action_id: str):
        if not hasattr(self.repository, "list_approval_events"):
            return None
        events = self.repository.list_approval_events(action_id)
        return events[-1] if events else None

    def _latest_confirmation(self, action_id: str):
        if not hasattr(self.repository, "list_confirmation_events"):
            return None
        events = self.repository.list_confirmation_events(action_id)
        return events[-1] if events else None

    def _controls(self, record: ActionLifecycleRecord) -> dict[str, Any]:
        latest_preflight = self._latest_preflight(record.id)
        latest_approval = self._latest_approval(record.id)
        latest_confirmation = self._latest_confirmation(record.id)
        preflight_allows = bool(latest_preflight and latest_preflight.result in {"allowed", "dry_run_only"})
        approval_exists = bool(latest_approval and latest_approval.approval_status == "approved")
        confirmation_exists = bool(latest_confirmation)
        return {
            "approve": {
                "enabled": record.status == "draft_created" and preflight_allows,
                "disabled_reason": "" if record.status == "draft_created" and preflight_allows else "Approval requires allowed preflight.",
            },
            "confirm": {
                "enabled": record.status == "approved" and approval_exists and preflight_allows,
                "disabled_reason": "" if record.status == "approved" and approval_exists and preflight_allows else "Final confirmation requires approval and valid preflight.",
            },
            "execute": {
                "enabled": False,
                "disabled_reason": "Execution is implemented in S6-P4 after confirmation and write_service gates.",
            },
        }


def action_operations_service() -> ActionOperationsService:
    return ActionOperationsService()


def _queue_item(record: ActionLifecycleRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "workspace_id": record.workspace_id,
        "account_id": record.account_id,
        "entity_type": record.entity_type,
        "entity_id": record.entity_id,
        "operation": record.operation,
        "status": record.status,
        "risk_level": record.risk_level,
        "updated_at": record.updated_at,
    }


def _detail_action(record: ActionLifecycleRecord) -> dict[str, Any]:
    return {
        **_queue_item(record),
        "created_by": record.created_by,
        "evidence": record.evidence,
        "assumptions": record.assumptions,
        "missing_data": record.missing_data,
        "current_value": record.current_value,
        "proposed_value": record.proposed_value,
        "metadata": record.metadata,
        "created_at": record.created_at,
    }


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str) and value.strip():
        return [{"summary": value.strip()}]
    return []
