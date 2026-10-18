from __future__ import annotations

import json
from typing import Any

from ..models import ActionExecutionAttempt, ActionLifecycleRecord
from ..repositories.action_repository import ActionRepository
from .action_operations import ActionNotFound, ActionOperationsService, ActionStateConflict
from .write_service import write_service


class ProviderSimulator:
    def apply(self, action: ActionLifecycleRecord) -> dict[str, Any]:
        if action.metadata.get("simulate_provider_failure"):
            return {
                "status": "failed",
                "error": "simulated provider failure",
                "affected_entity": {
                    "entity_type": action.entity_type,
                    "entity_id": action.entity_id,
                },
            }
        return {
            "status": "executed",
            "affected_entity": {
                "entity_type": action.entity_type,
                "entity_id": action.entity_id,
            },
            "applied": {
                "operation": action.operation,
                "value": action.proposed_value,
            },
        }


class ActionExecutionService:
    def __init__(self, repository: Any | None = None, write_service: Any | None = None, provider: ProviderSimulator | None = None) -> None:
        self.repository = repository or ActionRepository()
        self.write_service = write_service or write_service_factory()
        self.provider = provider or ProviderSimulator()
        self.operations = ActionOperationsService(repository=self.repository)

    def execute_confirmed_action(
        self,
        action_id: str,
        actor_user_id: str = "local_user",
        client_id: str = "",
        feature_flags: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        action = self.repository.get_lifecycle_record(action_id)
        if not action:
            raise ActionNotFound(f"Action {action_id} not found.")
        idempotency_key = _idempotency_key(action)
        if hasattr(self.repository, "get_execution_attempt_by_idempotency_key"):
            existing = self.repository.get_execution_attempt_by_idempotency_key(idempotency_key)
            if existing and existing.result != "pending":
                return {
                    "action": action.model_dump(),
                    "attempt": existing.model_dump(),
                    "idempotent_replay": True,
                }
        if action.status != "confirmed":
            raise ActionStateConflict("Execution requires confirmed status.")
        latest_preflight = self.operations._latest_preflight(action_id)
        if not latest_preflight or latest_preflight.result not in {"allowed", "dry_run_only"}:
            raise ActionStateConflict("Execution requires an allowed or dry_run_only preflight.")

        if _is_budget_operation(action) and not (feature_flags or {}).get("allow_live_budget_write"):
            attempt = self.repository.save_execution_attempt(
                ActionExecutionAttempt(
                    action_id=action.id,
                    idempotency_key=idempotency_key,
                    provider_mode="dry_run",
                    result="dry_run_only",
                    request_summary=_request_summary(action),
                    provider_response_summary={"dry_run": True},
                )
            )
            updated = self.operations.transition_action(action.id, "dry_run_only", actor=actor_user_id, event_type="dry_run_only")
            return {
                "action": updated.model_dump(),
                "attempt": attempt.model_dump(),
                "dry_run_plan": {"operation": action.operation, "proposed_value": action.proposed_value},
                "idempotent_replay": False,
            }

        pending = self.repository.save_execution_attempt(
            ActionExecutionAttempt(
                action_id=action.id,
                idempotency_key=idempotency_key,
                provider_mode="simulator",
                result="pending",
                request_summary=_request_summary(action),
            )
        )
        executing = self.operations.transition_action(action.id, "executing", actor=actor_user_id, event_type="executing")
        provider_result = self.provider.apply(executing)
        execution_log = self.write_service.execute_stage06_action(
            executing,
            actor_user_id=actor_user_id,
            provider_result=provider_result,
            client_id=client_id,
        )
        final_status = "executed" if provider_result.get("status") == "executed" else "failed"
        attempt = self.repository.save_execution_attempt(
            pending.model_copy(
                update={
                    "result": final_status,
                    "error_class": "" if final_status == "executed" else "provider_error",
                    "provider_response_summary": provider_result,
                }
            )
        )
        updated = self.operations.transition_action(action.id, final_status, actor=actor_user_id, event_type=final_status)
        return {
            "action": updated.model_dump(),
            "attempt": attempt.model_dump(),
            "execution_log": execution_log.model_dump(),
            "idempotent_replay": False,
        }


def action_execution_service() -> ActionExecutionService:
    return ActionExecutionService()


def write_service_factory():
    return write_service()


def _is_budget_operation(action: ActionLifecycleRecord) -> bool:
    return "budget" in action.operation.lower()


def _request_summary(action: ActionLifecycleRecord) -> dict[str, Any]:
    return {
        "action_id": action.id,
        "account_id": action.account_id,
        "entity_type": action.entity_type,
        "entity_id": action.entity_id,
        "operation": action.operation,
        "proposed_value": action.proposed_value,
    }


def _idempotency_key(action: ActionLifecycleRecord) -> str:
    value = json.dumps(action.proposed_value, sort_keys=True, ensure_ascii=True)
    return f"{action.id}:{action.operation}:{action.entity_type}:{action.entity_id}:{value}"
