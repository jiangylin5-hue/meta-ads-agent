import base64
from typing import Any
from urllib import parse
from datetime import date, timedelta

from ..config import (
    meta_access_token,
    meta_default_ad_account_id,
    meta_graph_api_version,
    meta_live_write_enabled,
)
from .http import get_json, post_form_json


class MetaAdsProvider:
    name = "meta_ads"

    def __init__(self, access_token: str | None = None) -> None:
        self.access_token = access_token

    def is_configured(self) -> bool:
        return bool(self._access_token())

    def limitation_message(self) -> str:
        return "\u672a\u914d\u7f6e META_ACCESS_TOKEN\uff0c\u65e0\u6cd5\u8bfb\u53d6 Meta \u5e7f\u544a\u8d26\u6237\u6570\u636e\u3002"

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.is_configured(),
            "graph_api_version": meta_graph_api_version(),
            "default_ad_account_id_configured": bool(meta_default_ad_account_id()),
            "live_publish_enabled": meta_live_write_enabled(),
            "allowed_operations": [
                "read_adaccounts",
                "read_campaigns",
                "read_insights",
                "read_assets",
                "upload_image_asset",
                "create_active_campaign",
                "create_active_adset",
                "create_active_creative",
                "create_active_ad",
            ],
        }

    def get_me(self) -> dict[str, Any]:
        return self._graph_get("me", {"fields": "id,name"})

    def list_permissions(self) -> list[dict[str, Any]]:
        data = self._graph_get("me/permissions", {})
        return data.get("data", [])

    def list_businesses(self, limit: int = 100) -> list[dict[str, Any]]:
        data = self._graph_get(
            "me/businesses",
            {
                "fields": "id,name",
                "limit": str(max(1, min(limit, 200))),
            },
        )
        return data.get("data", [])

    def list_ad_accounts(self, limit: int = 100) -> list[dict[str, Any]]:
        data = self._graph_get(
            "me/adaccounts",
            {
                "fields": "id,account_id,name,account_status,currency,timezone_name,business_name,amount_spent,balance",
                "limit": str(max(1, min(limit, 200))),
            },
        )
        return data.get("data", [])

    def list_campaigns(self, ad_account_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        account = self._normalize_ad_account_id(ad_account_id)
        data = self._graph_get(
            f"{account}/campaigns",
            {
                "fields": "id,name,status,effective_status,objective,buying_type,created_time,updated_time,daily_budget,lifetime_budget",
                "limit": str(max(1, min(limit, 100))),
            },
        )
        return data.get("data", [])

    def list_adsets(self, ad_account_id: str | None = None, limit: int = 100, campaign_id: str = "") -> list[dict[str, Any]]:
        account = self._normalize_ad_account_id(ad_account_id)
        params = {
            "fields": (
                "id,name,status,effective_status,configured_status,campaign_id,optimization_goal,"
                "billing_event,bid_strategy,daily_budget,lifetime_budget,start_time,end_time,targeting,"
                "promoted_object,is_dynamic_creative,created_time,updated_time"
            ),
            "limit": str(max(1, min(limit, 100))),
        }
        if campaign_id:
            params["filtering"] = _json_param([{"field": "campaign.id", "operator": "EQUAL", "value": campaign_id}])
        data = self._graph_get(f"{account}/adsets", params)
        return data.get("data", [])

    def list_ads(self, ad_account_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        account = self._normalize_ad_account_id(ad_account_id)
        data = self._graph_get(
            f"{account}/ads",
            {
                "fields": (
                    "id,name,status,effective_status,configured_status,campaign_id,adset_id,"
                    "creative{id,name,title,body,thumbnail_url,image_url,effective_object_story_id,object_story_spec}"
                ),
                "limit": str(max(1, min(limit, 100))),
            },
        )
        return data.get("data", [])

    def list_creatives(self, ad_account_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        account = self._normalize_ad_account_id(ad_account_id)
        data = self._graph_get(
            f"{account}/adcreatives",
            {
                "fields": (
                    "id,name,title,body,image_url,thumbnail_url,video_id,effective_object_story_id,"
                    "object_story_spec,asset_feed_spec,degrees_of_freedom_spec"
                ),
                "limit": str(max(1, min(limit, 100))),
            },
        )
        return data.get("data", [])

    def get_insights(
        self,
        ad_account_id: str | None = None,
        date_preset: str = "last_7d",
        level: str = "campaign",
        limit: int = 50,
        time_increment: str = "",
        breakdowns: list[str] | None = None,
        action_breakdowns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        account = self._normalize_ad_account_id(ad_account_id)
        params = {
            "fields": (
                "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,"
                "spend,impressions,clicks,ctr,cpc,cpm,actions,purchase_roas,date_start,date_stop"
            ),
            "level": level,
            "limit": str(max(1, min(limit, 100))),
        } | _date_query(date_preset)
        if time_increment:
            params["time_increment"] = str(time_increment)
        if breakdowns:
            params["breakdowns"] = ",".join(breakdowns)
        if action_breakdowns is not None:
            params["action_breakdowns"] = _json_param(action_breakdowns)
        data = self._graph_get(
            f"{account}/insights",
            params,
        )
        return data.get("data", [])

    def list_assets(self, ad_account_id: str, limit: int = 100) -> list[dict[str, Any]]:
        account = self._normalize_ad_account_id(ad_account_id)
        creatives = self._graph_get(
            f"{account}/adcreatives",
            {
                "fields": "id,name,title,body,image_url,thumbnail_url,object_story_spec,effective_object_story_id",
                "limit": str(max(1, min(limit, 100))),
            },
        ).get("data", [])
        adimages = self._graph_get(
            f"{account}/adimages",
            {
                "fields": "hash,name,url,permalink_url",
                "limit": str(max(1, min(limit, 100))),
            },
        ).get("data", [])
        return [
            {
                "id": f"creative_{item.get('id')}",
                "source": "existing_creative",
                "media_type": "image",
                "name": item.get("name") or item.get("title") or item.get("id", ""),
                "preview_url": item.get("thumbnail_url") or item.get("image_url") or "",
                "existing_creative_id": item.get("id", ""),
                "meta_asset_id": "",
                "validation_status": "valid",
            }
            for item in creatives
            if item.get("id")
        ] + [
            {
                "id": f"image_{item.get('hash')}",
                "source": "meta_library",
                "media_type": "image",
                "name": item.get("name") or item.get("hash", ""),
                "preview_url": item.get("url") or item.get("permalink_url") or "",
                "existing_creative_id": "",
                "meta_asset_id": item.get("hash", ""),
                "validation_status": "valid",
            }
            for item in adimages
            if item.get("hash")
        ]

    def upload_image_asset(self, ad_account_id: str, name: str, data_url: str) -> dict[str, Any]:
        account = self._normalize_ad_account_id(ad_account_id)
        image_bytes = _data_url_to_base64(data_url)
        if not image_bytes:
            raise RuntimeError("Image upload requires a base64 data URL.")
        data = self._graph_post(
            f"{account}/adimages",
            {
                "name": name,
                "bytes": image_bytes,
            },
        )
        images = data.get("images", {})
        first = next(iter(images.values()), {}) if isinstance(images, dict) else {}
        return {
            "hash": first.get("hash", ""),
            "url": first.get("url", ""),
            "raw": data,
        }

    def create_campaign(self, ad_account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        account = self._normalize_ad_account_id(ad_account_id)
        return self._graph_post(
            f"{account}/campaigns",
            {
                "name": payload["name"],
                "objective": payload.get("objective", "OUTCOME_TRAFFIC"),
                "status": payload.get("status", "ACTIVE"),
                "buying_type": "AUCTION",
                "special_ad_categories": "[]",
                "is_adset_budget_sharing_enabled": "false",
            },
        )

    def create_adset(self, ad_account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        account = self._normalize_ad_account_id(ad_account_id)
        data = {
            "name": payload["name"],
            "campaign_id": payload["campaign_id"],
            "status": payload.get("status", "ACTIVE"),
            "billing_event": payload.get("billing_event", "IMPRESSIONS"),
            "optimization_goal": payload.get("optimization_goal", "LINK_CLICKS"),
            "bid_strategy": payload.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP"),
            "daily_budget": str(payload.get("daily_budget") or 100),
            "targeting": _json_param(payload.get("targeting") or {}),
        }
        if payload.get("start_time"):
            data["start_time"] = payload["start_time"]
        if payload.get("end_time"):
            data["end_time"] = payload["end_time"]
        return self._graph_post(f"{account}/adsets", data)

    def create_creative(self, ad_account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        account = self._normalize_ad_account_id(ad_account_id)
        if payload.get("existing_creative_id"):
            return {"id": payload["existing_creative_id"], "reused": True}
        link_data: dict[str, Any] = {
            "link": payload["destination_url"],
            "message": payload["primary_text"],
            "name": payload["headline"],
        }
        if payload.get("description"):
            link_data["description"] = payload["description"]
        if payload.get("image_hash"):
            link_data["image_hash"] = payload["image_hash"]
        object_story_spec: dict[str, Any] = {
            "page_id": payload["page_id"],
            "link_data": link_data,
        }
        if payload.get("instagram_actor_id"):
            object_story_spec["instagram_actor_id"] = payload["instagram_actor_id"]
        return self._graph_post(
            f"{account}/adcreatives",
            {
                "name": payload["name"],
                "object_story_spec": _json_param(object_story_spec),
            },
        )

    def create_ad(self, ad_account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        account = self._normalize_ad_account_id(ad_account_id)
        return self._graph_post(
            f"{account}/ads",
            {
                "name": payload["name"],
                "adset_id": payload["adset_id"],
                "creative": _json_param({"creative_id": payload["creative_id"]}),
                "status": payload.get("status", "ACTIVE"),
            },
        )

    def _graph_post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        token = self._access_token()
        if not token:
            raise RuntimeError(self.limitation_message())
        url = f"https://graph.facebook.com/{meta_graph_api_version().strip('/')}/{path.lstrip('/')}"
        payload = {key: str(value) for key, value in data.items() if value is not None}
        payload["access_token"] = token
        return post_form_json(url, payload)

    def _graph_get(self, path: str, params: dict[str, str], include_token: bool = True) -> dict[str, Any]:
        token = self._access_token()
        if include_token and not token:
            raise RuntimeError(self.limitation_message())
        query = dict(params)
        if include_token:
            query["access_token"] = token
        url = f"https://graph.facebook.com/{meta_graph_api_version().strip('/')}/{path.lstrip('/')}?{parse.urlencode(query)}"
        return get_json(url)

    def _normalize_ad_account_id(self, ad_account_id: str | None) -> str:
        account = (ad_account_id or meta_default_ad_account_id()).strip()
        if not account:
            raise RuntimeError("未配置 META_AD_ACCOUNT_ID，也未在请求中提供 ad_account_id。")
        return account if account.startswith("act_") else f"act_{account}"

    def _access_token(self) -> str:
        return self.access_token or meta_access_token()

    def access_token_for_requests(self) -> str:
        return self._access_token()


def _data_url_to_base64(data_url: str) -> str:
    if not data_url:
        return ""
    if "," in data_url and data_url.split(",", 1)[0].startswith("data:"):
        encoded = data_url.split(",", 1)[1]
    else:
        encoded = data_url
    try:
        base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise RuntimeError("Image upload data is not valid base64.") from exc
    return encoded


def _json_param(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _date_query(date_preset: str) -> dict[str, str]:
    preset = (date_preset or "last_7d").strip()
    if preset in {"last_60d", "past_2_months", "last_2_months"}:
        stop = date.today()
        start = stop - timedelta(days=60)
        return {
            "time_range": _json_param({"since": start.isoformat(), "until": stop.isoformat()}),
        }
    return {"date_preset": preset}
