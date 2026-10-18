from fastapi import APIRouter

from ..route_handlers import admin as h
from ..route_handlers import common as common_h


router = APIRouter()

router.add_api_route("/execution-logs", h.execution_logs, methods=["GET"])
router.add_api_route("/execution-logs/{execution_id}", h.execution_log_detail, methods=["GET"])
router.add_api_route("/agent/traces/{trace_id}", common_h.agent_trace_detail, methods=["GET"])
