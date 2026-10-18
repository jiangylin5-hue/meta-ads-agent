from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


READY_STREAM = "meta_action_execution:ready"
RETRY_ZSET = "meta_action_execution:retry"
DLQ_STREAM = "meta_action_execution:dlq"
FORBIDDEN_KEY_PARTS = ("token", "cookie", "raw_payload", "data_url")


@dataclass
class ActionQueueJob:
    action_id: str
    attempt_id: str
    idempotency_key: str
    account_id: str
    job_id: str = field(default_factory=lambda: f"job_{uuid4().hex}")
    client_id: str = ""
    actor_user_id: str = "local_user"
    operation: str = ""
    entity_type: str = ""
    entity_id: str = ""
    preflight_check_id: str = ""
    approval_event_id: str = ""
    confirmation_event_id: str = ""
    confirmation_version: str = "v1"
    feature_flags: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    retry_count: int = 0
    max_retries: int = 3
    requested_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        assert_safe_queue_payload(payload)
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ActionQueueJob":
        assert_safe_queue_payload(payload)
        return cls(**payload)


def assert_safe_queue_payload(payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                raise ValueError(f"Unsafe queue payload field: {key}")
            assert_safe_queue_payload(value)
        return
    if isinstance(payload, list):
        for item in payload:
            assert_safe_queue_payload(item)
        return
    if isinstance(payload, str) and "data:" in payload.strip().lower():
        raise ValueError("Unsafe queue payload value: data URL")


class InMemoryActionQueueBackend:
    def __init__(self) -> None:
        self.ready: list[dict[str, Any]] = []
        self.processed: list[dict[str, Any]] = []
        self.acked: list[str] = []
        self.retry: list[dict[str, Any]] = []
        self.dlq: list[dict[str, Any]] = []
        self._sequence = 0

    def enqueue_ready(self, job: ActionQueueJob) -> str:
        message_id = self._next_message_id()
        self.ready.append({"message_id": message_id, "job": job.to_payload()})
        return message_id

    def read_next(self) -> tuple[str, ActionQueueJob] | None:
        if not self.ready:
            return None
        item = self.ready.pop(0)
        self.processed.append(item)
        return str(item["message_id"]), ActionQueueJob.from_payload(dict(item["job"]))

    def ack(self, message_id: str) -> None:
        self.acked.append(message_id)

    def enqueue_retry(self, job: ActionQueueJob, reason: str, delay_seconds: int = 30) -> None:
        payload = job.to_payload()
        self.retry.append(
            {
                "job": payload,
                "reason": reason,
                "next_run_at_ms": int(time.time() * 1000) + delay_seconds * 1000,
            }
        )

    def requeue_due_retries(self, now_ms: int | None = None, limit: int = 100) -> int:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        due = [item for item in self.retry if int(item["next_run_at_ms"]) <= now]
        selected = due[:limit]
        for item in selected:
            self.enqueue_ready(ActionQueueJob.from_payload(dict(item["job"])))
            self.retry.remove(item)
        return len(selected)

    def claim_stale_pending(self, min_idle_ms: int = 60000, count: int = 1) -> tuple[str, ActionQueueJob] | None:
        if min_idle_ms < 0 or count < 1:
            return None
        if not self.processed:
            return None
        item = self.processed[0]
        return str(item["message_id"]), ActionQueueJob.from_payload(dict(item["job"]))

    def move_to_dlq(self, job: ActionQueueJob, reason: str) -> None:
        self.dlq.append({"job": job.to_payload(), "reason": reason})

    def _next_message_id(self) -> str:
        self._sequence += 1
        return f"memory-{self._sequence}"


class RedisActionQueueBackend:
    def __init__(
        self,
        redis_client: Any | None = None,
        redis_url: str = "redis://localhost:6379/0",
        group_name: str = "action-workers",
        consumer_name: str = "action-worker-1",
    ) -> None:
        self.group_name = group_name
        self.consumer_name = consumer_name
        if redis_client is not None:
            self.redis = redis_client
            self._ensure_group()
            return
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("Redis client is not installed; provide redis_client or install redis-py.") from exc
        self.redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._ensure_group()

    def enqueue_ready(self, job: ActionQueueJob) -> str:
        return str(self.redis.xadd(READY_STREAM, {"job": json.dumps(job.to_payload(), sort_keys=True)}))

    def read_next(self, block_ms: int | None = 1) -> tuple[str, ActionQueueJob] | None:
        rows = self.redis.xreadgroup(self.group_name, self.consumer_name, {READY_STREAM: ">"}, count=1, block=block_ms)
        if not rows:
            return None
        _stream, messages = rows[0]
        message_id, fields = messages[0]
        return str(message_id), ActionQueueJob.from_payload(json.loads(fields["job"]))

    def ack(self, message_id: str) -> None:
        self.redis.xack(READY_STREAM, self.group_name, message_id)

    def enqueue_retry(self, job: ActionQueueJob, reason: str, delay_seconds: int = 30) -> None:
        payload = json.dumps(job.to_payload(), sort_keys=True)
        self.redis.hset(f"meta_action_execution:job:{job.job_id}", mapping={"job": payload, "last_retry_reason": reason})
        self.redis.zadd(RETRY_ZSET, {job.job_id: int(time.time() * 1000) + delay_seconds * 1000})

    def requeue_due_retries(self, now_ms: int | None = None, limit: int = 100) -> int:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        job_ids = self.redis.zrangebyscore(RETRY_ZSET, 0, now, start=0, num=limit)
        requeued = 0
        for job_id in job_ids:
            job_key = f"meta_action_execution:job:{job_id}"
            payload = self.redis.hget(job_key, "job")
            if not payload:
                self.redis.zrem(RETRY_ZSET, job_id)
                continue
            self.redis.xadd(READY_STREAM, {"job": payload})
            self.redis.zrem(RETRY_ZSET, job_id)
            self.redis.delete(job_key)
            requeued += 1
        return requeued

    def claim_stale_pending(self, min_idle_ms: int = 60000, count: int = 1) -> tuple[str, ActionQueueJob] | None:
        rows = self.redis.xautoclaim(
            READY_STREAM,
            self.group_name,
            self.consumer_name,
            min_idle_time=min_idle_ms,
            start_id="0-0",
            count=count,
        )
        messages = _xautoclaim_messages(rows)
        if not messages:
            return None
        message_id, fields = messages[0]
        return str(message_id), ActionQueueJob.from_payload(json.loads(fields["job"]))

    def move_to_dlq(self, job: ActionQueueJob, reason: str) -> None:
        self.redis.xadd(DLQ_STREAM, {"job": json.dumps(job.to_payload(), sort_keys=True), "reason": reason})

    def _ensure_group(self) -> None:
        try:
            self.redis.xgroup_create(READY_STREAM, self.group_name, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise


def _xautoclaim_messages(rows: Any) -> list[Any]:
    if isinstance(rows, tuple) and len(rows) >= 2:
        messages = rows[1]
        return list(messages or [])
    if isinstance(rows, list) and len(rows) >= 2 and isinstance(rows[1], list):
        return list(rows[1] or [])
    if isinstance(rows, list):
        return rows
    return []


def action_queue_backend() -> RedisActionQueueBackend:
    return RedisActionQueueBackend()
