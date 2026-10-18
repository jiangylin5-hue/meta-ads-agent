from typing import Any

from fastapi import APIRouter

from ..services.account_gateway import RemoteMcpGateway, connection_statuses
from .common import _meta_provider

router = APIRouter()


@router.get("/accounts/connections")
def account_connections(session_id: str = "") -> dict[str, Any]:
    return {
        "connections": connection_statuses(_meta_provider()),
        "strategy": "Official Meta Ads MCP first; local Meta provider is an explicit fallback",
    }


@router.get("/accounts/mcp/diagnostics")
def account_mcp_diagnostics() -> dict[str, Any]:
    return RemoteMcpGateway().diagnostics()


@router.get("/meta/status")
def meta_status(session_id: str = "") -> dict[str, Any]:
    status = _meta_provider().status()
    status["session_connected"] = bool(status.get("configured"))
    status["user"] = None
    return status


__all__ = [name for name in globals() if not name.startswith("__")]