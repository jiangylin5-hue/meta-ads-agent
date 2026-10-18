from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError

from ..config import agent_turn_timeout_seconds
from ..repositories.turn_repository import TurnRepository


TURN_LEASE_BUFFER_SECONDS = 120


class TurnConflictError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TurnControlService:
    def __init__(self, repository: TurnRepository | None = None, lease_seconds: int | None = None) -> None:
        self.repository = repository or TurnRepository()
        self.lease_seconds = max(
            30,
            int(lease_seconds) if lease_seconds is not None else default_turn_lease_seconds(),
        )

    def begin(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[str, dict[str, Any] | None]:
        key = idempotency_key.strip()[:128]
        existing = self.repository.get_by_idempotency(session_id, key) if key else None
        if existing:
            if str(existing.get("request_hash") or "") != request_hash:
                raise TurnConflictError("idempotency_key_reused", "The idempotency key was already used for a different request.")
            if existing.get("status") == "completed" and isinstance(existing.get("response"), dict) and existing["response"]:
                return str(existing["id"]), dict(existing["response"])
            turn = existing
            if turn.get("status") == "in_progress" and _lock_active(self.repository.get_lock(session_id), str(turn.get("id") or "")):
                raise TurnConflictError("turn_already_in_progress", "This turn is already being processed.")
            if turn.get("status") != "in_progress":
                turn = self.repository.mark_in_progress(str(turn["id"]), request_hash) or turn
        else:
            try:
                turn = self.repository.create(session_id=session_id, idempotency_key=key, request_hash=request_hash)
            except IntegrityError:
                existing = self.repository.get_by_idempotency(session_id, key) if key else None
                if existing and str(existing.get("request_hash") or "") == request_hash and existing.get("status") == "completed":
                    return str(existing["id"]), dict(existing.get("response") or {})
                raise TurnConflictError("turn_already_in_progress", "A turn is already being processed for this session.")
        turn_id = str(turn.get("id") or "")
        if not turn_id:
            raise TurnConflictError("turn_start_failed", "The turn could not be created.")
        if not self.repository.acquire_lock(session_id=session_id, turn_id=turn_id, lease_seconds=self.lease_seconds):
            self.repository.fail(turn_id, "Another turn is active for this session.")
            raise TurnConflictError("turn_already_in_progress", "Another turn is active for this session.")
        return turn_id, None

    def complete(self, turn_id: str, response: dict[str, Any]) -> None:
        self.repository.complete(turn_id, response)

    def fail(self, turn_id: str, error: str) -> None:
        self.repository.fail(turn_id, error)

    def release(self, *, session_id: str, turn_id: str) -> None:
        self.repository.release_lock(session_id=session_id, turn_id=turn_id)

    def force_release_session(self, session_id: str) -> None:
        self.repository.force_release_session(session_id)


def default_turn_lease_seconds() -> int:
    return max(30, agent_turn_timeout_seconds() + TURN_LEASE_BUFFER_SECONDS)


def _lock_active(lock: dict[str, Any] | None, turn_id: str) -> bool:
    if not lock or str(lock.get("turn_id") or "") != turn_id:
        return False
    expires_at = lock.get("expires_at")
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False
    if not hasattr(expires_at, "tzinfo"):
        return False
    if not expires_at.tzinfo:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > datetime.now(timezone.utc)


def request_fingerprint(*, session_id: str, account_id: str, message: str) -> str:
    payload = json.dumps(
        {"session_id": session_id, "account_id": account_id, "message": message},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "TURN_LEASE_BUFFER_SECONDS",
    "default_turn_lease_seconds",
    "TurnConflictError",
    "TurnControlService",
    "request_fingerprint",
]