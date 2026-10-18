from __future__ import annotations

from typing import Any

from .action_execution import action_execution_service
from .action_operations import ActionNotFound, ActionStateConflict
from .action_queue_backend import ActionQueueJob, action_queue_backend


class ActionExecutionWorker:
    def __init__(self, queue_backend: Any | None = None, execution_service: Any | None = None) -> None:
        self.queue_backend = queue_backend or action_queue_backend()
        self.execution_service = execution_service or action_execution_service()

    def process_next(self, recover_stale: bool = True, stale_min_idle_ms: int = 60000) -> dict[str, Any]:
        if hasattr(self.queue_backend, "requeue_due_retries"):
            self.queue_backend.requeue_due_retries()
        item = self.queue_backend.read_next()
        recovered = False
        if not item and recover_stale and hasattr(self.queue_backend, "claim_stale_pending"):
            item = self.queue_backend.claim_stale_pending(min_idle_ms=stale_min_idle_ms)
            recovered = bool(item)
        if not item:
            return {"processed": False, "acknowledged": False}
        message_id, job = item
        try:
            execution = self.execution_service.execute_confirmed_action(
                action_id=job.action_id,
                actor_user_id=job.actor_user_id,
                client_id=job.client_id,
                feature_flags=job.feature_flags,
            )
        except (ActionNotFound, ActionStateConflict) as exc:
            self.queue_backend.move_to_dlq(job, reason=str(exc))
            self.queue_backend.ack(message_id)
            return {"processed": True, "acknowledged": True, "dlq": True, "recovered": recovered, "reason": str(exc)}
        except Exception as exc:
            return self._retry_or_dlq(message_id, job, str(exc), recovered=recovered)

        if not _has_durable_evidence(execution):
            self.queue_backend.move_to_dlq(job, reason="missing durable execution evidence")
            return {"processed": True, "acknowledged": False, "recovered": recovered, "execution": execution}
        self.queue_backend.ack(message_id)
        return {"processed": True, "acknowledged": True, "recovered": recovered, "execution": execution}

    def _retry_or_dlq(self, message_id: str, job: ActionQueueJob, reason: str, recovered: bool = False) -> dict[str, Any]:
        if job.retry_count >= job.max_retries:
            self.queue_backend.move_to_dlq(job, reason=reason)
            self.queue_backend.ack(message_id)
            return {"processed": True, "acknowledged": True, "dlq": True, "recovered": recovered, "reason": reason}
        retry_job = job
        retry_job.retry_count += 1
        self.queue_backend.enqueue_retry(retry_job, reason=reason)
        self.queue_backend.ack(message_id)
        return {"processed": True, "acknowledged": True, "retry": True, "recovered": recovered, "reason": reason}


def _has_durable_evidence(execution: dict[str, Any]) -> bool:
    if execution.get("execution_log"):
        return True
    attempt = execution.get("attempt") if isinstance(execution.get("attempt"), dict) else {}
    return bool(execution.get("dry_run_plan") and attempt.get("result") == "dry_run_only")
