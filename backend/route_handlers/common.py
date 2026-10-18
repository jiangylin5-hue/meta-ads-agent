import json
from typing import Any

from fastapi import HTTPException

from ..integrations.meta_ads import MetaAdsProvider
from ..services.trace_service import get_trace


def _meta_runtime_exception(exc: RuntimeError) -> HTTPException:
    text = str(exc)
    if _is_meta_auth_error(text):
        return HTTPException(
            status_code=401,
            detail={
                "code": "meta_auth_required",
                "message": "Meta 授权已失效或 access token 无效，请重新配置 META_ACCESS_TOKEN 后再读取真实广告数据。",
                "action": "configure_meta_token",
                "provider_error": text[:700],
            },
        )
    return HTTPException(status_code=502, detail=f"Meta API 调用失败：{text}")


def _is_meta_auth_error(message: str) -> bool:
    text = (message or "").lower()
    return any(
        marker in text
        for marker in [
            "oauthexception",
            '"code":190',
            "code 190",
            "error validating access token",
            "access token",
            "meta_access_token",
            "session is invalid",
            "token has expired",
        ]
    )


def _meta_provider(state: dict | None = None) -> MetaAdsProvider:
    return MetaAdsProvider()


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def agent_trace_detail(trace_id: str) -> dict[str, Any]:
    return {"trace": get_trace(trace_id)}


__all__ = [name for name in globals() if not name.startswith("__")]