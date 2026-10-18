from fastapi import APIRouter

from ..route_handlers import config as h


router = APIRouter()

router.add_api_route("/config", h.config, methods=["GET"])
router.add_api_route("/config/reload", h.config_reload, methods=["POST"])
