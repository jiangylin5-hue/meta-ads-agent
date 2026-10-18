from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..db import schema as s
from ..models import OptimizationActionDraft
from .base import Repository, clean_json, ensure_account_reference, iso, utc_now


class DraftRepository(Repository):
    def save_action_draft(self, draft: OptimizationActionDraft, session_id: str = "", client_id: str = "") -> OptimizationActionDraft:
        with self.tx() as conn:
            client_id, account_pk = ensure_account_reference(conn, draft.account_id, client_id=client_id)
            conn.execute(
                insert(s.optimization_action_drafts)
                .values(
                    id=draft.id,
                    client_id=client_id,
                    account_id=account_pk,
                    session_id=session_id or None,
                    source=draft.source,
                    status=draft.status,
                    action_json=clean_json(draft.action),
                    draft_payload_json=clean_json(draft.draft_payload),
                    safety_json=clean_json(draft.safety),
                    notes_json=clean_json(draft.notes),
                    created_at=_dt(draft.created_at),
                    updated_at=_dt(draft.updated_at),
                )
                .on_conflict_do_update(
                    index_elements=[s.optimization_action_drafts.c.id],
                    set_={
                        "status": draft.status,
                        "action_json": clean_json(draft.action),
                        "draft_payload_json": clean_json(draft.draft_payload),
                        "safety_json": clean_json(draft.safety),
                        "notes_json": clean_json(draft.notes),
                        "updated_at": _dt(draft.updated_at),
                    },
                )
            )
        return draft

    def get_action_draft(self, draft_id: str) -> OptimizationActionDraft | None:
        with self.tx() as conn:
            row = conn.execute(select(s.optimization_action_drafts).where(s.optimization_action_drafts.c.id == draft_id)).mappings().first()
        return _action_draft(row) if row else None

    def list_action_drafts(self, account_id: str = "", session_id: str = "") -> list[OptimizationActionDraft]:
        query = select(s.optimization_action_drafts)
        if account_id:
            query = query.where(s.optimization_action_drafts.c.account_id == account_id)
        if session_id:
            query = query.where(s.optimization_action_drafts.c.session_id == session_id)
        query = query.order_by(s.optimization_action_drafts.c.created_at.desc())
        with self.tx() as conn:
            rows = conn.execute(query).mappings().all()
        return [_action_draft(row) for row in rows]


def _action_draft(row: Any) -> OptimizationActionDraft:
    return OptimizationActionDraft(
        id=str(row["id"]),
        account_id=str(row["account_id"]).split(":", 1)[-1],
        source=str(row["source"]),
        action=dict(row["action_json"] or {}),
        status=row["status"],
        created_at=iso(row["created_at"]),
        updated_at=iso(row["updated_at"]),
        draft_payload=dict(row["draft_payload_json"] or {}),
        safety=dict(row["safety_json"] or {}),
        notes=list(row["notes_json"] or []),
    )


def _dt(value: str):
    from datetime import datetime

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return utc_now()