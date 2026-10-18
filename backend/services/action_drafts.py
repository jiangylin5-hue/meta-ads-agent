from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..models import OptimizationActionDraft, OptimizationActionDraftRequest
from ..repositories.draft_repository import DraftRepository


def create_action_draft(request: OptimizationActionDraftRequest) -> OptimizationActionDraft:
    now = _utc_now()
    draft_id = f"opt_{uuid4().hex[:12]}"
    draft = OptimizationActionDraft(
        id=draft_id,
        account_id=request.account_id,
        source=request.source,
        action={**request.action, "session_id": request.session_id or request.action.get("session_id", "")},
        status="draft",
        created_at=now,
        updated_at=now,
        draft_payload=_build_draft_payload(request.account_id, request.action),
        safety={
            "mode": "approval_required_change_draft",
            "live_publish_enabled": False,
            "requires_human_approval": True,
        },
    )
    return DraftRepository().save_action_draft(draft, session_id=request.session_id)


def get_action_draft(draft_id: str) -> OptimizationActionDraft | None:
    return DraftRepository().get_action_draft(draft_id)


def list_action_drafts(account_id: str = "", session_id: str = "") -> list[OptimizationActionDraft]:
    return DraftRepository().list_action_drafts(account_id=account_id, session_id=session_id)


def update_action_draft(draft_id: str, status: str, note: str = "") -> OptimizationActionDraft:
    draft = get_action_draft(draft_id)
    if not draft:
        raise RuntimeError("Optimization action draft not found.")
    if status not in {"ignored", "done"}:
        raise RuntimeError("Unsupported optimization action draft status.")
    notes = [*draft.notes]
    if note.strip():
        notes.append(note.strip())
    updated = draft.model_copy(update={"status": status, "updated_at": _utc_now(), "notes": notes})
    return DraftRepository().save_action_draft(updated, session_id=str(updated.action.get("session_id") or ""))


def _build_draft_payload(account_id: str, action: dict[str, Any]) -> dict[str, Any]:
    proposed_changes = action.get("draft_payload") or _default_proposed_changes(str(action.get("action_type") or ""))
    return {
        "mode": "approval_required_optimization_action",
        "platform": "meta",
        "account_id": account_id,
        "action_id": action.get("id", ""),
        "action_type": action.get("action_type", ""),
        "target_level": action.get("target_level", ""),
        "target_id": action.get("target_id", ""),
        "target_name": action.get("target_name", ""),
        "evidence": action.get("evidence", ""),
        "evidence_strength": action.get("evidence_strength", ""),
        "confidence": action.get("confidence", ""),
        "judgment": action.get("judgment") or action.get("rationale", ""),
        "recommendation": action.get("recommendation", ""),
        "expected_impact": action.get("expected_impact", ""),
        "owner_decision_needed": action.get("owner_decision_needed", ""),
        "rollback_condition": action.get("rollback_condition", ""),
        "proposed_changes": proposed_changes,
        "requires_human_approval": True,
        "live_publish_enabled": False,
    }


def _default_proposed_changes(action_type: str) -> dict[str, Any]:
    defaults: dict[str, dict[str, Any]] = {
        "reduce_budget": {"budget_change": {"operation": "reduce_by_percent", "percent": 30}},
        "scale_budget": {"budget_change": {"operation": "increase_by_percent", "percent": 20}},
        "pause_ad": {"status": "PAUSED"},
        "refresh_creative": {"creative_test": {"new_variants": 2, "keep_original_as_control": True}},
        "duplicate_test": {"experiment": {"operation": "duplicate_for_test", "variants": 2}},
        "inspect_tracking": {
            "tracking_checklist": [
                "verify_pixel_event_match_quality",
                "verify_purchase_or_lead_event_mapping",
                "compare_platform_conversions_with_backend_orders",
            ]
        },
    }
    return defaults.get(action_type, {"manual_review": {"reason": "No deterministic Meta mutation can be inferred yet."}})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
