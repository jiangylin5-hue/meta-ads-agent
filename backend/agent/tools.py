from __future__ import annotations

import json
import time
from threading import Lock
from typing import Any, Callable
from uuid import uuid4

from jsonschema import Draft202012Validator

from ..config import meta_draft_write_enabled
from ..integrations.meta_ads import MetaAdsProvider
from ..models import ExecutionLogRecord, OptimizationActionDraftRequest
from ..services.account_gateway import RemoteMcpGateway
from ..services.action_drafts import create_action_draft as create_optimization_action_draft
from ..services.action_operations import action_operations_service


LEGACY_WRITE_TOOL_NAMES = {
    "create_campaign", "create_adset", "create_ad", "create_ad_creative", "create_budget_schedule",
    "update_campaign", "update_adset", "update_ad", "update_ad_creative", "upload_ad_image",
}
OFFICIAL_READ_PREFIXES = (
    "ads_get_",
    "ads_insights_",
    "ads_account_get_",
    "ads_catalog_get_",
    "ads_catalog_list_",
    "ads_catalog_event_source_get",
    "ads_experiment_abtest_get_",
    "ads_experiment_lift_get_",
    "ads_experiment_list_",
    "ads_experiment_check_",
    "ads_pixel_event_read",
    "ads_pixel_parameter_read",
)
OFFICIAL_READ_EXACT = {"ads_library_search"}
IGNORED_OFFICIAL_TOOLS = {"ads_log_ui_interaction", "ads_get_ad_preview_screenshot"}
WRITE_TOOL_NAMES = LEGACY_WRITE_TOOL_NAMES
DIRECT_DRAFT_CREATE_TOOLS = {
    "ads_create_campaign",
    "ads_create_ad_set",
    "ads_create_ad",
    "ads_create_creative",
}
FORBIDDEN_PUBLISH_TOOLS = {"ads_activate_entity"}
MEDIA_TOOL_NAMES = {"get_ad_image", "get_ad_video", "get_image_by_hash", "ads_get_ad_images", "ads_get_ad_videos", "ads_get_ad_preview_screenshot"}
WRITE_TARGETS: dict[str, tuple[str, str]] = {
    "create_campaign": ("account", "account_id"),
    "create_adset": ("campaign", "campaign_id"),
    "create_ad": ("adset", "adset_id"),
    "create_ad_creative": ("creative", "creative_id"),
    "create_budget_schedule": ("account", "account_id"),
    "update_campaign": ("campaign", "campaign_id"),
    "update_adset": ("adset", "adset_id"),
    "update_ad": ("ad", "ad_id"),
    "update_ad_creative": ("creative", "creative_id"),
    "upload_ad_image": ("account", "account_id"),
}
SENSITIVE_KEYS = {"access_token", "token", "secret", "api_key", "authorization", "cookie", "password"}
MAX_GENERAL_RESULT_CHARS = 16000
MAX_MEDIA_RESULT_CHARS = 4000
MAX_STRING_CHARS = 4000
MAX_LIST_ITEMS = 50
TOOL_CACHE_SECONDS = 300
_TOOL_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_TOOL_CACHE_LOCK = Lock()


class MetaToolRegistry:
    """MCP-native tool registry with local execution guardrails."""

    def __init__(
        self,
        provider: MetaAdsProvider | None = None,
        mcp_client: Any | None = None,
        tool_definitions: list[dict[str, Any]] | None = None,
        draft_creator: Callable[[OptimizationActionDraftRequest], Any] | None = None,
        action_creator: Callable[[Any], Any] | None = None,
        preflight_runner: Callable[[str], Any] | None = None,
        result_cache: Any | None = None,
        direct_draft_logger: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.provider = provider or MetaAdsProvider()
        self.remote = RemoteMcpGateway(access_token=self.provider.access_token_for_requests())
        self.client = mcp_client or self.remote.client
        if tool_definitions is None:
            tool_definitions = _discover_tools(self.client)
        self.tool_definitions = [dict(item) for item in tool_definitions if item.get("name")]
        if not self.tool_definitions:
            raise RuntimeError("No MCP tools are available.")
        self.tools_by_name = {str(item["name"]): item for item in self.tool_definitions}
        self.draft_creator = draft_creator or create_optimization_action_draft
        self.action_creator = action_creator or (lambda draft: action_operations_service().create_from_optimization_draft(draft))
        self.preflight_runner = preflight_runner or (lambda action_id: action_operations_service().run_preflight(action_id))
        self.result_cache = result_cache
        self.direct_draft_logger = direct_draft_logger or _log_direct_draft_execution
        self.selected_account_id = ""
        self.request_text = ""
        self.advertiser_job = "other"
        self.client_conversation_id = uuid4().hex[:20]
        self.deadline: float | None = None

    def set_context(self, account_id: str = "", request_text: str = "") -> None:
        self.selected_account_id = account_id.strip()
        self.request_text = request_text.strip()
        self.advertiser_job = "other"

    def set_advertiser_job(self, job: str) -> None:
        self.advertiser_job = str(job or "other").strip() or "other"

    def set_deadline(self, deadline: float | None) -> None:
        self.deadline = deadline

    def _remaining_timeout(self) -> float | None:
        if self.deadline is None:
            return None
        return max(0.1, self.deadline - time.monotonic())

    def validate_arguments(self, name: str, args: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(args, dict):
            return {"error": f"Arguments for {name} must be a JSON object."}
        if "__argument_parse_error__" in args:
            return {"error": f"Invalid JSON arguments for {name}: {args['__argument_parse_error__']}"}
        hidden = {"access_token", "advertiser_request", "advertiser_job", "client_conversation_id"}
        supplied_hidden = sorted(hidden.intersection(args))
        if supplied_hidden:
            return {"error": f"Arguments for {name} contain runtime-only fields: {', '.join(supplied_hidden)}"}
        original_schema = self.tools_by_name[name].get("inputSchema") or self.tools_by_name[name].get("input_schema") or {}
        schema = _model_parameters(name, original_schema)
        try:
            validator = Draft202012Validator(schema)
            errors = sorted(validator.iter_errors(args), key=lambda error: list(error.absolute_path))
        except Exception as exc:
            return {"error": f"Tool schema validation failed for {name}: {type(exc).__name__}: {exc}"}
        if errors:
            details = []
            for error in errors[:8]:
                path = ".".join(str(part) for part in error.absolute_path) or "<root>"
                details.append(f"{path}: {error.message}")
            return {"error": f"Invalid arguments for {name}.", "schema_errors": details}
        return None

    def schemas(self) -> list[dict[str, Any]]:
        namespace_tools = []
        for tool in self.tool_definitions:
            name = str(tool["name"])
            if is_ignored_tool(name) or is_forbidden_publish_tool(name):
                continue
            parameters = _model_parameters(name, tool.get("inputSchema") or tool.get("input_schema") or {})
            description = str(tool.get("description") or "")
            if is_direct_draft_create_tool(name):
                description = "Create a non-published Meta Draft object directly. Never activates or publishes. " + description
            elif is_write_tool(name):
                description = "Prepare a local approval draft. This tool never executes a Meta write. " + description
            if name in MEDIA_TOOL_NAMES:
                description = "Return bounded media metadata; raw media bytes and data URLs are omitted. " + description
            namespace_tools.append(
                {
                    "type": "function",
                    "name": name,
                    "description": description[:4000],
                    "parameters": parameters,
                    "defer_loading": True,
                }
            )
        return [
            {
                "type": "namespace",
                "name": "meta_ads",
                "description": "Meta Ads MCP tools. Use tool_search to load the tools relevant to the task.",
                "tools": namespace_tools,
            },
            {"type": "tool_search"},
            _local_tool(
                "ask_user",
                "Stop and ask one focused question when required context is missing.",
                {"question": {"type": "string"}},
                ["question"],
            ),
        ]

    def portable_schemas(self, allowed_tools: set[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for name in sorted(allowed_tools):
            tool = self.tools_by_name.get(name)
            if not tool or is_ignored_tool(name) or is_forbidden_publish_tool(name):
                continue
            parameters = _model_parameters(name, tool.get("inputSchema") or tool.get("input_schema") or {})
            description = str(tool.get("description") or "")
            if is_direct_draft_create_tool(name):
                description = "Create a non-published Meta Draft object directly. Never activates or publishes. " + description
            elif is_write_tool(name):
                description = "Prepare a local approval draft. This tool never executes a Meta write. " + description
            if name in MEDIA_TOOL_NAMES:
                description = "Return bounded media metadata; raw media bytes and data URLs are omitted. " + description
            output.append(
                {
                    "type": "function",
                    "name": name,
                    "description": description[:4000],
                    "parameters": parameters,
                }
            )
        return output

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(arguments or {})
        args.pop("access_token", None)
        if name == "ask_user":
            return {"needs_user_input": True, "question": str(args.get("question") or "I need one more detail.")}
        if name not in self.tools_by_name:
            return {"error": f"Unknown MCP tool: {name}"}
        if is_ignored_tool(name):
            return {"error": f"Tool is not exposed to the agent: {name}"}
        validation_error = self.validate_arguments(name, args)
        if validation_error:
            return validation_error
        if is_direct_draft_create_tool(name):
            return self.create_paused_draft(name, args)
        if is_write_tool(name):
            return self._create_write_draft(name, args)
        return self._execute_read(name, args)

    def create_paused_draft(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if not is_direct_draft_create_tool(name):
            return {"error": f"Tool is not an allowed direct Draft creator: {name}"}
        if not meta_draft_write_enabled():
            return {"error": "Direct Meta Draft creation is disabled. Set META_DRAFT_WRITE_ENABLED=true."}
        if not self.client:
            return {"error": "ADS_MCP_ENDPOINT_URL is not configured."}
        validation_error = self.validate_arguments(name, args)
        if validation_error:
            return validation_error
        request_args = dict(args)
        for key in (
            "access_token",
            "evidence",
            "recommendation",
            "risk_level",
            "current_state",
            "status",
            "campaign_status",
            "ad_set_status",
            "ad_status",
            "effective_status",
            "publish_as_active",
        ):
            request_args.pop(key, None)
        schema = self.tools_by_name[name].get("inputSchema") or self.tools_by_name[name].get("input_schema") or {}
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if "ad_account_id" in props and not str(request_args.get("ad_account_id") or "").strip() and self.selected_account_id:
            request_args["ad_account_id"] = self.selected_account_id.removeprefix("act_")
        if "client_conversation_id" in props:
            request_args.setdefault("client_conversation_id", self.client_conversation_id)
        if "advertiser_request" in props:
            request_args.setdefault("advertiser_request", self.request_text or "Create a paused Meta draft.")
        if "advertiser_job" in props:
            request_args.setdefault("advertiser_job", self.advertiser_job or "other")
        token = self.provider.access_token_for_requests()
        if token and getattr(self.client, "injects_access_token_argument", True):
            request_args["access_token"] = token
        original_timeout = getattr(self.client, "timeout", None)
        remaining_timeout = self._remaining_timeout()
        if original_timeout is not None and remaining_timeout is not None:
            self.client.timeout = max(1, min(float(original_timeout), remaining_timeout))
        try:
            raw = self.client.call_tool(name, request_args)
        except Exception as exc:
            payload = {
                "tool": name,
                "created": False,
                "published": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            self._record_direct_draft(name, args, payload)
            return payload
        finally:
            if original_timeout is not None:
                self.client.timeout = original_timeout
        if isinstance(raw, dict):
            conversation_id = raw.get("client_conversation_id")
            if conversation_id:
                self.client_conversation_id = str(conversation_id)
        normalized = _normalize_mcp_result(name, raw)
        bounded = _bounded_result(name, normalized, MAX_GENERAL_RESULT_CHARS)
        provider_error = _provider_result_error(normalized)
        if provider_error:
            payload = {
                "tool": name,
                "created": False,
                "draft_mode": True,
                "published": False,
                "status": "FAILED",
                "error": provider_error,
                "result": bounded.get("result"),
                "truncated": bool(bounded.get("truncated")),
            }
            self._record_direct_draft(name, args, payload)
            return payload
        created_id = _created_entity_id(normalized)
        payload = {
            "tool": name,
            "created": True,
            "draft_mode": True,
            "published": False,
            "status": "DRAFT",
            "meta_draft_status": _extract_meta_draft_status(normalized),
            "created_entity_id": created_id,
            "result": bounded.get("result"),
            "truncated": bool(bounded.get("truncated")),
        }
        self._record_direct_draft(name, args, payload)
        return payload

    def _record_direct_draft(self, name: str, args: dict[str, Any], payload: dict[str, Any]) -> None:
        try:
            self.direct_draft_logger(
                {
                    "account_id": str(args.get("ad_account_id") or self.selected_account_id or ""),
                    "tool": name,
                    "risk_level": str(args.get("risk_level") or ""),
                    "created_entity_id": str(payload.get("created_entity_id") or ""),
                    "created": bool(payload.get("created")),
                    "error": str(payload.get("error") or ""),
                }
            )
        except Exception:
            return

    def _execute_read(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self.client:
            return {"error": "ADS_MCP_ENDPOINT_URL is not configured."}
        schema = self.tools_by_name[name].get("inputSchema") or self.tools_by_name[name].get("input_schema") or {}
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if "account_id" in props and not str(args.get("account_id") or "").strip() and self.selected_account_id:
            args["account_id"] = self.selected_account_id
        if "ad_account_id" in props and not str(args.get("ad_account_id") or "").strip() and self.selected_account_id:
            args["ad_account_id"] = self.selected_account_id.removeprefix("act_")
        if "client_conversation_id" in props:
            args.setdefault("client_conversation_id", self.client_conversation_id)
        if "advertiser_request" in props:
            args.setdefault("advertiser_request", self.request_text or "Read Meta Ads data.")
        if "advertiser_job" in props:
            args.setdefault("advertiser_job", self.advertiser_job or "other")
        force_refresh = bool(args.pop("force_refresh", False))
        cache_args = {
            key: value
            for key, value in args.items()
            if key not in {"access_token", "client_conversation_id", "advertiser_request", "advertiser_job", "force_refresh"}
        }
        cached = None if force_refresh else (self.result_cache.get(name, cache_args, self.selected_account_id) if self.result_cache else None)
        if cached and not cached.get("stale"):
            return _cached_payload(cached)
        token = self.provider.access_token_for_requests()
        if token and getattr(self.client, "injects_access_token_argument", True):
            args["access_token"] = token
        original_timeout = getattr(self.client, "timeout", None)
        remaining_timeout = self._remaining_timeout()
        if original_timeout is not None and remaining_timeout is not None:
            self.client.timeout = max(1, min(float(original_timeout), remaining_timeout))
        try:
            result = self.client.call_tool(name, args)
        except Exception as exc:
            if cached:
                return _cached_payload(cached, error=f"{type(exc).__name__}: {exc}")
            return {"error": f"{type(exc).__name__}: {exc}"}
        finally:
            if original_timeout is not None:
                self.client.timeout = original_timeout
        if isinstance(result, dict):
            conversation_id = result.get("client_conversation_id")
            if conversation_id:
                self.client_conversation_id = str(conversation_id)
        result = _normalize_mcp_result(name, result)
        limit = MAX_MEDIA_RESULT_CHARS if name in MEDIA_TOOL_NAMES else MAX_GENERAL_RESULT_CHARS
        bounded = _bounded_result(name, result, limit)
        if self.result_cache:
            self.result_cache.put(name, cache_args, bounded, self.selected_account_id)
        return bounded

    def stage_write(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if is_forbidden_publish_tool(name):
            return {"error": f"Publishing or activation is not available: {name}"}
        validation_error = self.validate_arguments(name, args)
        if validation_error:
            return validation_error
        built = self._build_write_action(name, args)
        if "error" in built:
            return built
        return {"status": "staged", **built}

    def commit_staged_action(self, staged: dict[str, Any]) -> dict[str, Any]:
        action = staged.get("action") if isinstance(staged.get("action"), dict) else None
        if not action:
            return {"error": "Staged action is missing its action payload."}
        return self._commit_action(staged, action)

    def _create_write_draft(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        built = self._build_write_action(name, args)
        if "error" in built:
            return built
        return self._commit_action(built, built["action"])

    def _build_write_action(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        args = dict(args)
        args.pop("access_token", None)
        evidence = str(args.get("evidence") or "").strip()
        recommendation = str(args.get("recommendation") or "").strip()
        risk_level = str(args.get("risk_level") or "medium").strip().lower()
        if not evidence or not recommendation:
            return {"error": f"{name} requires evidence and recommendation before a draft can be created."}
        current_state = args.pop("current_state", None)
        if not isinstance(current_state, dict) or not current_state:
            return {"error": f"{name} requires a non-empty current_state object before a draft can be created."}
        account_id = str(args.get("ad_account_id") or args.get("account_id") or self.selected_account_id).strip()
        if not account_id:
            return {"error": f"{name} requires ad_account_id or a selected account."}
        target_level, target_key = _draft_target(name, args)
        target_id = str(args.get(target_key) or _first_entity_id(args) or "pending").strip()
        target_name = str(args.get("name") or args.get("campaign_name") or args.get("adset_name") or args.get("ad_name") or "")
        proposed = _sanitize_value(
            {
                key: value
                for key, value in args.items()
                if key not in {"evidence", "recommendation", "risk_level", "access_token", "file", "client_conversation_id", "advertiser_request", "advertiser_job"}
            }
        )
        if "file" in args:
            proposed["file_data_omitted"] = True
            proposed["file_chars"] = len(str(args.get("file") or ""))
        action = {
            "id": f"mcp_{name}_{target_id}"[:80],
            "action_type": name,
            "target_level": target_level,
            "target_id": target_id,
            "target_name": target_name,
            "evidence": evidence,
            "judgment": recommendation,
            "recommendation": recommendation,
            "risk_level": risk_level,
            "current_value": _sanitize_value(current_state),
            "proposed_value": proposed,
            "requires_approval": True,
        }
        return {
            "tool": name,
            "action": action,
            "account_id": account_id,
            "target_level": target_level,
            "target_id": target_id,
            "target_name": target_name,
            "evidence": evidence,
            "recommendation": recommendation,
            "risk_level": risk_level,
        }

    def _commit_action(self, staged: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        account_id = str(staged.get("account_id") or "").strip()
        if not account_id:
            return {"error": "Staged action is missing account_id."}
        draft = self.draft_creator(OptimizationActionDraftRequest(account_id=account_id, source="manual", action=action))
        action_record: dict[str, Any] = {}
        preflight: dict[str, Any] = {}
        action_id = ""
        try:
            lifecycle = self.action_creator(draft)
            action_id = str(getattr(lifecycle, "id", "") or "")
            action_record = {"id": action_id, "status": getattr(lifecycle, "status", "")}
            if action_id:
                try:
                    preflight = dict(self.preflight_runner(action_id).get("preflight") or {})
                except Exception as exc:
                    preflight = {"result": "blocked", "blocked_reasons": [f"Preflight failed: {type(exc).__name__}: {exc}"]}
        except Exception as exc:
            action_record = {"warning": f"Draft saved but lifecycle record failed: {type(exc).__name__}: {exc}"}
        return {
            "tool": str(staged.get("tool") or action.get("action_type") or ""),
            "draft_id": draft.id,
            "action_id": action_id,
            "draft_status": draft.status,
            "requires_approval": True,
            "target_level": staged.get("target_level"),
            "target_id": staged.get("target_id"),
            "target_name": staged.get("target_name"),
            "evidence": staged.get("evidence"),
            "recommendation": staged.get("recommendation"),
            "risk_level": staged.get("risk_level"),
            "preflight": preflight,
            "action_record": action_record,
        }


def _discover_tools(client: Any | None) -> list[dict[str, Any]]:
    if client is None:
        raise RuntimeError("ADS_MCP_ENDPOINT_URL is not configured.")
    endpoint = str(getattr(client, "endpoint", "") or "default")
    now = time.monotonic()
    with _TOOL_CACHE_LOCK:
        cached = _TOOL_CACHE.get(endpoint)
        if cached and now - cached[0] < TOOL_CACHE_SECONDS:
            return [dict(item) for item in cached[1]]
    tools = client.list_tools()
    with _TOOL_CACHE_LOCK:
        _TOOL_CACHE[endpoint] = (now, [dict(item) for item in tools])
    return tools


def _model_parameters(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    parameters = json.loads(json.dumps(schema))
    properties = parameters.get("properties") if isinstance(parameters.get("properties"), dict) else {}
    for hidden in ("access_token", "advertiser_request", "advertiser_job", "client_conversation_id"):
        properties.pop(hidden, None)
    if name == "upload_ad_image":
        properties.pop("file", None)
    if is_read_tool(name):
        properties["force_refresh"] = {
            "type": "boolean",
            "description": "Bypass the read cache. Use true before creating a write-like Draft when current state is required.",
        }
    hidden_names = {"access_token", "advertiser_request", "advertiser_job", "client_conversation_id"}
    required = [item for item in (parameters.get("required") or []) if item not in hidden_names and not (name == "upload_ad_image" and item == "file")]
    if is_write_tool(name):
        properties["evidence"] = {"type": "string", "description": "Observed evidence supporting the draft."}
        properties["recommendation"] = {"type": "string", "description": "Proposed change and expected rationale."}
        properties["risk_level"] = {"type": "string", "enum": ["low", "medium", "high"], "default": "medium"}
        properties["current_state"] = {"type": "object", "description": "Current entity state from a successful read, including budget/status and relevant evidence context."}
        for item in ("evidence", "recommendation", "risk_level", "current_state"):
            if item not in required:
                required.append(item)
    parameters["properties"] = properties
    parameters["required"] = required
    parameters.setdefault("type", "object")
    return parameters



def is_ignored_tool(name: str) -> bool:
    return name in IGNORED_OFFICIAL_TOOLS


def is_read_tool(name: str) -> bool:
    if name in OFFICIAL_READ_EXACT:
        return True
    if name.startswith("ads_"):
        return name.startswith(OFFICIAL_READ_PREFIXES)
    return name in {"list_accounts", "get_account_summary", "get_entity_insights"}


def is_direct_draft_create_tool(name: str) -> bool:
    return name in DIRECT_DRAFT_CREATE_TOOLS


def is_forbidden_publish_tool(name: str) -> bool:
    return name in FORBIDDEN_PUBLISH_TOOLS or "publish" in name.lower()


def is_write_tool(name: str) -> bool:
    if name in LEGACY_WRITE_TOOL_NAMES:
        return True
    if not name.startswith("ads_"):
        return False
    return not is_read_tool(name) and not is_ignored_tool(name)





def _provider_result_error(value: Any) -> str:
    if isinstance(value, dict):
        error_message = str(value.get("error_message") or "").strip()
        if error_message:
            return error_message[:1000]
        error = value.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()[:1000]
        if isinstance(error, dict) and error:
            return json.dumps(error, ensure_ascii=False)[:1000]
        errors = value.get("errors")
        if isinstance(errors, list) and errors:
            return json.dumps(errors, ensure_ascii=False)[:1000]
        for nested in value.values():
            found = _provider_result_error(nested)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _provider_result_error(item)
            if found:
                return found
    return ""

def _extract_meta_draft_status(value: Any) -> str:
    if isinstance(value, dict):
        draft_status = value.get("status")
        if isinstance(draft_status, str) and draft_status.upper() in {"EDITING", "VALIDATED"}:
            return draft_status.upper()
        for item in value.values():
            status = _extract_meta_draft_status(item)
            if status:
                return status
    if isinstance(value, list):
        for item in value:
            status = _extract_meta_draft_status(item)
            if status:
                return status
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return ""
        return _extract_meta_draft_status(parsed)
    return ""

def _created_entity_id(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("id", "ad_object_id", "campaign_id", "ad_set_id", "ad_id", "creative_id"):
            if value.get(key):
                return str(value[key])
        for key in ("data", "result", "created", "campaign", "ad_set", "ad", "creative"):
            nested = value.get(key)
            entity_id = _created_entity_id(nested)
            if entity_id:
                return entity_id
    if isinstance(value, list):
        for item in value:
            entity_id = _created_entity_id(item)
            if entity_id:
                return entity_id
    return ""


def _log_direct_draft_execution(event: dict[str, Any]) -> None:
    from ..services.persistent_store import PersistentStore

    created = bool(event.get("created"))
    entity_id = str(event.get("created_entity_id") or "")
    PersistentStore().save_execution_log(
        ExecutionLogRecord(
            account_id=str(event.get("account_id") or ""),
            source_type="action_draft",
            source_id=f"direct_draft:{entity_id or event.get('tool')}",
            status="succeeded" if created else "failed",
            request_summary={
                "tool": event.get("tool"),
                "mode": "meta_draft_mode",
                "risk_level": event.get("risk_level"),
            },
            result={"created_entities": [{"id": entity_id, "entity_type": "draft", "status": "draft"}]} if created else {},
            error=str(event.get("error") or ""),
        )
    )

def _draft_target(name: str, args: dict[str, Any]) -> tuple[str, str]:
    if name in WRITE_TARGETS:
        return WRITE_TARGETS[name]
    entity_type = str(args.get("entity_type") or "").lower()
    if entity_type:
        level = {"ad_set": "adset", "adset": "adset", "campaign": "campaign", "ad": "ad"}.get(entity_type, entity_type)
        return level, "entity_id"
    for key, level in (("campaign_id", "campaign"), ("ad_set_id", "adset"), ("adset_id", "adset"), ("ad_id", "ad"), ("creative_id", "creative")):
        if args.get(key):
            return level, key
    return "account", "ad_account_id"


def _normalize_mcp_result(name: str, result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    normalized = dict(result)
    for key in ("ad_entities", "ad_accounts", "ad_creatives", "ad_images", "ad_videos", "ad_drafts"):
        value = normalized.get(key)
        if isinstance(value, str):
            try:
                normalized[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return normalized

def _local_tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }



def _cached_payload(row: dict[str, Any], *, error: str = "") -> dict[str, Any]:
    payload = json.loads(json.dumps(row.get("result_json") or {}, ensure_ascii=False))
    payload["_cache"] = {
        "hit": True,
        "fresh": not bool(row.get("stale")),
        "stale": bool(row.get("stale")),
        "fetched_at": row.get("fetched_at"),
        "expires_at": row.get("expires_at"),
    }
    if error:
        payload["_cache"]["error"] = error
        payload["_cache"]["fallback"] = "stale_cache"
    return payload


def _bounded_result(tool_name: str, value: Any, max_chars: int) -> dict[str, Any]:
    original_chars = len(value) if isinstance(value, str) else len(json.dumps(value, ensure_ascii=False))
    parsed = _parse_jsonish(value)
    sanitized = _sanitize_value(parsed)
    payload = {"tool": tool_name, "result": sanitized, "truncated": original_chars > max_chars}
    if payload["truncated"]:
        payload["original_chars"] = original_chars
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) <= max_chars:
        return payload
    preview = text[: max(0, max_chars - 300)]
    return {
        "tool": tool_name,
        "truncated": True,
        "original_chars": len(text),
        "preview": preview,
        "note": "Result exceeded the context budget. Request a narrower query if more detail is needed.",
    }


def _parse_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 60:
                output["_truncated_keys"] = len(value) - 60
                break
            if str(key).lower() in SENSITIVE_KEYS:
                output[str(key)] = "[redacted]"
            else:
                output[str(key)] = _sanitize_value(item)
        return output
    if isinstance(value, list):
        output = [_sanitize_value(item) for item in value[:MAX_LIST_ITEMS]]
        if len(value) > MAX_LIST_ITEMS:
            output.append({"_truncated_items": len(value) - MAX_LIST_ITEMS})
        return output
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered.startswith("data:") or "base64," in lowered[:200]:
            return {"data_omitted": True, "chars": len(value)}
        if len(value) > MAX_STRING_CHARS:
            return value[:MAX_STRING_CHARS] + "...[truncated]"
    return value


def _first_entity_id(args: dict[str, Any]) -> str:
    for key in ("campaign_id", "adset_id", "ad_id", "creative_id", "ad_creative_id", "image_hash"):
        value = str(args.get(key) or "").strip()
        if value:
            return value
    return ""
