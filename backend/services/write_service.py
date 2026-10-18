from typing import Any

from ..config import meta_live_write_enabled
from ..models import ActionLifecycleRecord, ExecutionLogRecord, RollbackRecord
from .action_drafts import get_action_draft
from .persistent_store import PersistentStore, store


class WriteService:
    def __init__(self, repository: PersistentStore | None = None) -> None:
        self.repository = repository or store()

    def execute_action_draft(
        self,
        draft_id: str,
        client_id: str,
        actor_user_id: str = "local_user",
        confirmation_text: str = "",
    ) -> ExecutionLogRecord:
        draft = get_action_draft(draft_id)
        if not draft:
            return self._blocked(client_id, "", "action_draft", draft_id, actor_user_id, "Action draft not found.")
        if confirmation_text.strip() != "EXECUTE APPROVED ACTION":
            return self._blocked(client_id, draft.account_id, "action_draft", draft_id, actor_user_id, "Confirmation text is required.")
        if not meta_live_write_enabled():
            return self._blocked(client_id, draft.account_id, "action_draft", draft_id, actor_user_id, "META_LIVE_WRITE_ENABLED is false.")
        if draft.status != "done":
            return self._blocked(client_id, draft.account_id, "action_draft", draft_id, actor_user_id, "Action draft must be marked done/approved before execution.")
        return self.repository.save_execution_log(
            ExecutionLogRecord(
                client_id=client_id,
                account_id=draft.account_id,
                source_type="action_draft",
                source_id=draft_id,
                actor_user_id=actor_user_id,
                status="blocked",
                request_summary=draft.draft_payload,
                error="Direct action execution adapter is not implemented yet.",
            )
        )

    def execute_stage06_action(
        self,
        action: ActionLifecycleRecord,
        actor_user_id: str,
        provider_result: dict[str, Any],
        client_id: str = "",
    ) -> ExecutionLogRecord:
        status = "succeeded" if provider_result.get("status") == "executed" else "failed"
        return self.repository.save_execution_log(
            ExecutionLogRecord(
                client_id=client_id,
                account_id=action.account_id,
                source_type="action_draft",
                source_id=action.id,
                actor_user_id=actor_user_id,
                status=status,
                request_summary={
                    "action_id": action.id,
                    "operation": action.operation,
                    "entity_type": action.entity_type,
                    "entity_id": action.entity_id,
                    "proposed_value": action.proposed_value,
                },
                result=provider_result,
                error=str(provider_result.get("error") or ""),
            )
        )

    def create_rollback_plan(self, execution_id: str, actor_user_id: str = "local_user") -> RollbackRecord:
        plan = {
            "mode": "compensating_operations",
            "steps": [
                "Pause newly created entities where applicable.",
                "Restore previous budget/status values from the before snapshot when available.",
                "Record an after-rollback verification snapshot.",
            ],
            "requires_confirmation": True,
            "confirmation_text": "EXECUTE ROLLBACK",
        }
        return self.repository.save_rollback_record(
            RollbackRecord(execution_id=execution_id, actor_user_id=actor_user_id, status="draft", plan=plan)
        )

    def _blocked(
        self,
        client_id: str,
        account_id: str,
        source_type: str,
        source_id: str,
        actor_user_id: str,
        reason: str,
    ) -> ExecutionLogRecord:
        return self.repository.save_execution_log(
            ExecutionLogRecord(
                client_id=client_id,
                account_id=account_id,
                source_type=source_type,
                source_id=source_id,
                actor_user_id=actor_user_id,
                status="blocked",
                error=reason,
            )
        )


def write_service() -> WriteService:
    return WriteService()