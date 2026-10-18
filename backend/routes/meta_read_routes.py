from fastapi import APIRouter

from ..route_handlers import meta_read as h


router = APIRouter()

router.add_api_route("/meta/adaccounts", h.meta_adaccounts, methods=["GET"])
router.add_api_route("/meta/adaccounts/{ad_account_id}/context", h.meta_account_context, methods=["GET"])
router.add_api_route("/meta/adaccounts/{ad_account_id}/campaigns", h.meta_campaigns, methods=["GET"])
router.add_api_route("/meta/adaccounts/{ad_account_id}/insights", h.meta_insights, methods=["GET"])