from __future__ import annotations

from backend.models import ActionExecutionAttempt, ActionLifecycleRecord, ActionPreflightCheck, ExecutionLogRecord
from fastapi.testclient import TestClient

from backend.main import app


class FakeExecutionRepository:
    def __init__(self, operation: str = "pause", status: str = "confirmed", preflight_result: str = "allowed", fail_provider: bool = False) -> None:
        self.record = ActionLifecycleRecord(
            id="act_1",
            workspace_id="workspace_1",
            account_id="act_123",
            entity_type="campaign",
            entity_id="cmp_1",
            operation=operation,
            status=status,
            risk_level="high",
            created_by="local_user",
            current_value={"status": "ACTIVE", "daily_budget": 100},
            proposed_value={"status": "PAUSED", "daily_budget": 120},
            metadata={"simulate_provider_failure": fail_provider},
        )
        self.preflights = [ActionPreflightCheck(action_id="act_1", result=preflight_result)]
        self.attempts: dict[str, ActionExecutionAttempt] = {}
        self.saved_records: list[ActionLifecycleRecord] = []
        self.audit_events = []

    def get_lifecycle_record(self, action_id: str):
        return self.record if action_id == self.record.id else None

    def save_lifecycle_record(self, record: ActionLifecycleRecord, client_id: str = ""):
        self.record = record
        self.saved_records.append(record)
        return record

    def list_preflight_checks(self, action_id: str):
        return self.preflights

    def get_execution_attempt_by_idempotency_key(self, idempotency_key: str):
        return self.attempts.get(idempotency_key)

    def save_execution_attempt(self, attempt: ActionExecutionAttempt):
        self.attempts[attempt.idempotency_key] = attempt
        return attempt

    def save_audit_event(self, event):
        self.audit_events.append(event)
        return event


class FakeWriteService:
    def __init__(self) -> None:
        self.calls = []

    def execute_stage06_action(self, action, actor_user_id, provider_result, client_id: str = ""):
        self.calls.append((action.id, actor_user_id, provider_result))
        status = "succeeded" if provider_result["status"] == "executed" else "failed"
        return ExecutionLogRecord(
            id="exec_1",
            account_id=action.account_id,
            source_type="action_draft",
            source_id=action.id,
            actor_user_id=actor_user_id,
            status=status,
            request_summary={"operation": action.operation},
            result=provider_result,
            error=str(provider_result.get("error") or ""),
        )


def test_pause_resume_execution_uses_simulator_write_service_and_log() -> None:
    from backend.services.action_execution import ActionExecutionService, ProviderSimulator

    repository = FakeExecutionRepository(operation="pause")
    writer = FakeWriteService()
    service = ActionExecutionService(repository=repository, write_service=writer, provider=ProviderSimulator())

    result = service.execute_confirmed_action("act_1", actor_user_id="operator_1")

    assert result["action"]["status"] == "executed"
    assert result["attempt"]["result"] == "executed"
    assert result["execution_log"]["status"] == "succeeded"
    assert writer.calls[0][0] == "act_1"
    assert repository.saved_records[-1].status == "executed"


def test_provider_failure_records_failed_attempt_and_failed_lifecycle() -> None:
    from backend.services.action_execution import ActionExecutionService, ProviderSimulator

    repository = FakeExecutionRepository(operation="resume", fail_provider=True)
    writer = FakeWriteService()
    result = ActionExecutionService(repository=repository, write_service=writer, provider=ProviderSimulator()).execute_confirmed_action("act_1")

    assert result["action"]["status"] == "failed"
    assert result["attempt"]["result"] == "failed"
    assert result["execution_log"]["status"] == "failed"
    assert "simulated provider failure" in result["execution_log"]["error"]


def test_idempotent_retry_returns_existing_attempt_without_second_write() -> None:
    from backend.services.action_execution import ActionExecutionService, ProviderSimulator

    repository = FakeExecutionRepository(operation="pause")
    writer = FakeWriteService()
    service = ActionExecutionService(repository=repository, write_service=writer, provider=ProviderSimulator())

    first = service.execute_confirmed_action("act_1")
    repository.record = repository.record.model_copy(update={"status": "confirmed"})
    second = service.execute_confirmed_action("act_1")

    assert first["attempt"]["idempotency_key"] == second["attempt"]["idempotency_key"]
    assert second["idempotent_replay"] is True
    assert len(writer.calls) == 1


def test_budget_update_defaults_to_dry_run_without_provider_write() -> None:
    from backend.services.action_execution import ActionExecutionService, ProviderSimulator

    repository = FakeExecutionRepository(operation="budget_update", preflight_result="dry_run_only")
    writer = FakeWriteService()
    result = ActionExecutionService(repository=repository, write_service=writer, provider=ProviderSimulator()).execute_confirmed_action("act_1")

    assert result["action"]["status"] == "dry_run_only"
    assert result["attempt"]["result"] == "dry_run_only"
    assert result["dry_run_plan"]["operation"] == "budget_update"
    assert writer.calls == []


def test_execute_route_is_disabled_in_draft_only_demo() -> None:
    client = TestClient(app)
    response = client.post("/api/actions/drafts/act_1/execute", json={})
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "execution_disabled_in_demo"
