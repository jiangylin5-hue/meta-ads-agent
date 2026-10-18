from fastapi import APIRouter

from ..route_handlers import session as h


router = APIRouter()

router.add_api_route("/sessions/{session_id}", h.session_detail, methods=["GET"])
router.add_api_route("/sessions/{session_id}", h.session_reset, methods=["DELETE"])
