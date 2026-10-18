from typing import Any

from fastapi import APIRouter

from ..services.account_cache import AccountCacheService, MCPToolResultCache
from ..services.account_gateway import gateway_for
from ..services.session_store import get_or_create_session
from .common import _meta_provider, _meta_runtime_exception

router = APIRouter()


@router.get("/meta/adaccounts")
def meta_adaccounts(session_id: str = "", limit: int = 200, refresh: bool = False) -> dict[str, Any]:
    _, state = get_or_create_session(session_id)
    try:
        gateway = gateway_for("meta", _meta_provider(state))
        result = AccountCacheService().directory(gateway, limit=limit, force=refresh)
    except RuntimeError as exc:
        raise _meta_runtime_exception(exc) from exc
    return {"provider": "meta_auto_gateway", **result}


@router.get("/meta/adaccounts/{ad_account_id}/context")
def meta_account_context(ad_account_id: str, session_id: str = "", refresh: bool = False) -> dict[str, Any]:
    _, state = get_or_create_session(session_id)
    try:
        gateway = gateway_for("meta", _meta_provider(state))
        context = AccountCacheService().for_turn(ad_account_id, gateway, force=refresh)
    except RuntimeError as exc:
        raise _meta_runtime_exception(exc) from exc
    return {"provider": "meta_auto_gateway", "context": context}


@router.get("/meta/adaccounts/{ad_account_id}/campaigns")
def meta_campaigns(ad_account_id: str, session_id: str = "", limit: int = 50, refresh: bool = False) -> dict[str, Any]:
    _, state = get_or_create_session(session_id)
    cache = MCPToolResultCache()
    args = {"account_id": ad_account_id, "limit": limit}
    cached = None if refresh else cache.get("gateway_list_campaigns", args, ad_account_id)
    if cached and not cached.get("stale"):
        return {
            "provider": "mcp_tool_cache",
            "ad_account_id": ad_account_id,
            "campaigns": (cached.get("result_json") or {}).get("result") or [],
            "cache": {"hit": True, "fetched_at": cached.get("fetched_at"), "expires_at": cached.get("expires_at")},
        }
    try:
        gateway = gateway_for("meta", _meta_provider(state))
        campaigns = gateway.list_campaigns(account_id=ad_account_id, limit=limit)
    except RuntimeError as exc:
        if cached:
            return {
                "provider": "stale_cache",
                "ad_account_id": ad_account_id,
                "campaigns": (cached.get("result_json") or {}).get("result") or [],
                "cache": {"hit": True, "stale": True, "fetched_at": cached.get("fetched_at"), "error": str(exc)[:500]},
            }
        raise _meta_runtime_exception(exc) from exc
    cache.put("gateway_list_campaigns", args, {"tool": "gateway_list_campaigns", "result": campaigns}, ad_account_id, "gateway")
    return {"provider": "meta_auto_gateway", "ad_account_id": ad_account_id, "campaigns": campaigns, "cache": {"hit": False}}


@router.get("/meta/adaccounts/{ad_account_id}/insights")
def meta_insights(
    ad_account_id: str,
    session_id: str = "",
    date_preset: str = "last_7d",
    level: str = "campaign",
    limit: int = 50,
    refresh: bool = False,
) -> dict[str, Any]:
    _, state = get_or_create_session(session_id)
    cache = MCPToolResultCache()
    args = {"account_id": ad_account_id, "date_preset": date_preset, "level": level, "limit": limit}
    cached = None if refresh else cache.get("gateway_get_insights", args, ad_account_id)
    if cached and not cached.get("stale"):
        return {
            "provider": "mcp_tool_cache",
            "ad_account_id": ad_account_id,
            "date_preset": date_preset,
            "level": level,
            "insights": (cached.get("result_json") or {}).get("result") or [],
            "cache": {"hit": True, "fetched_at": cached.get("fetched_at"), "expires_at": cached.get("expires_at")},
        }
    try:
        gateway = gateway_for("meta", _meta_provider(state))
        insights = gateway.get_insights(account_id=ad_account_id, date_preset=date_preset, level=level, limit=limit)
    except RuntimeError as exc:
        if cached:
            return {
                "provider": "stale_cache",
                "ad_account_id": ad_account_id,
                "date_preset": date_preset,
                "level": level,
                "insights": (cached.get("result_json") or {}).get("result") or [],
                "cache": {"hit": True, "stale": True, "fetched_at": cached.get("fetched_at"), "error": str(exc)[:500]},
            }
        raise _meta_runtime_exception(exc) from exc
    cache.put("gateway_get_insights", args, {"tool": "gateway_get_insights", "result": insights}, ad_account_id, "gateway")
    return {
        "provider": "meta_auto_gateway",
        "ad_account_id": ad_account_id,
        "date_preset": date_preset,
        "level": level,
        "insights": insights,
        "cache": {"hit": False},
    }


__all__ = [name for name in globals() if not name.startswith("__")]