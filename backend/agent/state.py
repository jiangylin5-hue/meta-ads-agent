from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    message: str
    account_id: str = ""
    step: int = 0
    max_steps: int = 16
    trace: list[dict[str, Any]] = field(default_factory=list)
    drafts: list[dict[str, Any]] = field(default_factory=list)
    loaded_skills: list[dict[str, Any]] = field(default_factory=list)
    loaded_references: list[dict[str, Any]] = field(default_factory=list)
    read_tools: list[str] = field(default_factory=list)
    live_read_tools: list[str] = field(default_factory=list)
    live_read_evidence: list[dict[str, Any]] = field(default_factory=list)
    staged_actions: list[dict[str, Any]] = field(default_factory=list)
    direct_drafts: list[dict[str, Any]] = field(default_factory=list)
    submitted_result: dict[str, Any] | None = None
    stopped_reason: str = ""
    tool_ledger: list[dict[str, Any]] = field(default_factory=list)
    memory_writes: list[dict[str, Any]] = field(default_factory=list)
    task_update: dict[str, Any] = field(default_factory=dict)
    context_manifest: dict[str, Any] = field(default_factory=dict)
    summary_update: dict[str, Any] | None = None
    source_messages: list[dict[str, Any]] = field(default_factory=list)
    user_message_id: str = ""
    session_id: str = ""
    task_id: str = ""