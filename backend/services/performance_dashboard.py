from __future__ import annotations

import re
from typing import Any


ZH_AD = "\u5e7f\u544a"
ZH_ADSET = "\u5e7f\u544a\u7ec4"
ZH_CAMPAIGN = "\u5e7f\u544a\u7cfb\u5217"
ZH_PERFORMANCE = "\u8868\u73b0"
ZH_PAST = "\u8fc7\u53bb"
ZH_MONTH = "\u4e2a\u6708"
ZH_TWO_MONTHS = f"2 {ZH_MONTH}"
ZH_TWO_MONTHS_COMPACT = f"2{ZH_MONTH}"

CAMPAIGN_ID_RE = re.compile(r"(?:campaign[_\s-]?id|campaign_id)\s*[:=]\s*([A-Za-z0-9_]+)", re.IGNORECASE)
CAMPAIGN_QUOTED_RE = re.compile(
    r"(?:campaign|ad\s*campaign|\u5e7f\u544a\u7cfb\u5217)\s*[:=]?\s*[\"'\u201c\u201d\u300c\u300d]([^\"'\u201c\u201d\u300c\u300d]{2,100})[\"'\u201c\u201d\u300c\u300d]",
    re.IGNORECASE,
)
CAMPAIGN_COLON_RE = re.compile(
    r"(?:campaign|ad\s*campaign|\u5e7f\u544a\u7cfb\u5217)\s*[:=]\s*([^\n,;，。]{2,100})",
    re.IGNORECASE,
)
CAMPAIGN_UNQUOTED_RE = re.compile(
    r"(?:campaign|ad\s*campaign|\u5e7f\u544a\u7cfb\u5217)\s+([^\n,;，。]{2,100})",
    re.IGNORECASE,
)
CAMPAIGN_ADS_IN_RE = re.compile(
    r"(?:ads?|ad\s*sets?|performance(?:\s+history)?|insights)\s+"
    r"(?:in|under|within|for)\s+(?:the\s+)?(.{2,120}?)\s+(?:campaign|ad\s*campaign)\b",
    re.IGNORECASE,
)
CAMPAIGN_ZH_UNDER_RE = re.compile(
    r"(?:查看|读取|分析|审计)?\s*([^，。;\n]{2,100}?)\s*(?:campaign|\u5e7f\u544a\u7cfb\u5217)\s*(?:下|里|中|内|的)",
    re.IGNORECASE,
)
GENERIC_CAMPAIGN_WORDS = {
    "campaign",
    "campaigns",
    "ad campaign",
    ZH_CAMPAIGN,
}
CAMPAIGN_HINT_STOP_WORDS = {
    "last",
    "past",
    "previous",
    "recent",
    "performance",
    "dashboard",
    "report",
    "data",
    "ads",
    "ad",
    "under",
    "for",
    "of",
    ZH_PAST,
    "\u6700\u8fd1",
    "\u8fd1",
    ZH_PERFORMANCE,
    "\u6570\u636e",
    "\u62a5\u8868",
    ZH_AD,
    ZH_ADSET,
    "\u4e0b",
}


def parse_performance_query(message: str) -> dict[str, Any]:
    text = (message or "").strip()
    lower = text.lower()
    level = "campaign"
    if _has_any(lower, ["adset", "ad set"]) or ZH_ADSET in text:
        level = "adset"
    elif (
        _has_any(lower, ["ad-level", "ad level", "ads performance", "ad performance"])
        or ZH_AD in text
        or "\u5355\u5e7f\u544a" in text
        or "\u9010\u6761\u5e7f\u544a" in text
    ):
        level = "ad"

    date_preset = "last_30d"
    if (
        _has_any(lower, ["last 2 months", "past 2 months", "previous 2 months", "last two months", "past two months"])
        or ZH_TWO_MONTHS in text
        or ZH_TWO_MONTHS_COMPACT in text
        or "\u4e24\u4e2a\u6708" in text
    ):
        date_preset = "last_60d"
    if _has_any(lower, ["last 7", "past 7", "previous 7"]) or "\u8fd1 7 \u5929" in text or "\u8fd17\u5929" in text:
        date_preset = "last_7d"

    return {
        "date_preset": date_preset,
        "level": level,
        "campaign_hint": _campaign_hint(text),
    }


def build_performance_dashboard(
    account: dict[str, Any],
    campaigns: list[dict[str, Any]],
    insights: list[dict[str, Any]],
    date_preset: str,
    level: str = "ad",
    campaign_hint: str = "",
    ads: list[dict[str, Any]] | None = None,
    trend_insights: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    filtered_campaigns = _filter_campaigns(campaigns, campaign_hint)
    campaign_ids = {str(item.get("id") or item.get("campaign_id") or "") for item in filtered_campaigns}
    if campaign_hint and not filtered_campaigns:
        filtered_insights = []
    elif campaign_ids:
        filtered_insights = [item for item in insights if str(item.get("campaign_id") or "") in campaign_ids]
    else:
        filtered_insights = insights
    ad_metadata = _ad_metadata_by_id(ads or [])
    rows = [_normalize_row(item, level, ad_metadata) for item in filtered_insights]
    rows = sorted(rows, key=lambda item: item["spend"], reverse=True)
    totals = _totals(rows)
    rows = _attach_shares(rows, totals)
    return {
        "dashboard_type": "performance_dashboard",
        "account": account or {},
        "date_preset": date_preset,
        "level": level,
        "campaign_hint": campaign_hint,
        "matched_campaigns": filtered_campaigns,
        "summary": totals,
        "metric_cards": _metric_cards(totals, account.get("currency", "USD") if account else "USD"),
        "comparison_chart": _comparison_chart(rows),
        "spend_distribution": _spend_distribution(rows),
        "share_distribution": _share_distribution(rows),
        "creative_comparison": _creative_comparison(rows),
        "trend_chart": _trend_chart(trend_insights or insights),
        "anomaly_cards": _anomaly_cards(rows, totals),
        "entity_cards": rows[:24],
        "data_quality": _data_quality(rows, filtered_campaigns, campaign_hint),
        "next_actions": _next_actions(rows, totals),
    }


def _campaign_hint(message: str) -> str:
    for pattern in (
        CAMPAIGN_ID_RE,
        CAMPAIGN_QUOTED_RE,
        CAMPAIGN_COLON_RE,
        CAMPAIGN_ADS_IN_RE,
        CAMPAIGN_ZH_UNDER_RE,
        CAMPAIGN_UNQUOTED_RE,
    ):
        match = pattern.search(message)
        if not match:
            continue
        hint = _clean_campaign_hint(match.group(1))
        if hint:
            return hint
    quoted = re.findall(r"[\"'\u201c\u201d\u300c\u300d]([^\"'\u201c\u201d\u300c\u300d]{3,100})[\"'\u201c\u201d\u300c\u300d]", message)
    return _clean_campaign_hint(quoted[0]) if quoted else ""


def _clean_campaign_hint(value: str) -> str:
    text = (value or "").strip().strip(" \"'\u201c\u201d\u300c\u300d")
    text = _strip_campaign_hint_tail(text)
    if not text:
        return ""
    lowered = text.lower()
    if lowered in GENERIC_CAMPAIGN_WORDS:
        return ""
    first_token = re.split(r"\s+", lowered, maxsplit=1)[0]
    if first_token in CAMPAIGN_HINT_STOP_WORDS:
        return ""
    if ZH_PERFORMANCE in text and ZH_CAMPAIGN not in text:
        return ""
    return text


def _strip_campaign_hint_tail(value: str) -> str:
    text = (value or "").strip()
    stop_patterns = [
        r"\b(?:over|for|during|in)\s+(?:the\s+)?(?:last|past|previous|recent)\s+\d+\s+(?:days?|weeks?|months?).*$",
        r"\b(?:last|past|previous|recent)\s+\d+\s+(?:days?|weeks?|months?).*$",
        r"\b(?:performance|dashboard|report|data|insights?)\b.*$",
        r"(?:\u8fc7\u53bb|\u8fd1|最近)\s*\d+\s*(?:天|日|周|个月|月).*$",
        r"(?:\u8868\u73b0|\u6570\u636e|\u62a5\u8868|\u770b\u677f).*$",
        r"(?:下|里|中|内|的)\s*(?:\u5e7f\u544a|\u5e7f\u544a\u7ec4|\u8868\u73b0).*$",
    ]
    for pattern in stop_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
    return text.strip(" \"'\u201c\u201d\u300c\u300d:：-")


def _filter_campaigns(campaigns: list[dict[str, Any]], hint: str) -> list[dict[str, Any]]:
    if not hint:
        return campaigns
    needle = hint.lower()
    return [
        item for item in campaigns
        if needle in str(item.get("name", "")).lower() or needle in str(item.get("id", "")).lower()
    ]


def _normalize_row(row: dict[str, Any], level: str, ad_metadata: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    spend = _num(row.get("spend"))
    impressions = _num(row.get("impressions"))
    clicks = _num(row.get("clicks"))
    conversions = _action_count(row.get("actions", []), {"purchase", "lead", "complete_registration", "subscribe"})
    purchase_value = _roas_value(row.get("purchase_roas", []), spend)
    entity_id = row.get(f"{level}_id") or row.get("ad_id") or row.get("adset_id") or row.get("campaign_id") or ""
    entity_name = row.get(f"{level}_name") or row.get("ad_name") or row.get("adset_name") or row.get("campaign_name") or entity_id
    ad_meta = (ad_metadata or {}).get(str(row.get("ad_id") or ""))
    normalized = {
        "entity_id": str(entity_id),
        "entity_name": str(entity_name),
        "campaign_id": str(row.get("campaign_id") or ""),
        "campaign_name": str(row.get("campaign_name") or ""),
        "adset_id": str(row.get("adset_id") or ""),
        "adset_name": str(row.get("adset_name") or ""),
        "ad_id": str(row.get("ad_id") or ""),
        "ad_name": str(row.get("ad_name") or ""),
        "spend": round(spend, 2),
        "impressions": int(impressions),
        "clicks": int(clicks),
        "conversions": int(conversions),
        "purchase_value": round(purchase_value, 2),
        "ctr": clicks / impressions if impressions else 0,
        "cpc": spend / clicks if clicks else None,
        "cpm": spend / impressions * 1000 if impressions else None,
        "cpa": spend / conversions if conversions else None,
        "roas": purchase_value / spend if spend and purchase_value else None,
        "date_start": row.get("date_start", ""),
        "date_stop": row.get("date_stop", ""),
    }
    if ad_meta:
        normalized.update(ad_meta)
    return normalized


def _ad_metadata_by_id(ads: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for ad in ads:
        ad_id = str(ad.get("id") or "")
        if not ad_id:
            continue
        creative = ad.get("creative") if isinstance(ad.get("creative"), dict) else {}
        output[ad_id] = {
            "status": ad.get("status") or "",
            "effective_status": ad.get("effective_status") or "",
            "configured_status": ad.get("configured_status") or "",
            "creative_id": str(creative.get("id") or ""),
            "creative_name": creative.get("name") or "",
            "creative_title": creative.get("title") or "",
            "creative_body": creative.get("body") or "",
            "thumbnail_url": creative.get("thumbnail_url") or "",
            "image_url": creative.get("image_url") or "",
            "creative_preview_url": creative.get("thumbnail_url") or creative.get("image_url") or "",
            "object_story_id": creative.get("effective_object_story_id") or "",
        }
    return output


def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    spend = sum(item["spend"] for item in rows)
    impressions = sum(item["impressions"] for item in rows)
    clicks = sum(item["clicks"] for item in rows)
    conversions = sum(item["conversions"] for item in rows)
    purchase_value = sum(item["purchase_value"] for item in rows)
    return {
        "entity_count": len(rows),
        "spend": round(spend, 2),
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
        "purchase_value": round(purchase_value, 2),
        "ctr": clicks / impressions if impressions else 0,
        "cpc": spend / clicks if clicks else None,
        "cpm": spend / impressions * 1000 if impressions else None,
        "cpa": spend / conversions if conversions else None,
        "roas": purchase_value / spend if spend and purchase_value else None,
    }


def _attach_shares(rows: list[dict[str, Any]], totals: dict[str, Any]) -> list[dict[str, Any]]:
    spend = totals.get("spend") or 0
    clicks = totals.get("clicks") or 0
    conversions = totals.get("conversions") or 0
    output: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["spend_share"] = item["spend"] / spend if spend else 0
        item["click_share"] = item["clicks"] / clicks if clicks else 0
        item["conversion_share"] = item["conversions"] / conversions if conversions else 0
        output.append(item)
    return output


def _metric_cards(summary: dict[str, Any], currency: str) -> list[dict[str, Any]]:
    return [
        {"label": "Spend", "value": summary["spend"], "format": "money", "currency": currency},
        {"label": "Impressions", "value": summary["impressions"], "format": "number"},
        {"label": "Clicks", "value": summary["clicks"], "format": "number"},
        {"label": "CTR", "value": summary["ctr"], "format": "percent"},
        {"label": "CPC", "value": summary["cpc"], "format": "money", "currency": currency},
        {"label": "Conversions", "value": summary["conversions"], "format": "number"},
        {"label": "CPA", "value": summary["cpa"], "format": "money", "currency": currency},
        {"label": "ROAS", "value": summary["roas"], "format": "ratio"},
    ]


def _comparison_chart(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "label": item["entity_name"],
            "spend": item["spend"],
            "clicks": item["clicks"],
            "ctr": item["ctr"],
            "cpc": item["cpc"],
            "conversions": item["conversions"],
        }
        for item in rows[:12]
    ]


def _spend_distribution(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = sum(item["spend"] for item in rows)
    if total <= 0:
        return []
    return [
        {"label": item["entity_name"], "value": item["spend"], "share": item["spend"] / total}
        for item in rows[:8]
    ]


def _share_distribution(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "label": item["entity_name"],
            "entity_id": item["entity_id"],
            "spend_share": item.get("spend_share", 0),
            "click_share": item.get("click_share", 0),
            "conversion_share": item.get("conversion_share", 0),
        }
        for item in rows[:12]
    ]


def _creative_comparison(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        creative_id = row.get("creative_id") or row.get("ad_id") or row.get("entity_id")
        creative_name = row.get("creative_name") or row.get("creative_title") or row.get("ad_name") or row.get("entity_name")
        item = grouped.setdefault(
            str(creative_id),
            {
                "creative_id": str(creative_id),
                "creative_name": creative_name,
                "thumbnail_url": row.get("thumbnail_url") or row.get("creative_preview_url") or "",
                "spend": 0.0,
                "impressions": 0,
                "clicks": 0,
                "conversions": 0,
                "ad_count": 0,
            },
        )
        item["spend"] += row["spend"]
        item["impressions"] += row["impressions"]
        item["clicks"] += row["clicks"]
        item["conversions"] += row["conversions"]
        item["ad_count"] += 1
    output = []
    for item in grouped.values():
        impressions = item["impressions"]
        clicks = item["clicks"]
        spend = item["spend"]
        conversions = item["conversions"]
        item["spend"] = round(spend, 2)
        item["ctr"] = clicks / impressions if impressions else 0
        item["cpc"] = spend / clicks if clicks else None
        item["cpa"] = spend / conversions if conversions else None
        output.append(item)
    return sorted(output, key=lambda item: item["spend"], reverse=True)[:12]


def _trend_chart(insights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in insights:
        date_key = str(row.get("date_start") or row.get("date_stop") or "")
        if not date_key:
            continue
        item = grouped.setdefault(
            date_key,
            {"date": date_key, "spend": 0.0, "impressions": 0, "clicks": 0, "conversions": 0},
        )
        item["spend"] += _num(row.get("spend"))
        item["impressions"] += int(_num(row.get("impressions")))
        item["clicks"] += int(_num(row.get("clicks")))
        item["conversions"] += int(_action_count(row.get("actions", []), {"purchase", "lead", "complete_registration", "subscribe"}))
    output = []
    for item in grouped.values():
        impressions = item["impressions"]
        clicks = item["clicks"]
        spend = item["spend"]
        conversions = item["conversions"]
        item["spend"] = round(spend, 2)
        item["ctr"] = clicks / impressions if impressions else 0
        item["cpc"] = spend / clicks if clicks else None
        item["cpa"] = spend / conversions if conversions else None
        output.append(item)
    return sorted(output, key=lambda item: item["date"])[:90]


def _anomaly_cards(rows: list[dict[str, Any]], totals: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    avg_cpc = totals.get("cpc") or 0
    for row in rows:
        if row["spend"] > 0 and row["conversions"] == 0 and row.get("spend_share", 0) >= 0.05:
            cards.append(_anomaly("high_spend_no_conversion", "High spend / no conversion", row, "Spent budget but returned no conversion actions."))
        if row["impressions"] >= 500 and row["ctr"] < 0.005:
            cards.append(_anomaly("low_ctr", "Low CTR", row, "CTR is below 0.5%, suggesting weak creative or audience mismatch."))
        if avg_cpc and row.get("cpc") and row["cpc"] > avg_cpc * 1.5 and row["clicks"] >= 20:
            cards.append(_anomaly("high_cpc", "High CPC", row, "CPC is materially higher than the account average."))
        if row["impressions"] == 0 and row["spend"] == 0:
            cards.append(_anomaly("no_data", "No data", row, "No delivery data returned for this entity."))
    return cards[:16]


def _anomaly(kind: str, title: str, row: dict[str, Any], detail: str) -> dict[str, Any]:
    return {
        "type": kind,
        "title": title,
        "entity_id": row.get("entity_id"),
        "entity_name": row.get("entity_name"),
        "campaign_id": row.get("campaign_id"),
        "adset_id": row.get("adset_id"),
        "ad_id": row.get("ad_id"),
        "spend": row.get("spend"),
        "clicks": row.get("clicks"),
        "conversions": row.get("conversions"),
        "ctr": row.get("ctr"),
        "cpc": row.get("cpc"),
        "detail": detail,
    }


def _data_quality(rows: list[dict[str, Any]], campaigns: list[dict[str, Any]], hint: str) -> list[str]:
    notes: list[str] = []
    if hint and not campaigns:
        notes.append("No campaign matched the requested campaign hint.")
    if not rows:
        notes.append("No insights returned for the selected account, date range, and level.")
    if rows and not any(item["conversions"] for item in rows):
        notes.append("Conversion actions were not returned or are zero, so CPA and ROAS may be incomplete.")
    if rows and not any(item["roas"] is not None for item in rows):
        notes.append("Purchase value / ROAS data was not returned.")
    return notes


def _next_actions(rows: list[dict[str, Any]], summary: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if not rows:
        return [{"label": "Check account/date range", "detail": "No insight rows returned; verify permissions, campaign delivery, and date range."}]
    zero_conversion = [item for item in rows if item["spend"] > 0 and item["conversions"] == 0]
    if zero_conversion:
        actions.append({"label": "Investigate spend with no conversions", "detail": f"{len(zero_conversion)} entities spent budget without returned conversions."})
    low_ctr = [item for item in rows if item["impressions"] > 0 and item["ctr"] < 0.005]
    if low_ctr:
        actions.append({"label": "Review low CTR creatives", "detail": f"{len(low_ctr)} entities have CTR below 0.5%."})
    if summary["entity_count"] > 1:
        actions.append({"label": "Compare winners and losers", "detail": "Use the top spend and CTR/CPC comparison before drafting pause or scale actions."})
    return actions


def _has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _action_count(actions: Any, action_types: set[str]) -> float:
    if not isinstance(actions, list):
        return 0.0
    total = 0.0
    for action in actions:
        if isinstance(action, dict) and str(action.get("action_type", "")) in action_types:
            total += _num(action.get("value"))
    return total


def _roas_value(purchase_roas: Any, spend: float) -> float:
    if not isinstance(purchase_roas, list) or spend <= 0:
        return 0.0
    for item in purchase_roas:
        if isinstance(item, dict) and item.get("value") is not None:
            return _num(item.get("value")) * spend
    return 0.0
