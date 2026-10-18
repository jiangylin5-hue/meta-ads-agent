from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from backend.services.turn_control import (
    TURN_LEASE_BUFFER_SECONDS,
    TurnConflictError,
    TurnControlService,
    default_turn_lease_seconds,
    request_fingerprint,
)


class FakeTurnRepository:
    def __init__(self) -> None:
        self.turns: dict[str, dict[str, Any]] = {}
        self.locks: dict[str, dict[str, Any]] = {}
        self.next_id = 1

    def get(self, turn_id: str) -> dict[str, Any] | None:
        return self.turns.get(turn_id)

    def get_by_idempotency(self, session_id: str, idempotency_key: str) -> dict[str, Any] | None:
        for turn in self.turns.values():
            if turn["session_id"] == session_id and turn.get("idempotency_key") == idempotency_key:
                return turn
        return None

    def create(self, *, session_id: str, idempotency_key: str, request_hash: str) -> dict[str, Any]:
        turn_id = f"turn_{self.next_id}"
        self.next_id += 1
        turn = {
            "id": turn_id,
            "session_id": session_id,
            "idempotency_key": idempotency_key or None,
            "request_hash": request_hash,
            "status": "in_progress",
            "response": {},
        }
        self.turns[turn_id] = turn
        return turn

    def mark_in_progress(self, turn_id: str, request_hash: str) -> dict[str, Any] | None:
        turn = self.turns.get(turn_id)
        if turn:
            turn.update(status="in_progress", request_hash=request_hash, response={})
        return turn

    def get_lock(self, session_id: str) -> dict[str, Any] | None:
        return self.locks.get(session_id)

    def acquire_lock(self, *, session_id: str, turn_id: str, lease_seconds: int) -> bool:
        now = datetime.now(timezone.utc)
        lock = self.locks.get(session_id)
        if lock and lock["turn_id"] != turn_id and lock["expires_at"] > now:
            return False
        self.locks[session_id] = {
            "turn_id": turn_id,
            "expires_at": now + timedelta(seconds=lease_seconds),
        }
        return True

    def release_lock(self, *, session_id: str, turn_id: str) -> None:
        lock = self.locks.get(session_id)
        if lock and lock["turn_id"] == turn_id:
            self.locks.pop(session_id, None)

    def complete(self, turn_id: str, response: dict[str, Any]) -> None:
        self.turns[turn_id]["status"] = "completed"
        self.turns[turn_id]["response"] = dict(response)

    def fail(self, turn_id: str, error: str) -> None:
        self.turns[turn_id]["status"] = "failed"
        self.turns[turn_id]["error"] = error


def _hash(message: str = "hello") -> str:
    return request_fingerprint(session_id="s1", account_id="act_1", message=message)


def test_completed_idempotent_turn_replays_stored_response() -> None:
    repository = FakeTurnRepository()
    service = TurnControlService(repository=repository)
    turn_id, replay = service.begin(session_id="s1", idempotency_key="key_1", request_hash=_hash())
    assert replay is None
    service.complete(turn_id, {"reply": "done"})
    service.release(session_id="s1", turn_id=turn_id)

    replay_turn_id, replayed = service.begin(session_id="s1", idempotency_key="key_1", request_hash=_hash())

    assert replay_turn_id == turn_id
    assert replayed == {"reply": "done"}
    assert "s1" not in repository.locks


def test_in_progress_turn_rejects_duplicate_concurrent_request() -> None:
    service = TurnControlService(repository=FakeTurnRepository())
    service.begin(session_id="s1", idempotency_key="key_1", request_hash=_hash())

    with pytest.raises(TurnConflictError) as exc_info:
        service.begin(session_id="s1", idempotency_key="key_1", request_hash=_hash())

    assert exc_info.value.code == "turn_already_in_progress"


def test_idempotency_key_cannot_be_reused_for_different_payload() -> None:
    service = TurnControlService(repository=FakeTurnRepository())
    service.begin(session_id="s1", idempotency_key="key_1", request_hash=_hash("first"))

    with pytest.raises(TurnConflictError) as exc_info:
        service.begin(session_id="s1", idempotency_key="key_1", request_hash=_hash("second"))

    assert exc_info.value.code == "idempotency_key_reused"


def test_expired_lease_allows_same_turn_retry() -> None:
    repository = FakeTurnRepository()
    service = TurnControlService(repository=repository, lease_seconds=30)
    turn_id, _ = service.begin(session_id="s1", idempotency_key="key_1", request_hash=_hash())
    repository.locks["s1"]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    retried_id, replay = service.begin(session_id="s1", idempotency_key="key_1", request_hash=_hash())

    assert retried_id == turn_id
    assert replay is None
    assert repository.turns[turn_id]["status"] == "in_progress"


def test_request_fingerprint_is_stable_and_payload_sensitive() -> None:
    assert _hash("same") == _hash("same")
    assert _hash("same") != _hash("different")

def test_default_lease_tracks_agent_turn_timeout(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_TURN_TIMEOUT_SECONDS", "300")
    expected = 300 + TURN_LEASE_BUFFER_SECONDS

    assert default_turn_lease_seconds() == expected
    assert TurnControlService(repository=FakeTurnRepository()).lease_seconds == expected
