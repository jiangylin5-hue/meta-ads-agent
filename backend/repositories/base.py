from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import Connection
from sqlalchemy.dialects.postgresql import insert

from ..db.connection import transaction


SENSITIVE_KEYS = {
    "access_token",
    "token",
    "cookie",
    "cookies",
    "data_url",
    "dataUrl",
    "image_data",
    "video_data",
}


DEFAULT_CLIENT_ID = "client_default"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value or "")


def clean_json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            if str(key) in SENSITIVE_KEYS:
                continue
            output[str(key)] = clean_json(item)
        return output
    if isinstance(value, list):
        return [clean_json(item) for item in value]
    return value


class Repository:
    def __init__(self, connection: Connection | None = None) -> None:
        self.connection = connection

    def tx(self):
        return transaction()

    def conn(self) -> Connection:
        if self.connection is None:
            raise RuntimeError("Repository method requires an explicit transaction connection.")
        return self.connection


def account_record_id(client_id: str, provider_account_id: str) -> str:
    resolved_client_id = client_id or DEFAULT_CLIENT_ID
    return provider_account_id if resolved_client_id == DEFAULT_CLIENT_ID else f"{resolved_client_id}:{provider_account_id}"


def provider_account_id(record_id: str) -> str:
    return record_id.split(":", 1)[1] if ":" in record_id else record_id


def ensure_account_reference(conn: Connection, account_id: str, client_id: str = "") -> tuple[str, str]:
    from ..db import schema as s

    now = utc_now()
    org_id = "default_org"
    resolved_client_id = client_id or DEFAULT_CLIENT_ID
    resolved_account_id = account_record_id(resolved_client_id, account_id) if account_id else ""
    conn.execute(
        insert(s.organizations)
        .values(id=org_id, name="Default Organization", status="active", created_at=now, updated_at=now)
        .on_conflict_do_nothing(index_elements=[s.organizations.c.id])
    )
    conn.execute(
        insert(s.clients)
        .values(
            id=resolved_client_id,
            organization_id=org_id,
            name=resolved_client_id,
            status="active",
            metadata_json={},
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=[s.clients.c.id])
    )
    if account_id:
        conn.execute(
            insert(s.meta_ad_accounts)
            .values(
                id=resolved_account_id,
                client_id=resolved_client_id,
                provider_account_id=account_id,
                name=account_id,
                currency="",
                timezone_name="",
                business_id="",
                business_name="",
                status="active",
                raw_payload_json={},
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=[s.meta_ad_accounts.c.id])
        )
    return resolved_client_id, resolved_account_id


def ensure_user_reference(conn: Connection, user_id: str, email: str = "") -> str:
    from ..db import schema as s

    now = utc_now()
    resolved_user_id = user_id or "local_user"
    resolved_email = email or f"{resolved_user_id}@local.ads-agent"
    conn.execute(
        insert(s.users)
        .values(
            id=resolved_user_id,
            email=resolved_email,
            display_name=resolved_user_id,
            status="active",
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=[s.users.c.id])
    )
    return resolved_user_id
