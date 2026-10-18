from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.models import (
    ActionApprovalEvent,
    ActionAuditEvent,
    ActionConfirmationEvent,
    ActionExecutionAttempt,
    ActionLifecycleRecord,
    ActionPreflightCheck,
    ActionRollbackNote,
)


class FakePolicyRepository:
    def __init__(self, status: str = "draft_created", missing_data: list[str] | None = None, operation: str = "pause") -> None:
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
            evidence=[{"metric": "spend"}],
            missing_data=missing_data or [],
            current_value={"status": "ACTIVE"},
            proposed_value={"status": "PAUSED"},
        )
        self.preflights: list[ActionPreflightCheck] = []
        self.approvals: list[ActionApprovalEvent] = []
        self.confirmations: list[ActionConfirmationEvent] = []
        self.attempts: list[ActionExecutionAttempt] = []
        self.rollback_notes: list[ActionRollbackNote] = []
        self.audit_events: list[ActionAuditEvent] = []

    def get_lifecycle_record(self, action_id: str):
        return self.record if action_id == self.record.id else None

    def save_lifecycle_record(self, record: ActionLifecycleRecord, client_id: str = ""):
        self.record = record
        return record

    def save_preflight_check(self, check: ActionPreflightCheck):
        self.preflights.append(check)
        return check

    def list_preflight_checks(self, action_id: str):
        return [item for item in self.preflights if item.action_id == action_id]

    def save_approval_event(self, event: ActionApprovalEvent):
        self.approvals.append(event)
        return event

    def list_approval_events(self, action_id: str):
        return [item for item in self.approvals if item.action_id == action_id]

    def save_confirmation_event(self, event: ActionConfirmationEvent):
        self.confirmations.append(event)
        return event

    def list_confirmation_events(self, action_id: str):
        return [item for item in self.confirmations if item.action_id == action_id]

    def list_execution_attempts(self, action_id: str):
        return [item for item in self.attempts if item.action_id == action_id]

    def list_rollback_notes(self, action_id: str):
        return [item for item in self.rollback_notes if item.action_id == action_id]

    def save_audit_event(self, event: ActionAuditEvent):
        self.audit_events.append(event)
        return event

    def list_audit_events(self, action_id: str):
        return [event for event in self.audit_events if event.action_id == action_id]


def test_preflight_policy_returns_allowed_blocked_dry_run_and_stale_results() -> None:
    from backend.services.action_operations import ActionOperationsService

    allowed_repo = FakePolicyRepository()
    assert ActionOperationsService(allowed_repo).run_preflight("act_1")["preflight"]["result"] == "allowed"

    blocked_repo = FakePolicyRepository(missing_data=["fresh entity status"])
    blocked = ActionOperationsService(blocked_repo).run_preflight("act_1")
    assert blocked["preflight"]["result"] == "blocked"
    assert "missing data" in blocked["preflight"]["blocked_reasons"][0]

    budget_repo = FakePolicyRepository(operation="budget_update")
    dry_run = ActionOperationsService(budget_repo).run_preflight("act_1")
    assert dry_run["preflight"]["result"] == "dry_run_only"
    assert "budget" in dry_run["preflight"]["blocked_reasons"][0]

    stale_repo = FakePolicyRepository()
    stale = ActionOperationsService(stale_repo).run_preflight("act_1", current_value={"status": "PAUSED"})
    assert stale["preflight"]["result"] == "stale"
    assert stale["preflight"]["stale_fields"] == ["status"]


def test_approval_requires_successful_preflight_and_writes_audit() -> None:
    from backend.services.action_operations import ActionOperationsService, ActionStateConflict

    repository = FakePolicyRepository()
    service = ActionOperationsService(repository)

    with pytest.raises(ActionStateConflict):
        service.approve_action("act_1", approver="local_user", risk_summary="Reviewed.")

    service.run_preflight("act_1")
    approved = service.approve_action("act_1", approver="local_user", risk_summary="Reviewed.")

    assert approved["action"]["status"] == "approved"
    assert repository.approvals[-1].risk_summary == "Reviewed."
    assert repository.audit_events[-1].to_status == "approved"


def test_confirmation_requires_approval_and_keeps_execute_disabled_without_execution_phase() -> None:
    from backend.services.action_operations import ActionOperationsService, ActionStateConflict

    repository = FakePolicyRepository()
    service = ActionOperationsService(repository)

    service.run_preflight("act_1")
    with pytest.raises(ActionStateConflict):
        service.confirm_action("act_1", confirmed_by="local_user", confirmation_text="PAUSE cmp_1")

    service.approve_action("act_1", approver="local_user", risk_summary="Reviewed.")
    confirmed = service.confirm_action("act_1", confirmed_by="local_user", confirmation_text="PAUSE cmp_1")
    detail = service.get_detail("act_1")

    assert confirmed["action"]["status"] == "confirmed"
    assert repository.confirmations[-1].confirmation_text == "PAUSE cmp_1"
    assert detail["preflight_checks"][-1]["result"] == "allowed"
    assert detail["approval_events"][-1]["approval_status"] == "approved"
    assert detail["confirmation_events"][-1]["confirmation_text"] == "PAUSE cmp_1"
    assert detail["execution_attempts"] == []
    assert detail["rollback_notes"] == []
    assert detail["controls"]["execute"]["enabled"] is False
    assert "S6-P4" in detail["controls"]["execute"]["disabled_reason"]


def test_preflight_approve_confirm_routes_are_thin_service_wiring(monkeypatch) -> None:
    import backend.route_handlers.action as action_handler

    calls = []

    class FakeService:
        def run_preflight(self, action_id: str, current_value=None, feature_flags=None):
            calls.append(("preflight", action_id, current_value, feature_flags))
            return {"preflight": {"action_id": action_id, "result": "allowed"}}

        def approve_action(self, action_id: str, approver: str, risk_summary: str, scope=None):
            calls.append(("approve", action_id, approver, risk_summary, scope))
            return {"action": {"id": action_id, "status": "approved"}, "approval": {"approval_status": "approved"}}

        def confirm_action(self, action_id: str, confirmed_by: str, confirmation_text: str, confirmation_version: str = "v1"):
            calls.append(("confirm", action_id, confirmed_by, confirmation_text, confirmation_version))
            return {"action": {"id": action_id, "status": "confirmed"}, "confirmation": {"confirmation_version": confirmation_version}}

    monkeypatch.setattr(action_handler, "action_operations_service", lambda: FakeService())
    client = TestClient(app)

    assert client.post("/api/actions/drafts/act_1/preflight", json={"current_value": {"status": "ACTIVE"}}).status_code == 200
    assert client.post("/api/actions/drafts/act_1/approve", json={"approver": "local_user", "risk_summary": "Reviewed."}).status_code == 200
    assert client.post("/api/actions/drafts/act_1/confirm", json={"confirmed_by": "local_user", "confirmation_text": "PAUSE cmp_1"}).status_code == 200

    assert calls[0][0] == "preflight"
    assert calls[1] == ("approve", "act_1", "local_user", "Reviewed.", None)
    assert calls[2] == ("confirm", "act_1", "local_user", "PAUSE cmp_1", "v1")
