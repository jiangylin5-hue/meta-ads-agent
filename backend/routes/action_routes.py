from fastapi import APIRouter

from ..route_handlers import action as h


router = APIRouter()

router.add_api_route("/actions/drafts", h.actions_draft_create, methods=["POST"])
router.add_api_route("/actions/queue", h.actions_queue, methods=["GET"])
router.add_api_route("/actions/drafts/{draft_id}", h.actions_draft_detail, methods=["GET"])
router.add_api_route("/actions/drafts/{draft_id}/preflight", h.actions_draft_preflight, methods=["POST"])
router.add_api_route("/actions/drafts/{draft_id}/approve", h.actions_draft_approve, methods=["POST"])
router.add_api_route("/actions/drafts/{draft_id}/confirm", h.actions_draft_confirm, methods=["POST"])
router.add_api_route("/actions/drafts/{draft_id}/attempts", h.actions_draft_attempts, methods=["GET"])
router.add_api_route("/actions/drafts/{draft_id}/execute", h.actions_draft_execute, methods=["POST"])
router.add_api_route("/actions/{action_id}/rollback-note", h.actions_rollback_note_create, methods=["POST"])
router.add_api_route("/actions/{execution_id}/rollback", h.actions_rollback_create, methods=["POST"])
