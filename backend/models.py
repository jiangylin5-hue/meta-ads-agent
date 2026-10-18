from typing import Any, Literal

from pydantic import BaseModel, Field


OptimizationActionDraftStatus = Literal["draft", "ignored", "done"]
ActionLifecycleStatus = Literal[
    "suggested",
    "draft_created",
    "approved",
    "confirmed",
    "executing",
    "executed",
    "failed",
    "blocked",
    "dry_run_only",
    "cancelled",
    "stale",
]
ActionPreflightResult = Literal["allowed", "blocked", "dry_run_only", "stale"]


class AgentTurnRequest(BaseModel):
    message: str
    session_id: str = ""
    account_id: str = ""
    idempotency_key: str = ""
    frontend_context: dict[str, Any] = Field(default_factory=dict)


class OptimizationActionDraftRequest(BaseModel):
    session_id: str = ""
    account_id: str
    source: Literal["dashboard_audit", "manual"] = "dashboard_audit"
    action: dict[str, Any] = Field(default_factory=dict)


class OptimizationActionDraft(BaseModel):
    id: str
    account_id: str
    source: str = "dashboard_audit"
    action: dict[str, Any] = Field(default_factory=dict)
    status: OptimizationActionDraftStatus = "draft"
    created_at: str = ""
    updated_at: str = ""
    draft_payload: dict[str, Any] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ActionLifecycleRecord(BaseModel):
    id: str
    workspace_id: str
    account_id: str
    entity_type: str
    entity_id: str
    operation: str
    status: ActionLifecycleStatus = "draft_created"
    risk_level: str = "medium"
    created_by: str = "local_user"
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    current_value: dict[str, Any] = Field(default_factory=dict)
    proposed_value: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class ActionPreflightCheck(BaseModel):
    id: str = ""
    action_id: str
    result: ActionPreflightResult
    blocked_reasons: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    feature_flags: dict[str, Any] = Field(default_factory=dict)
    stale_fields: list[str] = Field(default_factory=list)
    checked_at: str = ""


class ActionApprovalEvent(BaseModel):
    id: str = ""
    action_id: str
    approver: str = "local_user"
    approval_status: Literal["approved", "rejected", "needs_revision"] = "approved"
    risk_summary: str = ""
    scope: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class ActionConfirmationEvent(BaseModel):
    id: str = ""
    action_id: str
    confirmed_by: str = "local_user"
    confirmation_text: str
    confirmation_version: str = "v1"
    created_at: str = ""


class ActionExecutionAttempt(BaseModel):
    id: str = ""
    action_id: str
    attempt_id: str = ""
    idempotency_key: str
    provider_mode: Literal["simulator", "live", "dry_run"] = "simulator"
    result: Literal["pending", "executed", "failed", "blocked", "dry_run_only"] = "pending"
    error_class: str = ""
    trace_id: str = ""
    request_summary: dict[str, Any] = Field(default_factory=dict)
    provider_response_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    finished_at: str = ""


class ActionAuditEvent(BaseModel):
    id: str = ""
    action_id: str
    from_status: str = ""
    to_status: str = ""
    actor: str = "local_user"
    event_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class ActionRollbackNote(BaseModel):
    id: str = ""
    action_id: str
    original_values: dict[str, Any] = Field(default_factory=dict)
    recommended_manual_recovery: str
    created_by: str = "local_user"
    created_at: str = ""


class Approval(BaseModel):
    id: str = ""
    draft_id: str
    actor_user_id: str = "local_user"
    decision: Literal["approved", "rejected", "needs_revision"]
    note: str = ""
    created_at: str = ""


class ExecutionLogRecord(BaseModel):
    id: str = ""
    client_id: str = ""
    account_id: str = ""
    source_type: Literal["action_draft", "batch_draft", "rollback"] = "action_draft"
    source_id: str = ""
    actor_user_id: str = "local_user"
    status: Literal["blocked", "succeeded", "failed", "partial"] = "blocked"
    before_snapshot_id: str = ""
    after_snapshot_id: str = ""
    request_summary: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    created_at: str = ""


class RollbackRecord(BaseModel):
    id: str = ""
    execution_id: str
    actor_user_id: str = "local_user"
    status: Literal["draft", "executed", "failed"] = "draft"
    plan: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    executed_at: str = ""
