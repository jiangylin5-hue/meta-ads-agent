from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.models import (
    ActionApprovalEvent,
    ActionConfirmationEvent,
    ActionExecutionAttempt,
    ActionLifecycleRecord,
    ActionPreflightCheck,
    ExecutionLogRecord,
)


class QueueRepo:
    def __init__(self, *, confirmation: bool = True, status: str = "confirmed", operation: str = "pause") -> None:
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
        )
        self.preflights = [ActionPreflightCheck(id="preflight_1", action_id="act_1", result="allowed")]
        self.approvals = [ActionApprovalEvent(id="approval_1", action_id="act_1", risk_summary="Reviewed.")]
        self.confirmations = (
            [ActionConfirmationEvent(id="confirmation_1", action_id="act_1", confirmation_text="EXECUTE APPROVED ACTION")]
            if confirmation
            else []
        )
        self.attempts: dict[str, ActionExecutionAttempt] = {}
        self.saved_attempts: list[ActionExecutionAttempt] = []
        self.saved_records: list[ActionLifecycleRecord] = []
        self.audit_events = []
        self.read_count = 0

    def get_lifecycle_record(self, action_id: str):
        self.read_count += 1
        return self.record if action_id == self.record.id else None

    def save_lifecycle_record(self, record: ActionLifecycleRecord, client_id: str = ""):
        self.record = record
        self.saved_records.append(record)
        return record

    def list_preflight_checks(self, action_id: str):
        return self.preflights

    def list_approval_events(self, action_id: str):
        return self.approvals

    def list_confirmation_events(self, action_id: str):
        return self.confirmations

    def get_execution_attempt_by_idempotency_key(self, idempotency_key: str):
        return self.attempts.get(idempotency_key)

    def save_execution_attempt(self, attempt: ActionExecutionAttempt):
        self.attempts[attempt.idempotency_key] = attempt
        self.saved_attempts.append(attempt)
        return attempt

    def save_audit_event(self, event):
        self.audit_events.append(event)
        return event


class QueueWriteService:
    def __init__(self) -> None:
        self.calls = []

    def execute_stage06_action(self, action, actor_user_id, provider_result, client_id: str = ""):
        self.calls.append((action.id, actor_user_id, client_id, provider_result))
        return ExecutionLogRecord(
            id="exec_1",
            client_id=client_id,
            account_id=action.account_id,
            source_type="action_draft",
            source_id=action.id,
            actor_user_id=actor_user_id,
            status="succeeded",
            request_summary={"action_id": action.id, "operation": action.operation},
            result=provider_result,
        )


def test_enqueue_rejects_missing_final_confirmation() -> None:
    from backend.services.action_operations import ActionStateConflict
    from backend.services.action_queue import ActionQueueService
    from backend.services.action_queue_backend import InMemoryActionQueueBackend

    service = ActionQueueService(repository=QueueRepo(confirmation=False), queue_backend=InMemoryActionQueueBackend())

    with pytest.raises(ActionStateConflict) as exc_info:
        service.enqueue_execution("act_1", actor_user_id="operator_1", client_id="client_1")

    assert "Final confirmation" in str(exc_info.value)


def test_enqueue_writes_pending_attempt_and_safe_redis_job() -> None:
    from backend.services.action_queue import ActionQueueService
    from backend.services.action_queue_backend import InMemoryActionQueueBackend

    repository = QueueRepo()
    backend = InMemoryActionQueueBackend()
    result = ActionQueueService(repository=repository, queue_backend=backend).enqueue_execution(
        "act_1",
        actor_user_id="operator_1",
        client_id="client_1",
        feature_flags={"allow_live_budget_write": False},
        trace_id="trace_1",
    )

    assert result["queued"] is True
    assert result["job"]["action_id"] == "act_1"
    assert result["attempt"]["result"] == "pending"
    assert repository.saved_attempts[-1].request_summary["queue_status"] == "enqueued"
    payload_text = str(backend.ready[0]["job"]).lower()
    assert "token" not in payload_text
    assert "cookie" not in payload_text
    assert "raw_payload" not in payload_text
    assert "data:" not in payload_text


def test_enqueue_hashes_idempotency_metadata_when_proposed_value_contains_data_url() -> None:
    from backend.services.action_queue import ActionQueueService
    from backend.services.action_queue_backend import InMemoryActionQueueBackend

    repository = QueueRepo()
    repository.record = repository.record.model_copy(update={"proposed_value": {"preview": "data:image/png;base64,abc"}})
    backend = InMemoryActionQueueBackend()

    result = ActionQueueService(repository=repository, queue_backend=backend).enqueue_execution("act_1")

    assert result["job"]["idempotency_key"].startswith("sha256:")
    assert "data:" not in str(result).lower()
    assert "data:" not in str(backend.ready[0]["job"]).lower()


def test_worker_re_reads_db_executes_and_acks_after_execution_log() -> None:
    from backend.services.action_execution import ActionExecutionService, ProviderSimulator
    from backend.services.action_execution_worker import ActionExecutionWorker
    from backend.services.action_queue import ActionQueueService
    from backend.services.action_queue_backend import InMemoryActionQueueBackend

    repository = QueueRepo()
    writer = QueueWriteService()
    backend = InMemoryActionQueueBackend()
    ActionQueueService(repository=repository, queue_backend=backend).enqueue_execution("act_1", actor_user_id="operator_1", client_id="client_1")

    worker = ActionExecutionWorker(
        queue_backend=backend,
        execution_service=ActionExecutionService(repository=repository, write_service=writer, provider=ProviderSimulator()),
    )
    result = worker.process_next()

    assert result["acknowledged"] is True
    assert result["execution"]["execution_log"]["id"] == "exec_1"
    assert writer.calls == [("act_1", "operator_1", "client_1", result["execution"]["execution_log"]["result"])]
    assert backend.acked == [backend.processed[0]["message_id"]]
    assert repository.read_count >= 2


def test_worker_does_not_ack_when_execution_has_no_durable_evidence() -> None:
    from backend.services.action_execution_worker import ActionExecutionWorker
    from backend.services.action_queue import ActionQueueService
    from backend.services.action_queue_backend import InMemoryActionQueueBackend

    class NoEvidenceExecutionService:
        def execute_confirmed_action(self, **_kwargs):
            return {"action": {"id": "act_1", "status": "executed"}, "attempt": {"result": "executed"}}

    backend = InMemoryActionQueueBackend()
    ActionQueueService(repository=QueueRepo(), queue_backend=backend).enqueue_execution("act_1")
    result = ActionExecutionWorker(queue_backend=backend, execution_service=NoEvidenceExecutionService()).process_next()

    assert result["acknowledged"] is False
    assert backend.acked == []
    assert backend.dlq[-1]["reason"] == "missing durable execution evidence"


def test_backend_retry_and_dlq_keep_job_payload_safe() -> None:
    from backend.services.action_queue_backend import ActionQueueJob, InMemoryActionQueueBackend

    backend = InMemoryActionQueueBackend()
    job = ActionQueueJob(action_id="act_1", attempt_id="attempt_1", idempotency_key="idem_1", account_id="act_123")

    backend.enqueue_retry(job, reason="rate limit", delay_seconds=30)
    backend.move_to_dlq(job, reason="permanent block")

    assert backend.retry[0]["reason"] == "rate limit"
    assert backend.dlq[0]["reason"] == "permanent block"
    assert "token" not in str(backend.retry[0]["job"]).lower()


def test_in_memory_retry_requeue_and_stale_claim() -> None:
    from backend.services.action_queue_backend import ActionQueueJob, InMemoryActionQueueBackend

    backend = InMemoryActionQueueBackend()
    job = ActionQueueJob(action_id="act_1", attempt_id="attempt_1", idempotency_key="idem_1", account_id="act_123")

    backend.enqueue_retry(job, reason="temporary", delay_seconds=0)
    assert backend.requeue_due_retries() == 1
    message_id, ready_job = backend.read_next()

    assert ready_job.job_id == job.job_id
    assert backend.claim_stale_pending(min_idle_ms=0) == (message_id, ready_job)


def test_real_redis_stream_ack_retry_requeue_and_pending_claim() -> None:
    if os.getenv("RUN_REAL_REDIS_TESTS") != "1":
        pytest.skip("Set RUN_REAL_REDIS_TESTS=1 and REDIS_URL for real Redis/Memurai acceptance.")
    redis = pytest.importorskip("redis")
    from backend.services.action_queue_backend import ActionQueueJob, RedisActionQueueBackend

    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6380/0")
    client = redis.Redis.from_url(redis_url, decode_responses=True)
    assert client.ping() is True
    client.flushdb()

    group_name = f"test-group-{uuid4().hex}"
    backend = RedisActionQueueBackend(redis_client=client, group_name=group_name, consumer_name="consumer-a")
    job = ActionQueueJob(action_id="act_1", attempt_id="attempt_1", idempotency_key="idem_1", account_id="act_123")

    backend.enqueue_ready(job)
    message_id, ready_job = backend.read_next()
    assert ready_job.job_id == job.job_id
    backend.ack(message_id)
    pending_summary = client.xpending("meta_action_execution:ready", group_name)
    assert pending_summary["pending"] == 0

    retry_job = ActionQueueJob(action_id="act_2", attempt_id="attempt_2", idempotency_key="idem_2", account_id="act_123")
    backend.enqueue_retry(retry_job, reason="rate limit", delay_seconds=0)
    assert backend.requeue_due_retries() == 1
    retry_message_id, requeued_job = backend.read_next()
    assert requeued_job.job_id == retry_job.job_id
    backend.ack(retry_message_id)

    stale_job = ActionQueueJob(action_id="act_3", attempt_id="attempt_3", idempotency_key="idem_3", account_id="act_123")
    backend.enqueue_ready(stale_job)
    original_message_id, original_job = backend.read_next()
    assert original_job.job_id == stale_job.job_id
    recovery_backend = RedisActionQueueBackend(redis_client=client, group_name=group_name, consumer_name="consumer-b")
    claimed = recovery_backend.claim_stale_pending(min_idle_ms=0)
    assert claimed is not None
    claimed_message_id, claimed_job = claimed
    assert claimed_message_id == original_message_id
    assert claimed_job.job_id == stale_job.job_id
    recovery_backend.ack(claimed_message_id)


def test_execute_route_is_disabled_in_draft_only_demo() -> None:
    client = TestClient(app)
    response = client.post("/api/actions/drafts/act_1/execute", json={})
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "execution_disabled_in_demo"
