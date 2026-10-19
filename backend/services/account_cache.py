from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ..repositories.cache_repository import CacheRepository


ACCOUNT_DIRECTORY_TTL_SECONDS = 7 * 24 * 3600
ACCOUNT_CONTEXT_TTL_SECONDS = 3600
TOOL_TTL_SECONDS = {
    "ads_get_ad_accounts": 3600,
    "ads_get_ad_entities": 3600,
    "ads_insights_performance_trend": 1800,
    "ads_insights_anomaly_signal": 1800,
    "ads_insights_advertiser_context": 1800,
    "ads_get_creatives": 86400,
}
DEFAULT_TOOL_TTL_SECONDS = 900
MEDIA_TOOL_NAMES = {"get_ad_image", "get_ad_video", "get_image_by_hash", "ads_get_ad_images", "ads_get_ad_videos", "ads_get_ad_preview_screenshot"}


class MCPToolResultCache:
    def __init__(self, repository: CacheRepository | None = None) -> None:
        self.repository = repository or CacheRepository()

    def cache_key(self, tool_name: str, arguments: dict[str, Any], account_id: str = "") -> str:
        safe_args = {
            str(key): value
            for key, value in arguments.items()
            if str(key).lower() not in {"access_token", "token", "cookie", "authorization"}
        }
        payload = json.dumps(
            {"tool": tool_name, "account_id": account_id, "arguments": safe_args},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, tool_name: str, arguments: dict[str, Any], account_id: str = "") -> dict[str, Any] | None:
        if tool_name in MEDIA_TOOL_NAMES:
            return None
        try:
            row = self.repository.get_tool_result(self.cache_key(tool_name, arguments, account_id))
        except Exception:
            return None
        if not row:
            return None
        expires_at = _parse_time(row.get("expires_at"))
        row["stale"] = bool(expires_at and expires_at <= datetime.now(timezone.utc))
        return row

    def put(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        account_id: str = "",
        source: str = "mcp",
    ) -> None:
        ttl = 0 if tool_name in MEDIA_TOOL_NAMES else TOOL_TTL_SECONDS.get(tool_name, DEFAULT_TOOL_TTL_SECONDS)
        if ttl <= 0:
            return
        now = datetime.now(timezone.utc)
        try:
            self.repository.save_tool_result(
                cache_key=self.cache_key(tool_name, arguments, account_id),
                tool_name=tool_name,
                account_id=account_id,
                arguments=arguments,
                result=result,
                source=source,
                fetched_at=now,
                expires_at=now + timedelta(seconds=ttl),
            )
        except Exception:
            return


class AccountCacheService:
    def __init__(self, repository: CacheRepository | None = None) -> None:
        self.repository = repository or CacheRepository()

    def directory(self, gateway: Any, *, limit: int = 200, force: bool = False) -> dict[str, Any]:
        cached = self._safe_get_directory()
        if cached and not force and _is_fresh(cached):
            return {"accounts": cached.get("accounts_json") or [], "freshness": "fresh", "as_of": cached.get("fetched_at"), "source": cached.get("source")}
        try:
            accounts = gateway.list_accounts(limit=limit)
            now = datetime.now(timezone.utc)
            self.repository.save_directory(
                accounts=accounts,
                source="account_gateway",
                fetched_at=now,
                expires_at=now + timedelta(seconds=ACCOUNT_DIRECTORY_TTL_SECONDS),
            )
            return {"accounts": accounts, "freshness": "fresh", "as_of": now.isoformat(), "source": "account_gateway"}
        except Exception as exc:
            if cached:
                return {
                    "accounts": cached.get("accounts_json") or [],
                    "freshness": "stale",
                    "as_of": cached.get("fetched_at"),
                    "source": cached.get("source"),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            return {"accounts": [], "freshness": "unavailable", "as_of": "", "source": "", "error": f"{type(exc).__name__}: {exc}"}

    def for_turn(self, account_id: str, gateway: Any, *, force: bool = False) -> dict[str, Any]:
        if not account_id:
            return {}
        cached = self._safe_get_account(account_id)
        if cached and not force and _is_fresh(cached):
            return _context_with_status(cached, "fresh")
        try:
            snapshot = gateway.account_snapshot(account_id=account_id, date_preset="last_7d", limit=100)
            context = build_account_context(account_id, snapshot)
            now = datetime.now(timezone.utc)
            self.repository.save_account_context(
                account_id=account_id,
                context=context,
                source_tools=["ads_get_ad_accounts", "ads_get_ad_entities", "ads_insights_performance_trend"],
                fetched_at=now,
                expires_at=now + timedelta(seconds=ACCOUNT_CONTEXT_TTL_SECONDS),
            )
            return {**context, "freshness": "fresh", "as_of": now.isoformat(), "source_tools": ["ads_get_ad_accounts", "ads_get_ad_entities", "ads_insights_performance_trend"]}
        except Exception as exc:
            if cached:
                return _context_with_status(cached, "stale", error=f"{type(exc).__name__}: {exc}")
            return {
                "account_id": account_id,
                "freshness": "unavailable",
                "as_of": "",
                "source_tools": [],
                "missing_data": [f"Account cache unavailable: {type(exc).__name__}: {exc}"],
            }

    def _safe_get_directory(self) -> dict[str, Any] | None:
        try:
            return self.repository.get_directory()
        except Exception:
            return None

    def _safe_get_account(self, account_id: str) -> dict[str, Any] | None:
        try:
            return self.repository.get_account_context(account_id)
        except Exception:
            return None


def build_account_context(account_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    account = snapshot.get("account") if isinstance(snapshot.get("account"), dict) else {}
    campaigns = snapshot.get("campaigns") if isinstance(snapshot.get("campaigns"), list) else []
    insights = snapshot.get("insights") if isinstance(snapshot.get("insights"), list) else []
    totals, counts = _metric_totals(insights)
    active_campaigns = sum(1 for item in campaigns if str(item.get("effective_status") or item.get("status") or "").upper() == "ACTIVE")
    attention = _attention_rows(insights)
    return {
        "account_id": account_id,
        "name": str(account.get("name") or account.get("account_name") or ""),
        "currency": str(account.get("currency") or ""),
        "timezone": str(account.get("timezone_name") or account.get("timezone") or ""),
        "status": str(account.get("account_status") or account.get("status") or ""),
        "date_preset": str(snapshot.get("date_preset") or "last_7d"),
        "totals": totals,
        "entity_counts": {"campaigns": len(campaigns), "active_campaigns": active_campaigns, "insight_rows": len(insights)},
        "attention": attention,
        "missing_data": [] if insights else ["No insight rows were returned for last_7d."],
    }


def _metric_totals(insights: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, int]]:
    totals = {"spend": 0.0, "impressions": 0.0, "clicks": 0.0, "results": 0.0, "purchase_value": 0.0}
    counts = {"rows": len(insights)}
    for row in insights:
        if not isinstance(row, dict):
            continue
        totals["spend"] += _number(row.get("spend") or row.get("amount_spent"))
        totals["impressions"] += _number(row.get("impressions"))
        totals["clicks"] += _number(row.get("clicks"))
        totals["results"] += _number(row.get("results"))
        totals["purchase_value"] += _number(row.get("purchase_value"))
    spend = totals["spend"]
    clicks = totals["clicks"]
    impressions = totals["impressions"]
    results = totals["results"]
    return {
        "spend": round(spend, 2),
        "impressions": round(impressions, 0),
        "clicks": round(clicks, 0),
        "results": round(results, 2),
        "cpa": round(spend / results, 2) if results else None,
        "ctr": round(clicks / impressions, 4) if impressions else None,
        "cpc": round(spend / clicks, 2) if clicks else None,
    }, counts


def _attention_rows(insights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in insights:
        if not isinstance(item, dict):
            continue
        cost = _number(item.get("cost_per_result") or item.get("cpa"))
        if not cost:
            continue
        rows.append({"name": str(item.get("name") or item.get("campaign_name") or item.get("id") or ""), "cost_per_result": cost})
    return sorted(rows, key=lambda item: item["cost_per_result"], reverse=True)[:3]


def _context_with_status(row: dict[str, Any], freshness: str, error: str = "") -> dict[str, Any]:
    context = dict(row.get("context_json") or {})
    context.update(
        {
            "freshness": freshness,
            "as_of": row.get("fetched_at"),
            "source_tools": row.get("source_tools_json") or [],
        }
    )
    if error:
        context["cache_error"] = error
    return context


def _is_fresh(row: dict[str, Any]) -> bool:
    expires_at = _parse_time(row.get("expires_at"))
    return bool(expires_at and expires_at > datetime.now(timezone.utc))


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "ACCOUNT_CONTEXT_TTL_SECONDS",
    "ACCOUNT_DIRECTORY_TTL_SECONDS",
    "AccountCacheService",
    "MCPToolResultCache",
    "build_account_context",
]