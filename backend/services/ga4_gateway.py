from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from queue import Empty, Queue

from ..config import (
    ga4_credentials_path,
    ga4_default_property_id,
    ga4_project_id,
    ga4_request_timeout_seconds,
)


DATA_API = "https://analyticsdata.googleapis.com/v1beta"
ADMIN_API = "https://analyticsadmin.googleapis.com/v1beta"
READ_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
_PROPERTY_RE = re.compile(r"^[0-9]{1,20}$")
_DATE_RE = re.compile(r"^(today|yesterday|[0-9]{1,4}daysAgo|[0-9]{4}-[0-9]{2}-[0-9]{2})$", re.IGNORECASE)
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")


class Ga4GatewayError(RuntimeError):
    def __init__(self, message: str, *, code: str = "ga4_error", status_code: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class Ga4Gateway:
    """Bounded, read-only GA4 Admin/Data API gateway."""

    name = "google_analytics"

    def __init__(
        self,
        *,
        credentials_path: str = "",
        project_id: str = "",
        default_property_id: str = "",
        timeout_seconds: int | None = None,
        session: Any | None = None,
        credentials_factory: Any | None = None,
        access_token: str = "",
    ) -> None:
        self.credentials_path = credentials_path or ga4_credentials_path()
        self.project_id = project_id or ga4_project_id()
        self.default_property_id = _normalize_property_id(default_property_id or ga4_default_property_id(), required=False)
        self.timeout_seconds = max(5, int(timeout_seconds or ga4_request_timeout_seconds()))
        self.session = session or requests.Session()
        self.credentials_factory = credentials_factory
        self._access_token = access_token.strip()
        self._credentials: Any = None
        self._token_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self._access_token or (self.credentials_path and Path(self.credentials_path).expanduser().is_file()))

    def status(self) -> dict[str, Any]:
        return {
            "provider": "google_analytics",
            "configured": self.configured,
            "credentials_file_present": bool(self.credentials_path and Path(self.credentials_path).expanduser().is_file()),
            "project_id": self.project_id,
            "default_property_id": self.default_property_id,
            "read_only": True,
            "scope": READ_SCOPE,
            "data_api": DATA_API,
            "admin_api": ADMIN_API,
        }

    def execute_tool(self, name: str, arguments: dict[str, Any], *, timeout_seconds: float | None = None) -> dict[str, Any]:
        args = dict(arguments or {})
        timeout = min(self.timeout_seconds, max(1.0, float(timeout_seconds or self.timeout_seconds)))
        if name == "ga4_list_properties":
            return self.list_properties(page_size=int(args.get("page_size") or 200), timeout_seconds=timeout)
        if name == "ga4_get_property_details":
            return self.get_property_details(args.get("property_id"), timeout_seconds=timeout)
        if name == "ga4_list_data_streams":
            return self.list_data_streams(args.get("property_id"), timeout_seconds=timeout)
        if name == "ga4_list_key_events":
            return self.list_key_events(args.get("property_id"), timeout_seconds=timeout)
        if name == "ga4_list_google_ads_links":
            return self.list_google_ads_links(args.get("property_id"), timeout_seconds=timeout)
        if name == "ga4_get_metadata":
            return self.get_metadata(args.get("property_id"), timeout_seconds=timeout)
        if name == "ga4_run_report":
            return self.run_report(args, timeout_seconds=timeout)
        if name == "ga4_run_realtime_report":
            return self.run_realtime_report(args, timeout_seconds=timeout)
        if name == "ga4_run_funnel_report":
            return self.run_funnel_report(args, timeout_seconds=timeout)
        raise Ga4GatewayError(f"Unknown GA4 tool: {name}", code="ga4_unknown_tool")

    def list_properties(self, *, page_size: int = 200, timeout_seconds: float | None = None) -> dict[str, Any]:
        properties: list[dict[str, Any]] = []
        accounts: list[dict[str, Any]] = []
        token = ""
        for _ in range(20):
            params: dict[str, Any] = {"pageSize": max(1, min(int(page_size), 200))}
            if token:
                params["pageToken"] = token
            payload = self._request("GET", f"{ADMIN_API}/accountSummaries", params=params, timeout_seconds=timeout_seconds)
            for account in payload.get("accountSummaries") or []:
                if not isinstance(account, dict):
                    continue
                account_id = _short_id(account.get("account"))
                accounts.append({"account_id": account_id, "display_name": str(account.get("displayName") or "")})
                for prop in account.get("propertySummaries") or []:
                    if not isinstance(prop, dict):
                        continue
                    property_name = str(prop.get("property") or "")
                    properties.append(
                        {
                            "property_id": _short_id(property_name),
                            "property_resource": property_name,
                            "display_name": str(prop.get("displayName") or ""),
                            "property_type": str(prop.get("propertyType") or ""),
                            "parent_account_id": account_id,
                            "parent_account_name": str(account.get("displayName") or ""),
                        }
                    )
            token = str(payload.get("nextPageToken") or "")
            if not token:
                break
        return _result(
            "ga4_list_properties",
            {
                "account_count": len(accounts),
                "property_count": len(properties),
                "accounts": accounts,
                "properties": properties,
                "pagination_complete": not bool(token),
            },
            missing_data=[] if properties else ["No GA4 properties are visible to this service account."],
        )

    def get_property_details(self, property_id: Any = None, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        prop = self._property_resource(property_id)
        payload = self._request("GET", f"{ADMIN_API}/{prop}", timeout_seconds=timeout_seconds)
        return _result("ga4_get_property_details", _property_payload(payload))

    def list_data_streams(self, property_id: Any = None, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        prop = self._property_resource(property_id)
        payload = self._request("GET", f"{ADMIN_API}/{prop}/dataStreams", timeout_seconds=timeout_seconds)
        streams = payload.get("dataStreams") or []
        missing = [] if streams else ["No GA4 data stream is configured for this property."]
        return _result("ga4_list_data_streams", {"property_id": _short_id(prop), "data_streams": streams, "count": len(streams)}, missing_data=missing)

    def list_key_events(self, property_id: Any = None, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        prop = self._property_resource(property_id)
        payload = self._request("GET", f"{ADMIN_API}/{prop}/keyEvents", timeout_seconds=timeout_seconds)
        key_events = payload.get("keyEvents") or []
        missing = [] if key_events else ["No GA4 key events are configured for this property."]
        return _result("ga4_list_key_events", {"property_id": _short_id(prop), "key_events": key_events, "count": len(key_events)}, missing_data=missing)

    def list_google_ads_links(self, property_id: Any = None, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        prop = self._property_resource(property_id)
        payload = self._request("GET", f"{ADMIN_API}/{prop}/googleAdsLinks", timeout_seconds=timeout_seconds)
        links = payload.get("googleAdsLinks") or []
        missing = [] if links else ["No Google Ads link is configured for this GA4 property."]
        return _result("ga4_list_google_ads_links", {"property_id": _short_id(prop), "links": links, "count": len(links)}, missing_data=missing)

    def get_metadata(self, property_id: Any = None, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        prop = self._property_resource(property_id)
        payload = self._request("GET", f"{DATA_API}/{prop}/metadata", timeout_seconds=timeout_seconds)
        return _result("ga4_get_metadata", {"property_id": _short_id(prop), **payload})

    def run_report(self, args: dict[str, Any], *, timeout_seconds: float | None = None) -> dict[str, Any]:
        prop = self._property_resource(args.get("property_id"))
        date_ranges = _date_ranges(args)
        dimensions = _names(args.get("dimensions"), "dimensions", 8)
        metrics = _names(args.get("metrics"), "metrics", 12)
        if not metrics:
            raise Ga4GatewayError("ga4_run_report requires at least one metric.", code="ga4_invalid_arguments")
        body: dict[str, Any] = {
            "dateRanges": date_ranges,
            "dimensions": [{"name": item} for item in dimensions],
            "metrics": [{"name": item} for item in metrics],
            "limit": _bounded_int(args.get("limit"), default=100, minimum=1, maximum=10000),
            "offset": _bounded_int(args.get("offset"), default=0, minimum=0, maximum=1000000),
            "returnPropertyQuota": bool(args.get("return_property_quota", True)),
        }
        for key, api_key in (
            ("dimension_filter", "dimensionFilter"),
            ("metric_filter", "metricFilter"),
            ("cohort_spec", "cohortSpec"),
            ("comparisons", "comparisons"),
        ):
            value = args.get(key)
            if isinstance(value, (dict, list)) and value:
                body[api_key] = value
        if isinstance(args.get("order_bys"), list) and args["order_bys"]:
            body["orderBys"] = args["order_bys"][:10]
        if isinstance(args.get("metric_aggregations"), list) and args["metric_aggregations"]:
            body["metricAggregations"] = [str(item) for item in args["metric_aggregations"][:6]]
        if "keep_empty_rows" in args:
            body["keepEmptyRows"] = bool(args.get("keep_empty_rows"))
        payload = self._request("POST", f"{DATA_API}/{prop}:runReport", json_body=body, timeout_seconds=timeout_seconds)
        return _report_result("ga4_run_report", prop, date_ranges, body, payload)

    def run_realtime_report(self, args: dict[str, Any], *, timeout_seconds: float | None = None) -> dict[str, Any]:
        prop = self._property_resource(args.get("property_id"))
        dimensions = _names(args.get("dimensions"), "dimensions", 8)
        metrics = _names(args.get("metrics"), "metrics", 8)
        if not metrics:
            raise Ga4GatewayError("ga4_run_realtime_report requires at least one metric.", code="ga4_invalid_arguments")
        body: dict[str, Any] = {
            "dimensions": [{"name": item} for item in dimensions],
            "metrics": [{"name": item} for item in metrics],
            "limit": _bounded_int(args.get("limit"), default=100, minimum=1, maximum=10000),
            "returnPropertyQuota": bool(args.get("return_property_quota", True)),
        }
        if isinstance(args.get("dimension_filter"), dict) and args["dimension_filter"]:
            body["dimensionFilter"] = args["dimension_filter"]
        if isinstance(args.get("metric_filter"), dict) and args["metric_filter"]:
            body["metricFilter"] = args["metric_filter"]
        if isinstance(args.get("order_bys"), list) and args["order_bys"]:
            body["orderBys"] = args["order_bys"][:10]
        payload = self._request("POST", f"{DATA_API}/{prop}:runRealtimeReport", json_body=body, timeout_seconds=timeout_seconds)
        return _report_result("ga4_run_realtime_report", prop, [], body, payload)

    def run_funnel_report(self, args: dict[str, Any], *, timeout_seconds: float | None = None) -> dict[str, Any]:
        prop = self._property_resource(args.get("property_id"))
        date_ranges = _date_ranges(args)
        funnel = args.get("funnel")
        if not isinstance(funnel, dict) or not funnel.get("steps"):
            raise Ga4GatewayError("ga4_run_funnel_report requires funnel.steps.", code="ga4_invalid_arguments")
        body: dict[str, Any] = {"dateRanges": date_ranges, "funnel": funnel, "returnPropertyQuota": bool(args.get("return_property_quota", True))}
        if isinstance(args.get("funnel_breakdown"), dict):
            body["funnelBreakdown"] = args["funnel_breakdown"]
        if isinstance(args.get("funnel_next_action"), dict):
            body["funnelNextAction"] = args["funnel_next_action"]
        payload = self._request("POST", f"{DATA_API}/{prop}:runFunnelReport", json_body=body, timeout_seconds=timeout_seconds)
        return _report_result("ga4_run_funnel_report", prop, date_ranges, body, payload)

    def _property_resource(self, property_id: Any) -> str:
        normalized = _normalize_property_id(property_id or self.default_property_id, required=True)
        return f"properties/{normalized}"

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        token = self._get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        timeout = min(self.timeout_seconds, max(1.0, float(timeout_seconds or self.timeout_seconds)))
        try:
            response = self.session.request(method, url, headers=headers, params=params, json=json_body, timeout=timeout)
        except Exception as exc:
            raise Ga4GatewayError(f"GA4 request failed: {type(exc).__name__}: {exc}", code="ga4_network_error") from exc
        status = int(getattr(response, "status_code", 0) or 0)
        if status == 401 and self.credentials_path:
            with self._token_lock:
                self._access_token = ""
                self._credentials = None
            headers["Authorization"] = f"Bearer {self._get_access_token()}"
            response = self.session.request(method, url, headers=headers, params=params, json=json_body, timeout=timeout)
            status = int(getattr(response, "status_code", 0) or 0)
        if status < 200 or status >= 300:
            message = _api_error_message(response)
            code = "ga4_permission_denied" if status in {401, 403} else "ga4_api_error"
            raise Ga4GatewayError(f"GA4 API HTTP {status}: {message}", code=code, status_code=status)
        try:
            payload = response.json()
        except Exception as exc:
            raise Ga4GatewayError("GA4 API returned a non-JSON response.", code="ga4_invalid_response", status_code=status) from exc
        return payload if isinstance(payload, dict) else {"data": payload}

    def _get_access_token(self) -> str:
        if self._access_token and (self._credentials is None or getattr(self._credentials, "valid", False)):
            return self._access_token
        with self._token_lock:
            if self._access_token and (self._credentials is None or getattr(self._credentials, "valid", False)):
                return self._access_token
            if not self.credentials_path:
                raise Ga4GatewayError("GOOGLE_APPLICATION_CREDENTIALS is not configured.", code="ga4_not_configured")
            path = Path(self.credentials_path).expanduser()
            if not path.is_file():
                raise Ga4GatewayError("GA4 credentials file is missing.", code="ga4_not_configured")
            last_error: Exception | None = None
            for attempt in range(2):
                try:
                    if self.credentials_factory is not None:
                        credentials = self.credentials_factory(str(path), [READ_SCOPE])
                    else:
                        from google.oauth2 import service_account

                        credentials = service_account.Credentials.from_service_account_file(str(path), scopes=[READ_SCOPE])
                    from google.auth.transport.requests import Request

                    _refresh_with_timeout(credentials, Request(), timeout_seconds=self.timeout_seconds)
                    token = str(getattr(credentials, "token", "") or "")
                    if not token:
                        raise RuntimeError("empty access token")
                    self._credentials = credentials
                    self._access_token = token
                    return token
                except Exception as exc:
                    last_error = exc
                    if attempt < 1:
                        time.sleep(0.5)
            raise Ga4GatewayError(f"GA4 authentication failed: {type(last_error).__name__}", code="ga4_auth_failed") from last_error




def _refresh_with_timeout(credentials: Any, request: Any, *, timeout_seconds: float) -> None:
    result: Queue[tuple[str, Any]] = Queue(maxsize=1)

    def worker() -> None:
        try:
            credentials.refresh(request)
            result.put(("ok", None))
        except BaseException as exc:
            result.put(("error", exc))

    thread = threading.Thread(target=worker, name="ga4-token-refresh", daemon=True)
    thread.start()
    try:
        status, payload = result.get(timeout=max(1.0, float(timeout_seconds)))
    except Empty as exc:
        raise TimeoutError("GA4 token refresh timed out.") from exc
    if status == "error":
        raise payload


def _normalize_property_id(value: Any, *, required: bool) -> str:
    normalized = str(value or "").strip()
    if normalized.startswith("properties/"):
        normalized = normalized.split("/", 1)[1]
    if not normalized:
        if required:
            raise Ga4GatewayError("A numeric GA4 property_id is required.", code="ga4_property_required")
        return ""
    if not _PROPERTY_RE.fullmatch(normalized):
        raise Ga4GatewayError("GA4 property_id must be numeric, not a G- measurement ID.", code="ga4_invalid_property")
    return normalized


def _short_id(resource_name: Any) -> str:
    value = str(resource_name or "").strip()
    return value.rsplit("/", 1)[-1] if "/" in value else value


def _names(value: Any, label: str, maximum: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise Ga4GatewayError(f"{label} must be a list of API names.", code="ga4_invalid_arguments")
    names: list[str] = []
    for item in value:
        name = str(item or "").strip()
        if not _NAME_RE.fullmatch(name):
            raise Ga4GatewayError(f"Invalid GA4 {label} entry: {name}", code="ga4_invalid_arguments")
        if name not in names:
            names.append(name)
    if len(names) > maximum:
        raise Ga4GatewayError(f"At most {maximum} GA4 {label} are allowed per call.", code="ga4_invalid_arguments")
    return names


def _date_ranges(args: dict[str, Any]) -> list[dict[str, Any]]:
    start = str(args.get("start_date") or "").strip()
    end = str(args.get("end_date") or "").strip()
    if not start or not end:
        raise Ga4GatewayError("start_date and end_date are required.", code="ga4_invalid_arguments")
    ranges = [{"startDate": _date_value(start), "endDate": _date_value(end), "name": "current"}]
    comparison_start = str(args.get("comparison_start_date") or "").strip()
    comparison_end = str(args.get("comparison_end_date") or "").strip()
    if bool(comparison_start) != bool(comparison_end):
        raise Ga4GatewayError("comparison_start_date and comparison_end_date must be supplied together.", code="ga4_invalid_arguments")
    if comparison_start and comparison_end:
        ranges.append(
            {
                "startDate": _date_value(comparison_start),
                "endDate": _date_value(comparison_end),
                "name": "comparison",
            }
        )
    return ranges


def _date_value(value: str) -> str:
    if not _DATE_RE.fullmatch(value):
        raise Ga4GatewayError(f"Invalid GA4 date value: {value}", code="ga4_invalid_arguments")
    lowered = value.lower()
    if lowered in {"today", "yesterday"}:
        return lowered
    if lowered.endswith("daysago"):
        return f"{int(value[:-7])}daysAgo"
    return value


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        resolved = int(value if value is not None else default)
    except (TypeError, ValueError):
        resolved = default
    return max(minimum, min(resolved, maximum))


def _property_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "property_id": _short_id(payload.get("name")),
        "parent_account_id": _short_id(payload.get("parent") or payload.get("account")),
        "display_name": str(payload.get("displayName") or ""),
        "time_zone": str(payload.get("timeZone") or ""),
        "currency_code": str(payload.get("currencyCode") or ""),
        "service_level": str(payload.get("serviceLevel") or ""),
        "property_type": str(payload.get("propertyType") or ""),
        "industry_category": str(payload.get("industryCategory") or ""),
        "create_time": str(payload.get("createTime") or ""),
        "update_time": str(payload.get("updateTime") or ""),
    }


def _report_result(
    tool: str,
    property_resource: str,
    date_ranges: list[dict[str, Any]],
    request_body: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    row_count = int(payload.get("rowCount") or len(payload.get("rows") or []))
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    dimension_headers = [str(item.get("name") or "") for item in payload.get("dimensionHeaders") or [] if isinstance(item, dict)]
    metric_headers = [str(item.get("name") or "") for item in payload.get("metricHeaders") or [] if isinstance(item, dict)]
    missing_data: list[str] = []
    if row_count == 0:
        missing_data.append("GA4 returned zero report rows for the requested property and date window.")
    data = {
        "property_id": _short_id(property_resource),
        "time_zone": str(metadata.get("timeZone") or ""),
        "currency_code": str(metadata.get("currencyCode") or ""),
        "date_ranges": date_ranges,
        "dimension_headers": dimension_headers,
        "metric_headers": metric_headers,
        "row_count": row_count,
        "rows": payload.get("rows") or [],
        "totals": payload.get("totals") or [],
        "maximums": payload.get("maximums") or [],
        "minimums": payload.get("minimums") or [],
        "property_quota": payload.get("propertyQuota") or {},
        "sampling_metadatas": payload.get("samplingMetadatas") or [],
        "subject_to_thresholding": payload.get("subjectToThresholding"),
        "no_data": row_count == 0,
        "requested": {
            "dimensions": [str(item.get("name") or "") for item in request_body.get("dimensions") or []],
            "metrics": [str(item.get("name") or "") for item in request_body.get("metrics") or []],
            "limit": request_body.get("limit"),
            "offset": request_body.get("offset"),
        },
    }
    return _result(tool, data, missing_data=missing_data)


def _result(tool: str, data: dict[str, Any], *, missing_data: list[str] | None = None) -> dict[str, Any]:
    return {
        "tool": tool,
        "source": "google_analytics",
        "read_only": True,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        **data,
        "missing_data": missing_data or [],
    }


def _api_error_message(response: Any) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("status") or "").strip()
            if message:
                return message[:1000]
        if isinstance(error, str) and error.strip():
            return error.strip()[:1000]
    return str(getattr(response, "text", "") or "Unknown GA4 API error")[:1000]


__all__ = ["Ga4Gateway", "Ga4GatewayError", "DATA_API", "ADMIN_API", "READ_SCOPE"]
