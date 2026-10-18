from __future__ import annotations

import importlib
import importlib.util

from sqlalchemy.dialects.postgresql import JSONB

import backend.models as models
from backend.db.schema import metadata


REQUIRED_ACTION_TABLES = {
    "action_lifecycle_records",
    "action_preflight_checks",
    "action_approval_events",
    "action_confirmation_events",
    "action_execution_attempts",
    "action_audit_events",
    "action_rollback_notes",
}


def test_stage_06_action_tables_are_declared_with_required_contract_fields() -> None:
    assert REQUIRED_ACTION_TABLES.issubset(metadata.tables)

    lifecycle = metadata.tables["action_lifecycle_records"]
    for column_name in [
        "id",
        "workspace_id",
        "account_id",
        "entity_type",
        "entity_id",
        "operation",
        "status",
        "risk_level",
        "created_by",
        "evidence_json",
        "assumptions_json",
        "missing_data_json",
        "current_value_json",
        "proposed_value_json",
        "created_at",
        "updated_at",
    ]:
        assert column_name in lifecycle.c
        assert not lifecycle.c[column_name].nullable

    for json_column in [
        "evidence_json",
        "assumptions_json",
        "missing_data_json",
        "current_value_json",
        "proposed_value_json",
        "metadata_json",
    ]:
        assert isinstance(lifecycle.c[json_column].type, JSONB)


def test_stage_06_action_tables_have_foreign_keys_and_indexes_for_queue_queries() -> None:
    lifecycle = metadata.tables["action_lifecycle_records"]
    actual_fks = {
        (table.name, column.name, fk.target_fullname)
        for table in metadata.tables.values()
        for column in table.columns
        for fk in column.foreign_keys
    }

    for item in [
        ("action_lifecycle_records", "account_id", "meta_ad_accounts.id"),
        ("action_lifecycle_records", "created_by", "users.id"),
        ("action_preflight_checks", "action_id", "action_lifecycle_records.id"),
        ("action_approval_events", "action_id", "action_lifecycle_records.id"),
        ("action_confirmation_events", "action_id", "action_lifecycle_records.id"),
        ("action_execution_attempts", "action_id", "action_lifecycle_records.id"),
        ("action_audit_events", "action_id", "action_lifecycle_records.id"),
        ("action_rollback_notes", "action_id", "action_lifecycle_records.id"),
    ]:
        assert item in actual_fks

    index_names = {index.name for table in metadata.tables.values() for index in table.indexes}
    for index_name in [
        "ix_action_lifecycle_account_status_updated",
        "ix_action_lifecycle_workspace_created",
        "ix_action_execution_attempts_idempotency",
        "ix_action_audit_events_action_created",
    ]:
        assert index_name in index_names

    unique_names = {constraint.name for constraint in lifecycle.constraints if constraint.name}
    assert "uq_action_lifecycle_account_entity_operation_active" in unique_names


def test_stage_06_action_models_preserve_lifecycle_and_audit_contracts() -> None:
    for model_name in [
        "ActionLifecycleRecord",
        "ActionPreflightCheck",
        "ActionApprovalEvent",
        "ActionConfirmationEvent",
        "ActionExecutionAttempt",
        "ActionAuditEvent",
        "ActionRollbackNote",
    ]:
        assert hasattr(models, model_name), model_name

    lifecycle = models.ActionLifecycleRecord(
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
        assumptions=["campaign is still active"],
        missing_data=["fresh status read"],
        current_value={"status": "ACTIVE"},
        proposed_value={"status": "PAUSED"},
    )

    assert lifecycle.status == "draft_created"
    assert lifecycle.evidence[0]["metric"] == "spend"
    assert lifecycle.missing_data == ["fresh status read"]

    assert models.ActionPreflightCheck(action_id="act_1", result="dry_run_only").result == "dry_run_only"
    assert models.ActionApprovalEvent(action_id="act_1", approver="local_user", approval_status="approved").scope == {}
    assert models.ActionConfirmationEvent(action_id="act_1", confirmed_by="local_user", confirmation_text="PAUSE cmp_1").confirmation_version == "v1"
    assert models.ActionExecutionAttempt(action_id="act_1", idempotency_key="act_1:pause:cmp_1").provider_mode == "simulator"
    assert models.ActionAuditEvent(action_id="act_1", from_status="draft_created", to_status="approved", actor="local_user", event_type="approved").metadata == {}
    assert models.ActionRollbackNote(action_id="act_1", original_values={"status": "ACTIVE"}, recommended_manual_recovery="Resume manually.").created_by == "local_user"


def test_stage_06_action_repository_exposes_persistence_contract_methods() -> None:
    assert importlib.util.find_spec("backend.repositories.action_repository") is not None
    action_repository = importlib.import_module("backend.repositories.action_repository")
    repository = action_repository.ActionRepository()

    for method_name in [
        "save_lifecycle_record",
        "get_lifecycle_record",
        "list_queue_records",
        "save_preflight_check",
        "save_approval_event",
        "save_confirmation_event",
        "save_execution_attempt",
        "list_execution_attempts",
        "save_audit_event",
        "save_rollback_note",
        "list_rollback_notes",
    ]:
        assert callable(getattr(repository, method_name))
