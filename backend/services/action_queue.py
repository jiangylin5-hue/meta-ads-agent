from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

from ..models import ActionAuditEvent, ActionExecutionAttempt
from ..repositories.action_repository import ActionRepository
from .action_execution import _idempotency_key
from .action_operations import ActionNotFound, ActionOperationsService, ActionStateConflict
from .action_queue_backend import ActionQueueJob, action_queue_backend


TERMINAL_ATTEMPT_RESULTS = {"executed", "failed", "blocked", "dry_run_only"}


class ActionQueueService:
    def __init__(self, repository: Any | None = None, queue_backend: Any | None = None) -> None:
        self.repository = repository or ActionRepository()
        self.queue_backend = queue_backend or action_queue_backend()
        self.operations = ActionOperationsService(repository=self.repository)

    def enqueue_execution(
        self,
        action_id: str,
        actor_user_id: str = "local_user",
        client_id: str = "",
        feature_flags: dict[str, Any] | None = None,
        trace_id: str = "",
    ) -> dict[str, Any]:
        action = self.repository.get_lifecycle_record(action_id)
        if not action:
            raise ActionNotFound(f"Action {action_id} not found.")
        if action.status != "confirmed":
            raise ActionStateConflict("Execution enqueue requires confirmed status.")

        latest_preflight = self.operations._latest_preflight(action_id)
        if not latest_preflight or latest_preflight.result not in {"allowed", "dry_run_only"}:
            raise ActionStateConflict("Execution enqueue requires an allowed or dry_run_only preflight.")
        latest_approval = self.operations._latest_approval(action_id)
        if not latest_approval or latest_approval.approval_status != "approved":
            raise ActionStateConflict("Execution enqueue requires approval.")
        latest_confirmation = self.operations._latest_confirmation(action_id)
        if not latest_confirmation:
            raise ActionStateConflict("Final confirmation is required before execution enqueue.")

        idempotency_key = _idempotency_key(action)
        existing = self._existing_attempt(idempotency_key)
        if existing and existing.result in TERMINAL_ATTEMPT_RESULTS:
            return {"queued": False, "idempotent_replay": True, "attempt": _safe_attempt_payload(existing)}
        if existing and existing.request_summary.get("queue_status") == "enqueued":
            return {
                "queued": True,
                "idempotent_replay": True,
                "attempt": _safe_attempt_payload(existing),
                "job": existing.request_summary.get("queue_job", {}),
            }

        attempt_id = f"attempt_{uuid4().hex}"
        job = ActionQueueJob(
            action_id=action.id,
            attempt_id=attempt_id,
            idempotency_key=_queue_safe_idempotency_key(idempotency_key),
            account_id=action.account_id,
            client_id=client_id,
            actor_user_id=actor_user_id,
            operation=action.operation,
            entity_type=action.entity_type,
            entity_id=action.entity_id,
            preflight_check_id=latest_preflight.id,
            approval_event_id=latest_approval.id,
            confirmation_event_id=latest_confirmation.id,
            confirmation_version=latest_confirmation.confirmation_version,
            feature_flags=feature_flags or {},
            trace_id=trace_id,
        )
        attempt = self.repository.save_execution_attempt(
            ActionExecutionAttempt(
                action_id=action.id,
                attempt_id=attempt_id,
                idempotency_key=idempotency_key,
                provider_mode="dry_run" if latest_preflight.result == "dry_run_only" else "simulator",
                result="pending",
                trace_id=trace_id,
                request_summary={
                    "action_id": action.id,
                    "queue_status": "enqueued",
                    "queue_job": job.to_payload(),
                },
            )
        )
        message_id = self.queue_backend.enqueue_ready(job)
        if hasattr(self.repository, "save_audit_event"):
            self.repository.save_audit_event(
                ActionAuditEvent(
                    action_id=action.id,
                    from_status=action.status,
                    to_status=action.status,
                    actor=actor_user_id,
                    event_type="execution_queued",
                    metadata={"job_id": job.job_id, "message_id": message_id, "attempt_id": attempt.attempt_id},
                )
            )
        return {
            "queued": True,
            "idempotent_replay": False,
            "message_id": message_id,
            "job": job.to_payload(),
            "attempt": _safe_attempt_payload(attempt),
        }

    def _existing_attempt(self, idempotency_key: str):
        if not hasattr(self.repository, "get_execution_attempt_by_idempotency_key"):
            return None
        return self.repository.get_execution_attempt_by_idempotency_key(idempotency_key)


def action_queue_service() -> ActionQueueService:
    return ActionQueueService()


def _queue_safe_idempotency_key(idempotency_key: str) -> str:
    return "sha256:" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()


def _safe_attempt_payload(attempt: ActionExecutionAttempt) -> dict[str, Any]:
    payload = attempt.model_dump()
    payload["idempotency_key"] = _queue_safe_idempotency_key(attempt.idempotency_key)
    request_summary = dict(payload.get("request_summary") or {})
    if "queue_job" in request_summary and isinstance(request_summary["queue_job"], dict):
        request_summary["queue_job"] = dict(request_summary["queue_job"])
        request_summary["queue_job"]["idempotency_key"] = _queue_safe_idempotency_key(attempt.idempotency_key)
    payload["request_summary"] = request_summary
    return payload
