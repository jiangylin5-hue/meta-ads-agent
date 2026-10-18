from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import ProgrammingError

from backend.main import app
from backend.models import ActionAuditEvent, ActionExecutionAttempt, ActionLifecycleRecord, ActionRollbackNote, ExecutionLogRecord, OptimizationActionDraft


class FakeActionRepository:
    def __init__(self) -> None:
        self.records = {
            "act_1": ActionLifecycleRecord(
                id="act_1",
                workspace_id="workspace_1",
                account_id="act_123",
                entity_type="campaign",
                entity_id="cmp_1",
                operation="pause",
                status="draft_created",
                risk_level="high",
                created_by="local_user",
                evidence=[{"metric": "spend", "value": 100}],
                assumptions=["still active until preflight"],
                missing_data=["fresh entity status"],
                current_value={"status": "ACTIVE"},
                proposed_value={"status": "PAUSED"},
                updated_at="2026-06-28T08:00:00+00:00",
            ),
            "act_2": ActionLifecycleRecord(
                id="act_2",
                workspace_id="workspace_1",
                account_id="act_123",
                entity_type="adset",
                entity_id="adset_2",
                operation="increase_budget",
                status="approved",
                risk_level="low",
                created_by="local_user",
                evidence=[{"metric": "cpa", "value": 20}],
                assumptions=[],
                missing_data=[],
                current_value={"daily_budget": 1000},
                proposed_value={"daily_budget": 1200},
                updated_at="2026-06-28T07:00:00+00:00",
            ),
        }
        self.saved_records: list[ActionLifecycleRecord] = []
        self.attempts = [
            ActionExecutionAttempt(
                action_id="act_1",
                attempt_id="attempt_1",
                idempotency_key="act_1:pause:campaign:cmp_1:{}",
                provider_mode="simulator",
                result="executed",
            )
        ]
        self.rollback_notes: list[ActionRollbackNote] = []
        self.audit_events: list[ActionAuditEvent] = []

    def save_lifecycle_record(self, record: ActionLifecycleRecord, client_id: str = "") -> ActionLifecycleRecord:
        self.records[record.id] = record
        self.saved_records.append(record)
        return record

    def get_lifecycle_record(self, action_id: str) -> ActionLifecycleRecord | None:
        return self.records.get(action_id)

    def list_queue_records(
        self,
        account_id: str = "",
        workspace_id: str = "",
        statuses: list[str] | None = None,
        risk_levels: list[str] | None = None,
        search: str = "",
        limit: int = 100,
    ) -> list[ActionLifecycleRecord]:
        rows = list(self.records.values())
        if account_id:
            rows = [row for row in rows if row.account_id == account_id]
        if workspace_id:
            rows = [row for row in rows if row.workspace_id == workspace_id]
        if statuses:
            rows = [row for row in rows if row.status in statuses]
        if risk_levels:
            rows = [row for row in rows if row.risk_level in risk_levels]
        if search.strip():
            needle = search.strip().lower()
            rows = [
                row
                for row in rows
                if needle in row.id.lower()
                or needle in row.entity_type.lower()
                or needle in row.entity_id.lower()
                or needle in row.operation.lower()
                or needle in row.status.lower()
                or needle in row.risk_level.lower()
            ]
        return rows[:limit]

    def save_audit_event(self, event: ActionAuditEvent) -> ActionAuditEvent:
        self.audit_events.append(event)
        return event

    def list_audit_events(self, action_id: str) -> list[ActionAuditEvent]:
        return [event for event in self.audit_events if event.action_id == action_id]

    def list_execution_attempts(self, action_id: str) -> list[ActionExecutionAttempt]:
        return [attempt for attempt in self.attempts if attempt.action_id == action_id]

    def save_rollback_note(self, note: ActionRollbackNote) -> ActionRollbackNote:
        self.rollback_notes.append(note)
        return note

    def list_rollback_notes(self, action_id: str) -> list[ActionRollbackNote]:
        return [note for note in self.rollback_notes if note.action_id == action_id]


def test_lifecycle_service_allows_approved_transition_and_writes_audit() -> None:
    from backend.services.action_operations import ActionOperationsService

    repository = FakeActionRepository()
    service = ActionOperationsService(repository=repository)

    updated = service.transition_action("act_1", "approved", actor="approver_1", event_type="approved")

    assert updated.status == "approved"
    assert repository.saved_records[-1].status == "approved"
    assert repository.audit_events[-1].from_status == "draft_created"
    assert repository.audit_events[-1].to_status == "approved"
    assert repository.audit_events[-1].actor == "approver_1"


def test_lifecycle_service_rejects_illegal_transition_with_conflict() -> None:
    from backend.services.action_operations import ActionOperationsService, ActionStateConflict

    service = ActionOperationsService(repository=FakeActionRepository())

    with pytest.raises(ActionStateConflict) as exc_info:
        service.transition_action("act_1", "executing", actor="local_user", event_type="execute")

    assert "draft_created -> executing" in str(exc_info.value)


def test_queue_and_detail_view_models_keep_missing_data_and_no_execution_claim() -> None:
    from backend.services.action_operations import ActionOperationsService

    repository = FakeActionRepository()
    service = ActionOperationsService(repository=repository)
    service.transition_action("act_1", "approved", actor="approver_1", event_type="approved")

    queue = service.get_queue(account_id="act_123", workspace_id="workspace_1")
    detail = service.get_detail("act_1")

    assert queue["items"][0]["id"] == "act_1"
    assert queue["actions"][0]["id"] == "act_1"
    assert queue["items"][0]["status"] == "approved"
    assert queue["items"][0]["risk_level"] == "high"
    assert detail["action"]["evidence"] == [{"metric": "spend", "value": 100}]
    assert detail["action"]["missing_data"] == ["fresh entity status"]
    assert detail["execution"]["has_execution_log"] is False
    assert detail["execution"]["account_change_claim_allowed"] is False
    assert detail["execution_attempts"][0]["attempt_id"] == "attempt_1"
    assert detail["audit_timeline"][0]["to_status"] == "approved"


def test_queue_view_model_supports_status_risk_and_search_filters() -> None:
    from backend.services.action_operations import ActionOperationsService

    service = ActionOperationsService(repository=FakeActionRepository())

    queue = service.get_queue(
        account_id="act_123",
        workspace_id="workspace_1",
        statuses=["approved"],
        risk_levels=["low"],
        search="budget",
    )

    assert queue["total"] == 1
    assert queue["items"][0]["id"] == "act_2"
    assert queue["items"][0]["risk_level"] == "low"


def test_attempt_history_and_rollback_note_are_available_without_auto_rollback() -> None:
    from backend.services.action_operations import ActionOperationsService

    repository = FakeActionRepository()
    service = ActionOperationsService(repository=repository)

    attempts = service.get_attempts("act_1")
    rollback = service.create_rollback_note(
        "act_1",
        original_values={"status": "ACTIVE"},
        recommended_manual_recovery="Resume campaign manually after fresh read.",
        created_by="operator_1",
    )
    detail = service.get_detail("act_1")

    assert attempts["attempts"][0]["attempt_id"] == "attempt_1"
    assert rollback["rollback_note"]["recommended_manual_recovery"].startswith("Resume campaign")
    assert detail["rollback_notes"][0]["original_values"] == {"status": "ACTIVE"}
    assert repository.audit_events[-1].event_type == "rollback_note"
    assert repository.records["act_1"].status == "draft_created"


def test_action_queue_and_detail_routes_are_thin_service_wiring(monkeypatch) -> None:
    import backend.route_handlers.action as action_handler

    class FakeService:
        def get_queue(
            self,
            account_id: str = "",
            workspace_id: str = "",
            statuses=None,
            risk_levels=None,
            search: str = "",
            limit: int = 100,
        ):
            assert account_id == "act_123"
            assert workspace_id == "workspace_1"
            assert statuses == ["draft_created", "approved"]
            assert risk_levels == ["high"]
            assert search == "cmp"
            return {"items": [{"id": "act_1", "status": "approved"}], "total": 1}

        def get_detail(self, action_id: str):
            assert action_id == "act_1"
            return {"action": {"id": "act_1", "status": "approved"}, "audit_timeline": [], "execution": {"has_execution_log": False}}

    monkeypatch.setattr(action_handler, "action_operations_service", lambda: FakeService())
    client = TestClient(app)

    queue_response = client.get("/api/actions/queue?account_id=act_123&workspace_id=workspace_1&status=draft_created,approved&risk_level=high&search=cmp")
    detail_response = client.get("/api/actions/drafts/act_1")

    assert queue_response.status_code == 200
    assert queue_response.json()["items"] == [{"id": "act_1", "status": "approved"}]
    assert detail_response.status_code == 200
    assert detail_response.json()["action"]["id"] == "act_1"


def test_action_queue_reports_missing_lifecycle_tables_without_500(monkeypatch) -> None:
    import backend.route_handlers.action as action_handler

    class FakeService:
        def get_queue(self, **_kwargs):
            raise ProgrammingError(
                "select * from action_lifecycle_records",
                {},
                Exception('relation "action_lifecycle_records" does not exist'),
            )

    monkeypatch.setattr(action_handler, "action_operations_service", lambda: FakeService())
    client = TestClient(app)

    response = client.get("/api/actions/queue")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "stage06_schema_not_migrated"
    assert "alembic upgrade head" in detail["action"]


def test_execution_log_repository_filters_client_scoped_account_ids(monkeypatch) -> None:
    from backend.repositories.execution_repository import ExecutionRepository

    captured_sql: list[str] = []
    repository = ExecutionRepository()

    class FakeRows:
        def mappings(self):
            return self

        def all(self):
            return []

    class FakeConnection:
        def execute(self, query):
            captured_sql.append(str(query.compile(compile_kwargs={"literal_binds": True})))
            return FakeRows()

    class FakeTx:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(repository, "tx", lambda: FakeTx())

    repository.list_execution_logs(client_id="client_a", account_id="act_123", limit=10)

    assert "client_a:act_123" in captured_sql[0]


def test_attempt_and_rollback_note_routes_are_thin_service_wiring(monkeypatch) -> None:
    import backend.route_handlers.action as action_handler

    calls = []

    class FakeService:
        def get_attempts(self, action_id: str):
            calls.append(("attempts", action_id))
            return {"attempts": [{"attempt_id": "attempt_1"}]}

        def create_rollback_note(self, action_id: str, original_values=None, recommended_manual_recovery: str = "", created_by: str = "local_user"):
            calls.append(("rollback_note", action_id, original_values, recommended_manual_recovery, created_by))
            return {"rollback_note": {"action_id": action_id, "recommended_manual_recovery": recommended_manual_recovery}}

    monkeypatch.setattr(action_handler, "action_operations_service", lambda: FakeService())
    client = TestClient(app)

    attempts_response = client.get("/api/actions/drafts/act_1/attempts")
    rollback_response = client.post(
        "/api/actions/act_1/rollback-note",
        json={
            "original_values": {"status": "ACTIVE"},
            "recommended_manual_recovery": "Resume manually.",
            "created_by": "operator_1",
        },
    )

    assert attempts_response.status_code == 200
    assert attempts_response.json()["attempts"][0]["attempt_id"] == "attempt_1"
    assert rollback_response.status_code == 200
    assert calls[0] == ("attempts", "act_1")
    assert calls[1] == ("rollback_note", "act_1", {"status": "ACTIVE"}, "Resume manually.", "operator_1")


def test_execution_log_detail_route_returns_single_evidence_record(monkeypatch) -> None:
    import backend.route_handlers.admin as admin_handler

    class FakeStore:
        def get_execution_log(self, execution_id: str):
            assert execution_id == "exec_1"
            return ExecutionLogRecord(id="exec_1", account_id="act_123", source_type="action_draft", source_id="act_1", status="succeeded")

    monkeypatch.setattr(admin_handler, "store", lambda: FakeStore())
    client = TestClient(app)

    response = client.get("/api/execution-logs/exec_1")

    assert response.status_code == 200
    assert response.json()["execution_log"]["id"] == "exec_1"


def test_action_draft_create_route_also_creates_stage_06_lifecycle_record(monkeypatch) -> None:
    import backend.route_handlers.action as action_handler

    created_action_payloads = []

    class FakeService:
        def create_from_optimization_draft(self, draft: OptimizationActionDraft):
            created_action_payloads.append(draft.model_dump())
            return ActionLifecycleRecord(
                id="act_lifecycle_1",
                workspace_id="workspace_1",
                account_id=draft.account_id,
                entity_type="campaign",
                entity_id="cmp_1",
                operation="pause",
                status="draft_created",
                risk_level="high",
                created_by="local_user",
                evidence=[{"source": "campaign_table"}],
                missing_data=["fresh entity status"],
                current_value={"status": "ACTIVE"},
                proposed_value={"status": "PAUSED"},
            )

    def fake_create_action_draft(request):
        return OptimizationActionDraft(
            id="opt_1",
            account_id=request.account_id,
            source=request.source,
            action={**request.action, "session_id": request.session_id},
            status="draft",
            draft_payload={
                "target_level": request.action["target_level"],
                "target_id": request.action["target_id"],
                "action_type": request.action["action_type"],
                "evidence": request.action["evidence"],
                "proposed_changes": {"status": "PAUSED"},
            },
        )

    monkeypatch.setattr(action_handler, "create_action_draft", fake_create_action_draft)
    monkeypatch.setattr(action_handler, "action_operations_service", lambda: FakeService())
    client = TestClient(app)

    response = client.post(
        "/api/actions/drafts",
        json={
            "session_id": "workspace_1",
            "account_id": "act_123",
            "action": {
                "action_type": "pause",
                "target_level": "campaign",
                "target_id": "cmp_1",
                "evidence": "Spend rising with no purchases.",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["draft"]["id"] == "opt_1"
    assert payload["action"]["id"] == "act_lifecycle_1"
    assert payload["action"]["status"] == "draft_created"
    assert created_action_payloads[0]["id"] == "opt_1"


def test_action_draft_create_route_reports_missing_lifecycle_tables_without_fake_action(monkeypatch) -> None:
    import backend.route_handlers.action as action_handler
    from sqlalchemy.exc import ProgrammingError

    class FakeService:
        def create_from_optimization_draft(self, draft: OptimizationActionDraft):
            raise ProgrammingError(
                "insert into action_lifecycle_records",
                {},
                Exception('relation "action_lifecycle_records" does not exist'),
            )

    def fake_create_action_draft(request):
        return OptimizationActionDraft(
            id="opt_1",
            account_id=request.account_id,
            source=request.source,
            action={**request.action, "session_id": request.session_id},
            status="draft",
            draft_payload={"action_type": request.action["action_type"]},
        )

    monkeypatch.setattr(action_handler, "create_action_draft", fake_create_action_draft)
    monkeypatch.setattr(action_handler, "action_operations_service", lambda: FakeService())
    client = TestClient(app)

    response = client.post(
        "/api/actions/drafts",
        json={
            "session_id": "workspace_1",
            "account_id": "act_123",
            "action": {"action_type": "pause", "target_id": "cmp_1"},
        },
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["detail"]["code"] == "stage06_schema_not_migrated"
