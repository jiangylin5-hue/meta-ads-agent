from fastapi import APIRouter

from ..route_handlers import memory as h


router = APIRouter()
router.add_api_route("/memory", h.list_memory, methods=["GET"])
router.add_api_route("/memory/{memory_id}/confirm", h.confirm_memory, methods=["POST"])
router.add_api_route("/memory/{memory_id}/reject", h.reject_memory, methods=["POST"])
router.add_api_route("/memory/{memory_id}", h.delete_memory, methods=["DELETE"])
