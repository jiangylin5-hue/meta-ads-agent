from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ..db import schema as s
from .base import Repository, clean_json, new_id, utc_now


class CacheRepository(Repository):
    def get_tool_result(self, cache_key: str) -> dict[str, Any] | None:
        with self.tx() as conn:
            row = conn.execute(
                select(s.mcp_tool_result_cache).where(s.mcp_tool_result_cache.c.cache_key == cache_key)
            ).mappings().first()
        return _cache_row(row)

    def save_tool_result(
        self,
        *,
        cache_key: str,
        tool_name: str,
        account_id: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        source: str,
        fetched_at: datetime,
        expires_at: datetime,
    ) -> None:
        with self.tx() as conn:
            existing = conn.execute(
                select(s.mcp_tool_result_cache.c.id).where(s.mcp_tool_result_cache.c.cache_key == cache_key)
            ).scalar_one_or_none()
            values = {
                "tool_name": tool_name,
                "account_id": account_id,
                "arguments_json": clean_json(arguments),
                "result_json": clean_json(result),
                "source": source,
                "fetched_at": fetched_at,
                "expires_at": expires_at,
            }
            if existing:
                conn.execute(
                    s.mcp_tool_result_cache.update()
                    .where(s.mcp_tool_result_cache.c.cache_key == cache_key)
                    .values(**values)
                )
            else:
                conn.execute(
                    s.mcp_tool_result_cache.insert().values(
                        id=new_id("toolcache"),
                        cache_key=cache_key,
                        **values,
                    )
                )

    def get_directory(self, key: str = "meta") -> dict[str, Any] | None:
        with self.tx() as conn:
            row = conn.execute(
                select(s.meta_account_directory_cache).where(s.meta_account_directory_cache.c.id == key)
            ).mappings().first()
        return _cache_row(row)

    def save_directory(
        self,
        *,
        accounts: list[dict[str, Any]],
        source: str,
        fetched_at: datetime,
        expires_at: datetime,
        last_error: str = "",
        key: str = "meta",
    ) -> None:
        with self.tx() as conn:
            existing = conn.execute(
                select(s.meta_account_directory_cache.c.id).where(s.meta_account_directory_cache.c.id == key)
            ).scalar_one_or_none()
            values = {
                "accounts_json": clean_json(accounts),
                "source": source,
                "fetched_at": fetched_at,
                "expires_at": expires_at,
                "last_error": last_error,
            }
            if existing:
                conn.execute(
                    s.meta_account_directory_cache.update()
                    .where(s.meta_account_directory_cache.c.id == key)
                    .values(**values)
                )
            else:
                conn.execute(
                    s.meta_account_directory_cache.insert().values(id=key, **values)
                )

    def get_account_context(self, account_id: str) -> dict[str, Any] | None:
        with self.tx() as conn:
            row = conn.execute(
                select(s.meta_account_context_cache).where(
                    s.meta_account_context_cache.c.account_id == account_id
                )
            ).mappings().first()
        return _cache_row(row)

    def save_account_context(
        self,
        *,
        account_id: str,
        context: dict[str, Any],
        source_tools: list[str],
        fetched_at: datetime,
        expires_at: datetime,
        last_error: str = "",
    ) -> None:
        now = utc_now()
        with self.tx() as conn:
            existing = conn.execute(
                select(s.meta_account_context_cache.c.id).where(
                    s.meta_account_context_cache.c.account_id == account_id
                )
            ).scalar_one_or_none()
            values = {
                "context_json": clean_json(context),
                "source_tools_json": clean_json(source_tools),
                "fetched_at": fetched_at,
                "expires_at": expires_at,
                "last_error": last_error,
                "updated_at": now,
            }
            if existing:
                conn.execute(
                    s.meta_account_context_cache.update()
                    .where(s.meta_account_context_cache.c.account_id == account_id)
                    .values(**values)
                )
            else:
                conn.execute(
                    s.meta_account_context_cache.insert().values(
                        id=new_id("accountctx"),
                        account_id=account_id,
                        created_at=now,
                        **values,
                    )
                )


def _cache_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    value = dict(row)
    value["metadata"] = value.pop("metadata_json", {}) or {}
    for key in ("fetched_at", "expires_at", "created_at", "updated_at"):
        if hasattr(value.get(key), "isoformat"):
            value[key] = value[key].isoformat()
    return value