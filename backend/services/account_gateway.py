import json
from itertools import count
from threading import Lock
from typing import Any, Protocol
from urllib import error, request
from uuid import uuid4

from ..config import (
    account_gateway_preference,
    meta_access_token,
    remote_ads_mcp_endpoint,
    remote_ads_mcp_token,
)
from ..integrations.meta_ads import MetaAdsProvider


REQUIRED_META_MCP_TOOLS = {"get_ad_accounts", "get_account_info", "get_campaigns", "get_insights"}
OPTIONAL_META_MCP_TOOLS = {"get_adsets", "get_ads", "get_ad_creatives"}
REQUIRED_OFFICIAL_META_MCP_TOOLS = {"ads_get_ad_accounts", "ads_get_ad_entities", "ads_insights_performance_trend"}
OPTIONAL_OFFICIAL_META_MCP_TOOLS = {
    "ads_account_get_activity_logs",
    "ads_get_opportunity_score",
    "ads_insights_anomaly_signal",
    "ads_get_creatives",
}


class AccountDataProvider(Protocol):
    name: str

    def connection_status(self) -> dict[str, Any]:
        ...

    def list_accounts(self, limit: int = 100) -> list[dict[str, Any]]:
        ...

    def account_snapshot(self, account_id: str, date_preset: str = "last_7d", limit: int = 50) -> dict[str, Any]:
        ...

    def list_campaigns(self, account_id: str, limit: int = 50) -> list[dict[str, Any]]:
        ...

    def list_adsets(self, account_id: str, limit: int = 100, campaign_id: str = "") -> list[dict[str, Any]]:
        ...

    def list_ads(self, account_id: str, limit: int = 100) -> list[dict[str, Any]]:
        ...

    def list_creatives(self, account_id: str, limit: int = 100) -> list[dict[str, Any]]:
        ...

    def get_insights(
        self,
        account_id: str,
        date_preset: str = "last_7d",
        level: str = "campaign",
        limit: int = 50,
        time_increment: str = "",
        breakdowns: list[str] | None = None,
        action_breakdowns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        ...


class MetaAccountGateway:
    name = "meta"

    def __init__(self, provider: MetaAdsProvider) -> None:
        self.provider = provider

    def connection_status(self) -> dict[str, Any]:
        status = self.provider.status()
        return {
            "platform": self.name,
            "provider": "local_meta_marketing_api",
            "configured": status.get("configured", False),
            "read_enabled": status.get("configured", False),
            "write_enabled": False,
            "allowed_operations": status.get("allowed_operations", []),
            "note": "Read-only Meta provider for ad accounts, campaigns, and insights.",
        }

    def list_accounts(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.provider.list_ad_accounts(limit=limit)

    def account_snapshot(self, account_id: str, date_preset: str = "last_7d", limit: int = 50) -> dict[str, Any]:
        return {
            "platform": self.name,
            "provider": "local_meta_marketing_api",
            "account_id": account_id,
            "date_preset": date_preset,
            "campaigns": self.list_campaigns(account_id=account_id, limit=limit),
            "insights": self.get_insights(account_id=account_id, date_preset=date_preset, level="campaign", limit=limit),
        }

    def list_campaigns(self, account_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.provider.list_campaigns(ad_account_id=account_id, limit=limit)

    def list_adsets(self, account_id: str, limit: int = 100, campaign_id: str = "") -> list[dict[str, Any]]:
        return self.provider.list_adsets(ad_account_id=account_id, limit=limit, campaign_id=campaign_id)

    def list_ads(self, account_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.provider.list_ads(ad_account_id=account_id, limit=limit)

    def list_creatives(self, account_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.provider.list_creatives(ad_account_id=account_id, limit=limit)

    def get_insights(
        self,
        account_id: str,
        date_preset: str = "last_7d",
        level: str = "campaign",
        limit: int = 50,
        time_increment: str = "",
        breakdowns: list[str] | None = None,
        action_breakdowns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "ad_account_id": account_id,
            "date_preset": date_preset,
            "level": level,
            "limit": limit,
            "time_increment": time_increment,
        }
        if breakdowns is not None:
            kwargs["breakdowns"] = breakdowns
        if action_breakdowns is not None:
            kwargs["action_breakdowns"] = action_breakdowns
        return self.provider.get_insights(**kwargs)


class MetaMcpClient:
    def __init__(self, endpoint: str, token: str = "", timeout: int = 45) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._ids = count(1)
        self._session_id = ""
        self._protocol_version = ""
        self._initialized = False
        self._session_lock = Lock()
        self.injects_access_token_argument = "mcp.facebook.com" not in self.endpoint.lower()

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        response = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if "error" in response:
            raise RuntimeError(f"MCP tool {name} failed: {response['error']}")
        result = response.get("result", {})
        structured = result.get("structuredContent") or result.get("structured_content")
        if structured is not None:
            return structured.get("result", structured) if isinstance(structured, dict) else structured
        if "result" in result and not result.get("content"):
            return result["result"]
        content = result.get("content", [])
        texts = [str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("type") == "text"]
        media = [_compact_media_content(item, arguments or {}) for item in content if isinstance(item, dict) and item.get("type") in {"image", "audio"}]
        if media:
            payload: dict[str, Any] = {"media": media}
            if texts:
                payload["text"] = "\n".join(texts).strip()
            return payload
        return "\n".join(texts).strip()

    def list_tools(self) -> list[dict[str, Any]]:
        response = self._rpc("tools/list", {})
        if "error" in response:
            raise RuntimeError(f"MCP tools/list failed: {response['error']}")
        return response.get("result", {}).get("tools", [])

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._ensure_session()
        return self._send_request(method, params)

    def _ensure_session(self) -> None:
        if self._initialized:
            return
        with self._session_lock:
            if self._initialized:
                return
            response = self._send_request(
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "overseas-ads-agent", "version": "0.1.0"},
                },
            )
            if "error" in response:
                raise RuntimeError(f"MCP initialize failed: {response['error']}")
            result = response.get("result") if isinstance(response.get("result"), dict) else {}
            self._protocol_version = str(result.get("protocolVersion") or "2025-03-26")
            self._initialized = True
            self._send_request("notifications/initialized", {}, notification=True)

    def _send_request(self, method: str, params: dict[str, Any], notification: bool = False) -> dict[str, Any]:
        payload_data: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            payload_data["id"] = next(self._ids)
        payload = json.dumps(payload_data).encode("utf-8")
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if self._protocol_version:
            headers["MCP-Protocol-Version"] = self._protocol_version
        req = request.Request(self.endpoint, data=payload, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id") or ""
                if session_id:
                    self._session_id = session_id
                body = response.read().decode("utf-8")
                return _parse_rpc_response(body) if body.strip() else {}
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MCP HTTP error {exc.code}: {body}") from exc
        except Exception as exc:
            raise RuntimeError(f"MCP request failed: {exc}") from exc


class RemoteMcpGateway:
    name = "mcp"

    def __init__(self, client: MetaMcpClient | None = None, access_token: str = "") -> None:
        endpoint = remote_ads_mcp_endpoint()
        self.endpoint = endpoint
        self.official = "mcp.facebook.com" in endpoint.lower()
        self.access_token = access_token
        self.client = client or (MetaMcpClient(endpoint, remote_ads_mcp_token()) if endpoint else None)
        self.client_conversation_id = uuid4().hex[:20]
        self.advertiser_request = "Read Meta Ads account and performance data."

    def connection_status(self) -> dict[str, Any]:
        endpoint = remote_ads_mcp_endpoint()
        return {
            "platform": self.name,
            "provider": "meta_official_mcp" if self.official else "meta_ads_mcp",
            "configured": bool(endpoint),
            "read_enabled": bool(endpoint),
            "write_enabled": False,
            "endpoint_configured": bool(endpoint),
            "token_configured": bool(remote_ads_mcp_token() or self.access_token),
            "allowed_operations": [
                "read_adaccounts", "read_entities", "read_insights",
                "read_activity_logs", "read_datasets", "read_experiments",
            ],
            "note": "Official Meta Ads MCP." if self.official else "Third-party Meta Ads MCP adapter.",
        }

    def diagnostics(self) -> dict[str, Any]:
        status = self.connection_status()
        required = REQUIRED_OFFICIAL_META_MCP_TOOLS if self.official else REQUIRED_META_MCP_TOOLS
        optional = OPTIONAL_OFFICIAL_META_MCP_TOOLS if self.official else OPTIONAL_META_MCP_TOOLS
        if not self.client:
            return {
                **status, "reachable": False, "ready": False, "tool_count": 0, "tools": [],
                "required_tools": sorted(required), "optional_tools": sorted(optional),
                "missing_required_tools": sorted(required),
                "error": "ADS_MCP_ENDPOINT_URL is not configured.",
            }
        try:
            tools = self.client.list_tools()
        except RuntimeError as exc:
            return {
                **status, "reachable": False, "ready": False, "tool_count": 0, "tools": [],
                "required_tools": sorted(required), "optional_tools": sorted(optional),
                "missing_required_tools": sorted(required), "error": str(exc),
            }
        names = sorted({item.get("name", "") for item in tools if item.get("name")})
        missing = sorted(required.difference(names))
        return {
            **status, "reachable": True, "ready": not missing, "tool_count": len(names), "tools": names,
            "required_tools": sorted(required), "optional_tools": sorted(optional),
            "missing_required_tools": missing, "missing_optional_tools": sorted(optional.difference(names)), "error": "",
        }

    def list_accounts(self, limit: int = 100) -> list[dict[str, Any]]:
        if self.official:
            result = self._call("ads_get_ad_accounts", {"limit": limit, "show_suggested_actions": False})
            rows = result.get("ad_accounts", []) if isinstance(result, dict) else []
            return [
                {
                    "id": f"act_{item.get('ad_account_id')}", "account_id": str(item.get("ad_account_id") or ""),
                    "name": str(item.get("ad_account_name") or ""), "business_id": str(item.get("business_id") or ""),
                    "business_name": str(item.get("business_name") or ""), "account_status": item.get("account_status"),
                    "is_queryable": item.get("is_queryable"), "is_ads_mcp_enabled": item.get("is_ads_mcp_enabled"), "currency": "",
                }
                for item in rows if isinstance(item, dict) and item.get("ad_account_id")
            ]
        return _extract_records(self._call("get_ad_accounts", {"limit": limit, **self._access_token_arg()}))

    def account_snapshot(self, account_id: str, date_preset: str = "last_7d", limit: int = 50) -> dict[str, Any]:
        if self.official:
            accounts = self.list_accounts(limit=200)
            account = next((item for item in accounts if item.get("account_id") == _numeric_account_id(account_id)), {"id": account_id})
            return {"platform": self.name, "provider": "meta_official_mcp", "account_id": _numeric_account_id(account_id), "date_preset": date_preset, "account": account, "campaigns": self.list_campaigns(account_id=account_id, limit=limit), "insights": self.get_insights(account_id=account_id, date_preset=date_preset, level="campaign", limit=limit)}
        account = _normalize_account_id(account_id)
        common = self._access_token_arg()
        account_info = self._call("get_account_info", {"account_id": account, **common})
        return {"platform": self.name, "provider": "meta_ads_mcp", "account_id": account, "date_preset": date_preset, "account": _extract_object(account_info), "campaigns": self.list_campaigns(account_id=account, limit=limit), "insights": self.get_insights(account_id=account, date_preset=date_preset, level="campaign", limit=limit)}

    def list_campaigns(self, account_id: str, limit: int = 50) -> list[dict[str, Any]]:
        if self.official:
            return self._official_entities(account_id, "campaign", limit)
        return _extract_records(self._call("get_campaigns", {"account_id": _normalize_account_id(account_id), "limit": limit, **self._access_token_arg()}))

    def list_adsets(self, account_id: str, limit: int = 100, campaign_id: str = "") -> list[dict[str, Any]]:
        if self.official:
            rows = self._official_entities(account_id, "adset", limit)
            return [row for row in rows if not campaign_id or str(row.get("campaign_id") or "") == campaign_id]
        args = {"account_id": _normalize_account_id(account_id), "limit": limit, **self._access_token_arg()}
        if campaign_id:
            args["campaign_id"] = campaign_id
        return _extract_records(self._call("get_adsets", args))

    def list_ads(self, account_id: str, limit: int = 100) -> list[dict[str, Any]]:
        if self.official:
            return self._official_entities(account_id, "ad", limit)
        return _extract_records(self._call("get_ads", {"account_id": _normalize_account_id(account_id), "limit": limit, **self._access_token_arg()}))

    def list_creatives(self, account_id: str, limit: int = 100) -> list[dict[str, Any]]:
        if self.official:
            return _official_list(self._call("ads_get_creatives", {"ad_account_id": _numeric_account_id(account_id), "limit": min(limit, 100)}), "ad_creatives")
        creatives: list[dict[str, Any]] = []
        for ad in self.list_ads(account_id=account_id, limit=limit)[:limit]:
            ad_id = str(ad.get("id") or "")
            if not ad_id:
                continue
            try:
                creatives.extend(_extract_records(self._call("get_ad_creatives", {"ad_id": ad_id, **self._access_token_arg()})))
            except RuntimeError:
                continue
        return creatives[:limit]

    def get_insights(self, account_id: str, date_preset: str = "last_7d", level: str = "campaign", limit: int = 50, time_increment: str = "", breakdowns: list[str] | None = None, action_breakdowns: list[str] | None = None) -> list[dict[str, Any]]:
        if self.official:
            fields = ["id", "name", "amount_spent", "impressions", "clicks", "ctr", "cpc", "cpm", "reach", "frequency", "results", "cost_per_result", "purchase_roas"]
            args: dict[str, Any] = {"ad_account_id": _numeric_account_id(account_id), "level": "ad_account" if level == "account" else level, "date_preset": date_preset, "fields": fields, "limit": min(max(limit, 1), 1000)}
            if time_increment:
                args["time_increment"] = str(time_increment)
            if breakdowns:
                args["breakdowns"] = breakdowns
            return _official_list(self._call("ads_get_ad_entities", args), "ad_entities")
        args = {"account_id": _normalize_account_id(account_id), "time_range": date_preset, "level": level, "limit": limit, "compact": True, **self._access_token_arg()}
        if time_increment:
            args["time_increment"] = time_increment
        if breakdowns:
            args["breakdowns"] = breakdowns
        if action_breakdowns is not None:
            args["action_breakdowns"] = action_breakdowns
        return _extract_records(self._call("get_insights", args))

    def _official_entities(self, account_id: str, level: str, limit: int) -> list[dict[str, Any]]:
        fields = ["id", "name", "amount_spent", "impressions", "clicks", "ctr", "cpc", "cpm", "reach", "frequency", "results", "cost_per_result", "purchase_roas"]
        if level == "campaign":
            fields += ["status", "effective_status", "objective", "daily_budget", "lifetime_budget", "bid_strategy"]
        elif level == "adset":
            fields += ["campaign_id", "campaign_name", "status", "effective_status", "optimization_goal", "daily_budget", "lifetime_budget", "bid_strategy", "learning_stage_info"]
        elif level == "ad":
            fields += ["campaign_id", "campaign_name", "adset_id", "adset_name", "status", "effective_status", "creative_id"]
        result = self._call("ads_get_ad_entities", {"ad_account_id": _numeric_account_id(account_id), "level": level, "date_preset": "maximum", "fields": fields, "limit": min(max(limit, 1), 1000)})
        return _official_list(result, "ad_entities")

    def _call(self, tool: str, args: dict[str, Any]) -> Any:
        if not self.client:
            raise RuntimeError("ADS_MCP_ENDPOINT_URL is not configured.")
        request_args = dict(args)
        if self.official and tool.startswith("ads_"):
            request_args.setdefault("client_conversation_id", self.client_conversation_id)
            request_args.setdefault("advertiser_request", self.advertiser_request)
            request_args.setdefault("advertiser_job", "other")
        result = self.client.call_tool(tool, request_args)
        if isinstance(result, dict):
            conversation_id = result.get("client_conversation_id")
            if conversation_id:
                self.client_conversation_id = str(conversation_id)
        return result

    def _access_token_arg(self) -> dict[str, str]:
        if self.client and not getattr(self.client, "injects_access_token_argument", True):
            return {}
        token = self.access_token or meta_access_token()
        return {"access_token": token} if token else {}


class AutoAccountGateway:
    name = "meta"

    def __init__(self, local_gateway: MetaAccountGateway, mcp_gateway: RemoteMcpGateway) -> None:
        self.local_gateway = local_gateway
        self.mcp_gateway = mcp_gateway

    def connection_status(self) -> dict[str, Any]:
        mcp_status = self.mcp_gateway.connection_status()
        local_status = self.local_gateway.connection_status()
        selected = "mcp" if mcp_status.get("read_enabled") else "local_meta"
        return {
            "platform": self.name,
            "provider": f"auto:{selected}",
            "configured": bool(mcp_status.get("read_enabled") or local_status.get("read_enabled")),
            "read_enabled": bool(mcp_status.get("read_enabled") or local_status.get("read_enabled")),
            "write_enabled": False,
            "selected": selected,
            "candidates": [mcp_status, local_status],
        }

    def list_accounts(self, limit: int = 100) -> list[dict[str, Any]]:
        if self.mcp_gateway.connection_status().get("read_enabled"):
            try:
                return self.mcp_gateway.list_accounts(limit=limit)
            except RuntimeError:
                if not self.local_gateway.connection_status().get("read_enabled"):
                    raise
        return self.local_gateway.list_accounts(limit=limit)

    def account_snapshot(self, account_id: str, date_preset: str = "last_7d", limit: int = 50) -> dict[str, Any]:
        if self.mcp_gateway.connection_status().get("read_enabled"):
            try:
                return self.mcp_gateway.account_snapshot(account_id=account_id, date_preset=date_preset, limit=limit)
            except RuntimeError:
                if not self.local_gateway.connection_status().get("read_enabled"):
                    raise
        return self.local_gateway.account_snapshot(account_id=account_id, date_preset=date_preset, limit=limit)

    def list_campaigns(self, account_id: str, limit: int = 50) -> list[dict[str, Any]]:
        if self.mcp_gateway.connection_status().get("read_enabled"):
            try:
                return self.mcp_gateway.list_campaigns(account_id=account_id, limit=limit)
            except RuntimeError:
                if not self.local_gateway.connection_status().get("read_enabled"):
                    raise
        return self.local_gateway.list_campaigns(account_id=account_id, limit=limit)

    def list_adsets(self, account_id: str, limit: int = 100, campaign_id: str = "") -> list[dict[str, Any]]:
        if self.mcp_gateway.connection_status().get("read_enabled"):
            try:
                adsets = self.mcp_gateway.list_adsets(account_id=account_id, limit=limit, campaign_id=campaign_id)
                if adsets:
                    return adsets
            except RuntimeError:
                if not self.local_gateway.connection_status().get("read_enabled"):
                    raise
        return self.local_gateway.list_adsets(account_id=account_id, limit=limit, campaign_id=campaign_id)

    def list_ads(self, account_id: str, limit: int = 100) -> list[dict[str, Any]]:
        if self.mcp_gateway.connection_status().get("read_enabled"):
            try:
                ads = self.mcp_gateway.list_ads(account_id=account_id, limit=limit)
                if ads:
                    return ads
            except RuntimeError:
                if not self.local_gateway.connection_status().get("read_enabled"):
                    raise
        return self.local_gateway.list_ads(account_id=account_id, limit=limit)

    def list_creatives(self, account_id: str, limit: int = 100) -> list[dict[str, Any]]:
        if self.mcp_gateway.connection_status().get("read_enabled"):
            try:
                creatives = self.mcp_gateway.list_creatives(account_id=account_id, limit=limit)
                if creatives:
                    return creatives
            except RuntimeError:
                if not self.local_gateway.connection_status().get("read_enabled"):
                    raise
        return self.local_gateway.list_creatives(account_id=account_id, limit=limit)

    def get_insights(
        self,
        account_id: str,
        date_preset: str = "last_7d",
        level: str = "campaign",
        limit: int = 50,
        time_increment: str = "",
        breakdowns: list[str] | None = None,
        action_breakdowns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if self.mcp_gateway.connection_status().get("read_enabled"):
            try:
                return self.mcp_gateway.get_insights(
                    account_id=account_id,
                    date_preset=date_preset,
                    level=level,
                    limit=limit,
                    time_increment=time_increment,
                    breakdowns=breakdowns,
                    action_breakdowns=action_breakdowns,
                )
            except RuntimeError:
                if not self.local_gateway.connection_status().get("read_enabled"):
                    raise
        return self.local_gateway.get_insights(
            account_id=account_id,
            date_preset=date_preset,
            level=level,
            limit=limit,
            time_increment=time_increment,
            breakdowns=breakdowns,
            action_breakdowns=action_breakdowns,
        )


def connection_statuses(meta_provider: MetaAdsProvider) -> list[dict[str, Any]]:
    local_gateway = MetaAccountGateway(meta_provider)
    mcp_gateway = RemoteMcpGateway(access_token=meta_provider.access_token_for_requests())
    return [
        AutoAccountGateway(local_gateway, mcp_gateway).connection_status(),
        mcp_gateway.connection_status(),
        local_gateway.connection_status(),
    ]


def gateway_for(platform: str, meta_provider: MetaAdsProvider) -> AccountDataProvider:
    local_gateway = MetaAccountGateway(meta_provider)
    mcp_gateway = RemoteMcpGateway(access_token=meta_provider.access_token_for_requests())
    normalized = platform.strip().lower()
    if normalized in {"meta", "auto"}:
        preference = account_gateway_preference()
        if preference == "mcp":
            if not mcp_gateway.connection_status().get("read_enabled") and local_gateway.connection_status().get("read_enabled"):
                return local_gateway
            return AutoAccountGateway(local_gateway, mcp_gateway)
        if preference in {"local", "local_meta"}:
            return local_gateway
        return AutoAccountGateway(local_gateway, mcp_gateway)
    if normalized in {"mcp", "remote_mcp", "meta_mcp"}:
        return mcp_gateway
    if normalized in {"local", "local_meta"}:
        return local_gateway
    raise RuntimeError(f"Unsupported account data platform: {platform}")


def _normalize_account_id(account_id: str) -> str:
    value = account_id.strip()
    return value if value.startswith("act_") else f"act_{value}"


def _compact_media_content(item: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    data = str(item.get("data") or "")
    mime_type = str(item.get("mimeType") or item.get("mime_type") or "")
    estimate = int(len(data) * 3 / 4) if data else 0
    source = {
        key: str(value)
        for key, value in arguments.items()
        if key in {"ad_id", "video_id", "account_id", "image_hash"} and value
    }
    return {
        "type": str(item.get("type") or "media"),
        "mime_type": mime_type,
        "source": source,
        "data_omitted": True,
        "data_chars": len(data),
        "bytes_estimate": estimate,
        "note": "Raw media data is omitted from model context and trace.",
    }


def _numeric_account_id(account_id: str) -> str:
    return account_id.strip().removeprefix("act_")


def _official_list(result: Any, key: str) -> list[dict[str, Any]]:
    value = result.get(key) if isinstance(result, dict) else result
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _extract_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    records = _extract_records(value)
    return records[0] if records else {}


def _extract_records(value: Any) -> list[dict[str, Any]]:
    parsed = _parse_jsonish(value)
    if isinstance(parsed, dict):
        data = parsed.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(parsed.get("result"), list):
            return [item for item in parsed["result"] if isinstance(item, dict)]
        if parsed:
            return [parsed]
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _parse_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _parse_rpc_response(body: str) -> dict[str, Any]:
    text = body.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = _parse_sse_response(text)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"MCP response was not a JSON object: {str(parsed)[:200]}")
    return parsed


def _parse_sse_response(text: str) -> Any:
    events: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                events.append("\n".join(current))
                current = []
            continue
        if line.startswith("data:"):
            current.append(line.removeprefix("data:").strip())
    if current:
        events.append("\n".join(current))
    for event in reversed(events):
        try:
            return json.loads(event)
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"MCP response was neither JSON nor parseable SSE: {text[:200]}")
