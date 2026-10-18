from fastapi import APIRouter

from ..route_handlers import meta_auth as h


router = APIRouter()

router.add_api_route("/accounts/connections", h.account_connections, methods=["GET"])
router.add_api_route("/accounts/mcp/diagnostics", h.account_mcp_diagnostics, methods=["GET"])
router.add_api_route("/meta/status", h.meta_status, methods=["GET"])