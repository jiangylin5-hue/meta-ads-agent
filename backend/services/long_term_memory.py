from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from ..repositories.memory_repository import MemoryRepository
from ..agent.context import MEMORY_TOKEN_BUDGET, estimate_tokens


MEMORY_KINDS = {"preference", "habit", "decision", "account_profile", "outcome"}
MEMORY_SCOPES = {"user", "account"}
DEFAULT_USER_ID = "local_user"
_MAX_MEMORIES = 8
_MEMORY_RECALL_POOL = 100
_MAX_PER_KIND = 3
_KIND_PRIORITY = {
    "preference": 1.0,
    "account_profile": 0.85,
    "decision": 0.8,
    "habit": 0.65,
    "outcome": 0.5,
}
_HALF_LIFE_DAYS = {
    "preference": 365,
    "habit": 180,
    "account_profile": 60,
    "decision": 45,
    "outcome": 14,
}
_WORD_RE = re.compile(r"[a-z0-9_]{2,}")
_CJK_RE = re.compile(r"[\u3400-\u9fff]+")
_CJK_STOP_BIGRAMS = {"这个", "那个", "什么", "怎么", "是否", "一个", "帮我", "当前"}


class MemoryValidationError(ValueError):
    pass


class LongTermMemoryService:
    def __init__(self, repository: MemoryRepository | None = None) -> None:
        self.repository = repository or MemoryRepository()

    def context_for(
        self,
        *,
        user_id: str,
        account_id: str = "",
        query: str = "",
        task_state: dict[str, Any] | None = None,
        limit: int = _MAX_MEMORIES,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.repository.list_memories(
            user_id=user_id,
            account_id=account_id,
            limit=_MEMORY_RECALL_POOL,
        )
        current_time = _aware_time(now or datetime.now(timezone.utc))
        query_tokens = _memory_tokens(" ".join([query, _task_query_text(task_state)]))
        ranked: list[tuple[float, str, dict[str, Any]]] = []
        for row in rows:
            if str(row.get("status") or "active") != "active":
                continue
            score = _memory_score(row, query_tokens, current_time)
            ranked.append((score, str(row.get("updated_at") or ""), row))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)

        output: list[dict[str, Any]] = []
        kind_counts: dict[str, int] = {}
        safe_limit = max(1, min(limit, _MAX_MEMORIES))
        for _score, _updated_at, row in ranked:
            if len(output) >= safe_limit:
                break
            kind = str(row.get("kind") or "unknown")
            if kind_counts.get(kind, 0) >= _MAX_PER_KIND:
                continue
            candidate = [*output, row]
            if estimate_tokens(candidate) > MEMORY_TOKEN_BUDGET:
                continue
            output.append(row)
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        return output

    def remember_many(
        self,
        writes: list[dict[str, Any]],
        *,
        user_id: str,
        account_id: str,
        session_id: str,
        user_message_id: str,
    ) -> list[dict[str, Any]]:
        saved: list[dict[str, Any]] = []
        for item in writes[:8]:
            kind = str(item.get("kind") or "").strip()
            scope = str(item.get("scope") or "").strip()
            content = str(item.get("content") or "").strip()
            if kind not in MEMORY_KINDS or scope not in MEMORY_SCOPES or not content:
                continue
            scope_id = user_id if scope == "user" else account_id
            if scope == "account" and not account_id:
                continue
            confidence = _clamp_confidence(item.get("confidence"), 0.5)
            source_quote = str(item.get("source_quote") or "").strip()[:2000]
            source_role = str(item.get("source_role") or "").strip()
            explicit = bool(
                source_role == "user"
                and source_quote
                and source_quote in str(item.get("source_text") or "")
            )
            status = "active" if explicit and confidence >= 0.7 else "candidate"
            record = self.repository.remember(
                user_id=user_id,
                scope_type=scope,
                scope_id=scope_id,
                account_id=account_id if scope == "account" else "",
                kind=kind,
                content=content[:3000],
                confidence=confidence,
                status=status,
                source_session_id=session_id,
                source_message_id=user_message_id,
                source_quote=source_quote,
                supersedes_id=str(item.get("supersedes_memory_id") or ""),
                metadata={
                    **dict(item.get("metadata") or {}),
                    "source": "agent_turn",
                    "source_role": source_role,
                },
            )
            saved.append(record)
        return saved

    def list_visible(self, *, user_id: str, account_id: str = "") -> list[dict[str, Any]]:
        return self.repository.list_memories(user_id=user_id, account_id=account_id, include_candidates=True)

    def delete(self, *, user_id: str, memory_id: str) -> bool:
        return self.repository.delete(user_id=user_id, memory_id=memory_id)

    def confirm_candidate(self, *, user_id: str, memory_id: str) -> bool:
        return self.repository.update_candidate_status(
            user_id=user_id,
            memory_id=memory_id,
            status="active",
        )

    def reject_candidate(self, *, user_id: str, memory_id: str) -> bool:
        return self.repository.update_candidate_status(
            user_id=user_id,
            memory_id=memory_id,
            status="rejected",
        )


def _task_query_text(task_state: dict[str, Any] | None) -> str:
    task = dict(task_state or {})
    progress = task.get("progress") if isinstance(task.get("progress"), dict) else {}
    return " ".join(
        str(value)
        for value in (
            task.get("goal"),
            progress.get("next_step"),
            progress.get("blocker_summary"),
        )
        if value not in (None, "")
    )


def _memory_tokens(text: str) -> set[str]:
    normalized = str(text or "").casefold()
    tokens = set(_WORD_RE.findall(normalized))
    for segment in _CJK_RE.findall(normalized):
        if len(segment) == 1:
            tokens.add(segment)
            continue
        tokens.update(
            segment[index:index + 2]
            for index in range(len(segment) - 1)
            if segment[index:index + 2] not in _CJK_STOP_BIGRAMS
        )
    return tokens


def _memory_score(row: dict[str, Any], query_tokens: set[str], now: datetime) -> float:
    kind = str(row.get("kind") or "")
    memory_tokens = _memory_tokens(f"{kind} {row.get('content') or ''}")
    relevance = 0.0
    if query_tokens:
        relevance = min(1.0, len(query_tokens & memory_tokens) / min(len(query_tokens), 12))
    confidence = _clamp_confidence(row.get("confidence"), 0.5)
    priority = _KIND_PRIORITY.get(kind, 0.4)
    recency = _recency_score(row.get("updated_at"), now=now, kind=kind)
    return 0.55 * relevance + 0.15 * confidence + 0.15 * priority + 0.15 * recency


def _recency_score(value: Any, *, now: datetime, kind: str) -> float:
    updated_at = _memory_datetime(value)
    if updated_at is None:
        return 0.0
    age_days = max(0.0, (now - updated_at).total_seconds() / 86400)
    half_life = max(1, int(_HALF_LIFE_DAYS.get(kind, 30)))
    return math.pow(0.5, age_days / half_life)


def _memory_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _aware_time(value)
    try:
        return _aware_time(datetime.fromisoformat(str(value or "").replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def _aware_time(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def validate_memory_tool_args(arguments: dict[str, Any], *, account_id: str) -> tuple[dict[str, Any] | None, str]:
    kind = str(arguments.get("kind") or "").strip()
    scope = str(arguments.get("scope") or "").strip()
    content = str(arguments.get("content") or "").strip()
    if kind not in MEMORY_KINDS:
        return None, f"kind must be one of {sorted(MEMORY_KINDS)}"
    if scope not in MEMORY_SCOPES:
        return None, f"scope must be one of {sorted(MEMORY_SCOPES)}"
    if not content:
        return None, "content is required"
    if scope == "account" and not account_id:
        return None, "account-scoped Memory requires a selected account"
    payload = {
        "kind": kind,
        "scope": scope,
        "content": content[:3000],
        "confidence": _clamp_confidence(arguments.get("confidence"), 0.8 if scope == "user" else 0.7),
        "source_quote": str(arguments.get("source_quote") or "").strip()[:2000],
        "supersedes_memory_id": str(arguments.get("supersedes_memory_id") or "").strip(),
        "source_role": "user",
        "metadata": {"source": "model_tool"},
    }
    return payload, ""


def _clamp_confidence(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


__all__ = [
    "DEFAULT_USER_ID",
    "LongTermMemoryService",
    "MEMORY_KINDS",
    "MEMORY_SCOPES",
    "MemoryValidationError",
    "validate_memory_tool_args",
]