"""
MCP Server — Powered by the nutreoPak Meta Marketing API tools.

ALL 21 original tools from nutreoPak-meta-mcp are available under their
original names (returning formatted markdown for AI agents / direct use).

Additionally, 6 JSON-structured tools prefixed with 'saas_' return
structured dicts for the SaaS platform's frontend components.

Both sets of tools use the SAME nutreoPak helpers (_get, _post,
_extract_action, _roas_flag, minor_to_display, etc.) — zero duplication
of Meta Graph API logic.

Protocol: JSON-RPC 2.0 over HTTP on port 8080.
"""

import json
import hashlib
import logging
import inspect
import os

logger = logging.getLogger(__name__)
from datetime import date
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

import requests

# ── Import the nutreoPak MCP server (all 21 tools + helpers) ──────────────────
import meta_mcp

PORT = 8080
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("mcp-server")


# ── Aliases for nutreoPak helpers (used by SaaS tools below) ──────────────────

_get = meta_mcp._get
_post = meta_mcp._post
_extract_action = meta_mcp._extract_action
_roas_flag = meta_mcp._roas_flag
minor_to_display = meta_mcp.minor_to_display
DATE_PRESETS = meta_mcp.DATE_PRESETS
BASE_URL = meta_mcp.BASE_URL


# ═══════════════════════════════════════════════════════════════════════════════
# SaaS JSON Tools — structured dicts for the platform frontend
# ═══════════════════════════════════════════════════════════════════════════════

def _clean_act_id(ad_account_id: str) -> str:
    """Ensure a clean 'act_XXXXX' format — handles both 'act_123' and '123' inputs."""
    stripped = ad_account_id.removeprefix("act_")
    return f"act_{stripped}"


def _extract_results(actions: list) -> dict:
    """
    Extract both purchases and leads from Meta's actions array.
    Returns {"purchases": int, "leads": int, "results": int, "result_type": str}
    """
    purchases = 0
    leads = 0
    purchase_types = {"purchase", "offsite_conversion.fb_pixel_purchase"}
    lead_types = {"lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead"}
    for a in actions:
        at = a.get("action_type", "")
        val = int(float(a.get("value", 0)))
        if at in purchase_types:
            purchases += val
        elif at in lead_types:
            leads += val
    # Primary result: purchases win if any, otherwise leads
    if purchases > 0:
        return {"purchases": purchases, "leads": leads, "results": purchases, "result_type": "purchases"}
    elif leads > 0:
        return {"purchases": 0, "leads": leads, "results": leads, "result_type": "leads"}
    return {"purchases": 0, "leads": 0, "results": 0, "result_type": "none"}


def _dynamic_verdict(spend: float, roas: float, results: dict,
                     baselines: dict | None = None) -> str:
    """
    Dynamic verdict using account-specific historical baselines.
    Winning = 20% better than baseline, Losing = 30% worse.
    Falls back to sensible defaults when no baselines are provided.
    """
    purchases = results.get("purchases", 0)
    leads = results.get("leads", 0)

    bl = baselines or {}

    # Purchase campaigns: ROAS-based verdict
    if purchases > 0:
        avg_roas = bl.get("avg_roas")
        if avg_roas and avg_roas > 0:
            win = avg_roas * 1.20   # 20% above baseline
            lose = avg_roas * 0.70  # 30% below baseline
        else:
            win, lose = 3.0, 1.5    # absolute fallback
        if roas >= win: return "scale"
        if roas <= lose: return "underperforming"
        return "hold"

    # Lead campaigns: CPL-based verdict (lower is better)
    if leads > 0:
        cpl = spend / leads
        avg_cpl = bl.get("avg_cpl")
        if avg_cpl and avg_cpl > 0:
            win = avg_cpl * 0.80    # 20% below baseline = good
            lose = avg_cpl * 1.30   # 30% above baseline = bad
        else:
            win, lose = 10.0, 20.0  # absolute fallback
        if cpl <= win: return "scale"
        if cpl >= lose: return "underperforming"
        return "hold"

    # No results
    if spend >= 2000: return "kill"
    if spend > 0: return "no_results"
    return "no_data"


def saas_account_overview(access_token: str, ad_account_id: str) -> dict:
    """Account health snapshot with 30d performance — structured JSON."""
    act_id = _clean_act_id(ad_account_id)
    account = _get(
        access_token, act_id,
        params={"fields": "name,currency,timezone_name,account_status,amount_spent,spend_cap,balance"},
    )
    campaigns = _get(
        access_token, f"{act_id}/campaigns",
        params={
            "fields": "id,status",
            "filtering": '[{"field":"effective_status","operator":"IN","value":["ACTIVE"]}]',
            "limit": 100,
        },
    )

    STATUS_MAP = {
        1: "Active", 2: "Disabled", 3: "Unsettled",
        7: "Pending Risk Review", 9: "In Grace Period", 201: "Closed",
    }

    # 30d aggregated insights
    spend_30d = roas_30d = 0.0
    purchases_30d = leads_30d = results_30d = 0
    result_type_30d = "none"
    cost_per_result_30d = None
    try:
        ins = _get(
            access_token, f"{act_id}/insights",
            params={
                "fields": "spend,purchase_roas,actions,action_values,outbound_clicks,impressions",
                "date_preset": "last_30d",
            },
        )
        rows = ins.get("data", [])
        if rows:
            r = rows[0]
            spend_30d = float(r.get("spend", 0))
            rl = r.get("purchase_roas", [])
            roas_30d = float(rl[0].get("value", 0)) if rl else 0.0
            res = _extract_results(r.get("actions", []))
            purchases_30d = res["purchases"]
            leads_30d = res["leads"]
            results_30d = res["results"]
            result_type_30d = res["result_type"]
            if results_30d > 0:
                cost_per_result_30d = round(spend_30d / results_30d, 2)
    except Exception:
        pass

    return {
        "name": account.get("name", "N/A"),
        "status": STATUS_MAP.get(account.get("account_status", 0), "Unknown"),
        "currency": account.get("currency", "USD"),
        "timezone": account.get("timezone_name", "N/A"),
        "lifetime_spend": minor_to_display(int(account.get("amount_spent", 0))),
        "spend_cap": minor_to_display(int(account["spend_cap"])) if account.get("spend_cap") else None,
        "active_campaigns": len(campaigns.get("data", [])),
        "spend_30d": spend_30d,
        "roas_30d": roas_30d if purchases_30d > 0 else None,
        "purchases_30d": purchases_30d,
        "leads_30d": leads_30d,
        "results_30d": results_30d,
        "result_type_30d": result_type_30d,
        "cost_per_result_30d": cost_per_result_30d,
    }


def saas_list_campaigns(
    access_token: str, ad_account_id: str,
    status_filter: str = "all", limit: int = 25,
) -> dict:
    """List campaigns with status, budget, and 7d performance — structured JSON."""
    act_id = _clean_act_id(ad_account_id)
    limit = max(1, min(100, limit))
    params: dict = {
        "fields": "id,name,status,effective_status,objective,daily_budget,lifetime_budget,created_time",
        "limit": limit,
    }
    if status_filter != "all":
        ms = {"active": "ACTIVE", "paused": "PAUSED", "archived": "ARCHIVED"}.get(status_filter)
        if ms:
            params["filtering"] = f'[{{"field":"effective_status","operator":"IN","value":["{ms}"]}}]'

    data = _get(access_token, f"{act_id}/campaigns", params=params)
    campaigns_raw = data.get("data", [])

    currency = "USD"
    try:
        acc = _get(access_token, act_id, params={"fields": "currency"})
        currency = acc.get("currency", "USD")
    except ValueError:
        pass

    # Batch-fetch 7d insights
    ins_map: dict[str, dict] = {}
    try:
        ins = _get(
            access_token, f"{act_id}/insights",
            params={
                "fields": "campaign_id,spend,purchase_roas,actions,action_values,impressions,inline_link_click_ctr,outbound_clicks",
                "date_preset": "last_7d", "level": "campaign", "limit": 100,
            },
        )
        for r in ins.get("data", []):
            cid = r.get("campaign_id")
            rl = r.get("purchase_roas", [])
            roas = float(rl[0].get("value", 0)) if rl else 0.0
            res = _extract_results(r.get("actions", []))
            spend = float(r.get("spend", 0))
            cpr = round(spend / res["results"], 2) if res["results"] > 0 else None
            ins_map[cid] = {
                "spend_7d": spend,
                "roas_7d": roas if res["purchases"] > 0 else None,
                "purchases_7d": res["purchases"],
                "leads_7d": res["leads"],
                "results_7d": res["results"],
                "result_type_7d": res["result_type"],
                "cost_per_result_7d": cpr,
                "impressions_7d": int(r.get("impressions", 0)),
                "ctr_7d": float(r.get("inline_link_click_ctr", 0)),
            }
    except Exception:
        pass

    campaigns = []
    for c in campaigns_raw:
        cid = c.get("id")
        d, lt = c.get("daily_budget"), c.get("lifetime_budget")
        budget = minor_to_display(int(d)) if d else (minor_to_display(int(lt)) if lt else None)
        bt = "daily" if d else ("lifetime" if lt else "cbo")
        i = ins_map.get(cid, {})
        roas = i.get("roas_7d") or 0
        spend = i.get("spend_7d", 0)
        res = {
            "purchases": i.get("purchases_7d", 0),
            "leads": i.get("leads_7d", 0),
            "results": i.get("results_7d", 0),
        }
        verdict = _dynamic_verdict(spend, roas, res)
        campaigns.append({
            "id": cid, "name": c.get("name", "Unnamed"),
            "status": c.get("status"), "effective_status": c.get("effective_status"),
            "objective": c.get("objective", "N/A"),
            "budget": budget, "budget_type": bt,
            "created_time": c.get("created_time", "")[:10],
            "spend_7d": spend, "roas_7d": i.get("roas_7d"),
            "purchases_7d": res["purchases"],
            "leads_7d": res["leads"],
            "results_7d": res["results"],
            "result_type_7d": i.get("result_type_7d", "none"),
            "cost_per_result_7d": i.get("cost_per_result_7d"),
            "impressions_7d": i.get("impressions_7d", 0),
            "ctr_7d": i.get("ctr_7d", 0),
            "verdict": verdict,
        })

    return {
        "campaigns": campaigns, "currency": currency,
        "count": len(campaigns),
        "has_more": bool(data.get("paging", {}).get("next")),
    }


def saas_campaign_insights(
    access_token: str, campaign_id: str, date_preset: str = "last_7d",
) -> dict:
    """Detailed performance insights for a campaign — structured JSON."""
    preset = DATE_PRESETS.get(date_preset, "last_7d")
    params: dict = {
        "fields": ",".join([
            "campaign_name", "spend", "impressions", "reach", "clicks",
            "inline_link_clicks", "inline_link_click_ctr", "cpm", "cpc",
            "purchase_roas", "actions", "action_values", "cost_per_action_type",
            "frequency", "date_start", "date_stop",
        ]),
        "date_preset": preset, "level": "campaign",
    }
    data = _get(access_token, f"{campaign_id}/insights", params=params)
    rows = data.get("data", [])
    if not rows:
        return {"campaign_id": campaign_id, "date_preset": date_preset, "no_data": True}

    row = rows[0]
    spend = float(row.get("spend", 0))
    rl = row.get("purchase_roas", [])
    roas_raw = float(rl[0].get("value", 0)) if rl else 0.0
    actions = row.get("actions", [])
    avs = row.get("action_values", [])
    cpa_arr = row.get("cost_per_action_type", [])
    res = _extract_results(actions)

    # Dynamic CPA/CPL: purchases first, then leads
    cost_per_result = round(spend / res["results"], 2) if res["results"] > 0 else None
    # Only show ROAS if there are actual purchases
    roas = roas_raw if res["purchases"] > 0 else None

    return {
        "campaign_id": campaign_id,
        "campaign_name": row.get("campaign_name"),
        "date_preset": date_preset, "no_data": False,
        "date_start": row.get("date_start"), "date_stop": row.get("date_stop"),
        "spend": spend, "roas": roas,
        "impressions": int(row.get("impressions", 0)),
        "reach": int(row.get("reach", 0)),
        "clicks": int(row.get("clicks", 0)),
        "link_clicks": int(row.get("inline_link_clicks", 0)),
        "ctr": float(row.get("inline_link_click_ctr", 0)),
        "cpm": float(row.get("cpm", 0)),
        "cpc": float(row.get("cpc", 0)),
        "frequency": float(row.get("frequency", 0)),
        "purchases": res["purchases"],
        "leads": res["leads"],
        "results": res["results"],
        "result_type": res["result_type"],
        "cost_per_result": cost_per_result,
        "purchase_value": _extract_action(avs, "offsite_conversion.fb_pixel_purchase"),
        "cost_per_purchase": _extract_action(cpa_arr, "offsite_conversion.fb_pixel_purchase"),
        "add_to_cart": int(_extract_action(actions, "offsite_conversion.fb_pixel_add_to_cart")),
        "initiate_checkout": int(_extract_action(actions, "offsite_conversion.fb_pixel_initiate_checkout")),
    }


def saas_campaign_detail(
    access_token: str, campaign_id: str, date_preset: str = "last_7d",
) -> dict:
    """
    Full campaign detail: summary metrics, daily time-series, ads list,
    and breakdowns by age/gender/placement — structured JSON for the
    campaign detail page.
    """
    preset = DATE_PRESETS.get(date_preset, "last_7d")

    # ── 1. Summary metrics (reuse saas_campaign_insights) ────────────────
    summary = saas_campaign_insights(access_token, campaign_id, date_preset)

    # ── 2. Daily time-series for this campaign ───────────────────────────
    daily = []
    try:
        ts_data = _get(access_token, f"{campaign_id}/insights", params={
            "fields": "spend,impressions,clicks,inline_link_click_ctr,cpm,actions,purchase_roas,date_start",
            "date_preset": preset,
            "time_increment": 1,
            "limit": 90,
        })
        for row in ts_data.get("data", []):
            rl = row.get("purchase_roas", [])
            roas_raw = float(rl[0].get("value", 0)) if rl else 0.0
            res = _extract_results(row.get("actions", []))
            spend = float(row.get("spend", 0))
            cpr = round(spend / res["results"], 2) if res["results"] > 0 else None
            daily.append({
                "date": row.get("date_start"),
                "spend": spend,
                "impressions": int(row.get("impressions", 0)),
                "clicks": int(row.get("clicks", 0)),
                "ctr": float(row.get("inline_link_click_ctr", 0)),
                "cpm": float(row.get("cpm", 0)),
                "roas": roas_raw if res["purchases"] > 0 else None,
                "purchases": res["purchases"],
                "leads": res["leads"],
                "results": res["results"],
                "result_type": res["result_type"],
                "cost_per_result": cpr,
            })
    except Exception:
        pass

    # ── 3. Ads list (reuse saas_list_ads) ────────────────────────────────
    ads_data = saas_list_ads(access_token, campaign_id, date_preset)

    # ── 4. Breakdowns: age, gender, placement ────────────────────────────
    breakdowns = {}
    breakdown_fields = "spend,impressions,clicks,ctr,cpm,frequency,actions,cost_per_action_type"
    breakdowns_map = {
        "age": "age",
        "gender": "gender",
        "placement": "publisher_platform,platform_position",
    }
    for bk_name, bk_value in breakdowns_map.items():
        try:
            url = f"{BASE_URL}/{campaign_id}/insights"
            params = {
                "access_token": access_token,
                "fields": breakdown_fields,
                "date_preset": preset,
                "breakdowns": bk_value,
                "limit": 100,
            }
            resp = requests.get(url, params=params, timeout=30)
            data = resp.json()
            rows = []
            for r in data.get("data", []):
                actions = r.get("actions", [])
                res = _extract_results(actions)
                spend = round(float(r.get("spend", 0)), 2)
                cpr = round(spend / res["results"], 2) if res["results"] > 0 else None
                row = {
                    "spend": spend,
                    "impressions": int(r.get("impressions", 0)),
                    "clicks": int(r.get("clicks", 0)),
                    "ctr": round(float(r.get("ctr", 0)), 2),
                    "cpm": round(float(r.get("cpm", 0)), 2),
                    **res,
                    "cost_per_result": cpr,
                }
                if bk_name == "age":
                    row["age"] = r.get("age", "unknown")
                elif bk_name == "gender":
                    row["gender"] = r.get("gender", "unknown")
                else:
                    row["publisher_platform"] = r.get("publisher_platform", "unknown")
                    row["platform_position"] = r.get("platform_position", "unknown")
                rows.append(row)
            breakdowns[f"by_{bk_name}"] = rows
        except Exception:
            breakdowns[f"by_{bk_name}"] = []

    # ── 5. Pixel analytics ─────────────────────────────────────────────────
    pixel_section = _extract_campaign_pixel_data(access_token, campaign_id, preset)

    return {
        "summary": summary,
        "daily": daily,
        "ads": ads_data.get("ads", []),
        "breakdowns": breakdowns,
        "pixel": pixel_section,
    }


# All pixel event types we track
_PIXEL_EVENTS = [
    ("offsite_conversion.fb_pixel_purchase", "Purchase"),
    ("offsite_conversion.fb_pixel_add_to_cart", "AddToCart"),
    ("offsite_conversion.fb_pixel_initiate_checkout", "InitiateCheckout"),
    ("offsite_conversion.fb_pixel_view_content", "ViewContent"),
    ("offsite_conversion.fb_pixel_add_payment_info", "AddPaymentInfo"),
    ("offsite_conversion.fb_pixel_complete_registration", "CompleteRegistration"),
    ("offsite_conversion.fb_pixel_lead", "Lead"),
    ("offsite_conversion.fb_pixel_search", "Search"),
]


def _extract_pixel_events(actions: list, action_values: list | None = None, cost_per: list | None = None) -> list[dict]:
    """Extract all pixel conversion events from actions arrays."""
    events = []
    for action_type, label in _PIXEL_EVENTS:
        count = _extract_action(actions, action_type)
        if count > 0:
            ev: dict = {"event": label, "action_type": action_type, "count": int(count)}
            if action_values:
                ev["value"] = round(_extract_action(action_values, action_type), 2)
            if cost_per:
                ev["cost_per"] = round(_extract_action(cost_per, action_type), 2)
            events.append(ev)
    return events


def _extract_campaign_pixel_data(access_token: str, campaign_id: str, preset: str) -> dict | None:
    """Discover pixel from adsets and extract pixel conversion analytics."""
    try:
        # Discover pixel from adsets' promoted_object
        adsets_data = _get(access_token, f"{campaign_id}/adsets", params={
            "fields": "promoted_object",
            "limit": 10,
        })
        pixel_id = None
        for adset in adsets_data.get("data", []):
            po = adset.get("promoted_object", {})
            if po.get("pixel_id"):
                pixel_id = po["pixel_id"]
                break

        # Get campaign-level actions for pixel event extraction
        summary_actions = []
        summary_action_values = []
        summary_cost_per = []
        try:
            full_data = _get(access_token, f"{campaign_id}/insights", params={
                "fields": "actions,action_values,cost_per_action_type",
                "date_preset": preset,
                "level": "campaign",
            })
            if full_data.get("data"):
                r = full_data["data"][0]
                summary_actions = r.get("actions", [])
                summary_action_values = r.get("action_values", [])
                summary_cost_per = r.get("cost_per_action_type", [])
        except Exception:
            pass

        pixel_events = _extract_pixel_events(summary_actions, summary_action_values, summary_cost_per)

        if not pixel_id and not pixel_events:
            return None

        # Fetch pixel name if we have the ID
        pixel_name = None
        if pixel_id:
            try:
                px_data = _get(access_token, pixel_id, params={"fields": "name"})
                pixel_name = px_data.get("name")
            except Exception:
                pass

        # Daily pixel events time-series
        daily_pixel: list[dict] = []
        try:
            px_daily_data = _get(access_token, f"{campaign_id}/insights", params={
                "fields": "actions,action_values",
                "date_preset": preset,
                "time_increment": 1,
                "level": "campaign",
                "limit": 90,
            })
            for row in px_daily_data.get("data", []):
                acts = row.get("actions", [])
                avals = row.get("action_values", [])
                day_entry: dict = {"date": row.get("date_start", "")}
                has_any = False
                for action_type, label in _PIXEL_EVENTS:
                    cnt = int(_extract_action(acts, action_type))
                    val = round(_extract_action(avals, action_type), 2)
                    if cnt > 0:
                        has_any = True
                    day_entry[label] = cnt
                    day_entry[f"{label}_value"] = val
                if has_any:
                    daily_pixel.append(day_entry)
        except Exception:
            pass

        return {
            "pixel_id": pixel_id,
            "pixel_name": pixel_name,
            "events": pixel_events,
            "daily_events": daily_pixel,
        }
    except Exception:
        return None


def saas_list_ads(
    access_token: str, campaign_id: str,
    date_preset: str = "last_7d", status_filter: str = "all",
) -> dict:
    """List all ads in a campaign with per-ad performance — structured JSON."""
    preset = DATE_PRESETS.get(date_preset, "last_7d")
    params: dict = {
        "fields": "id,name,status,effective_status,creative{thumbnail_url}",
        "limit": 50,
    }
    if status_filter != "all":
        ms = {"active": "ACTIVE", "paused": "PAUSED"}.get(status_filter)
        if ms:
            params["filtering"] = f'[{{"field":"effective_status","operator":"IN","value":["{ms}"]}}]'

    data = _get(access_token, f"{campaign_id}/ads", params=params)

    ins_map: dict[str, dict] = {}
    try:
        ins_data = _get(access_token, f"{campaign_id}/insights", params={
            "fields": "ad_id,ad_name,spend,impressions,inline_link_click_ctr,purchase_roas,actions,action_values,cost_per_action_type,outbound_clicks",
            "date_preset": preset, "level": "ad",
        })
        for r in ins_data.get("data", []):
            aid = r.get("ad_id")
            rl = r.get("purchase_roas", [])
            roas_raw = float(rl[0].get("value", 0)) if rl else 0.0
            res = _extract_results(r.get("actions", []))
            spend = float(r.get("spend", 0))
            cpr = round(spend / res["results"], 2) if res["results"] > 0 else None
            ins_map[aid] = {
                "spend": spend,
                "impressions": int(r.get("impressions", 0)),
                "ctr": float(r.get("inline_link_click_ctr", 0)),
                "roas": roas_raw if res["purchases"] > 0 else None,
                "purchases": res["purchases"],
                "leads": res["leads"],
                "results": res["results"],
                "result_type": res["result_type"],
                "cost_per_result": cpr,
            }
    except Exception:
        pass

    ads = []
    for ad in data.get("data", []):
        aid = ad["id"]
        i = ins_map.get(aid, {})
        spend = i.get("spend", 0.0)
        roas = i.get("roas") or 0
        res = {
            "purchases": i.get("purchases", 0),
            "leads": i.get("leads", 0),
            "results": i.get("results", 0),
        }
        verdict = _dynamic_verdict(spend, roas, res)
        creative = ad.get("creative", {})
        thumb = creative.get("thumbnail_url") if isinstance(creative, dict) else None
        ads.append({
            "id": aid, "name": ad.get("name", "Unnamed"),
            "status": ad.get("status"), "effective_status": ad.get("effective_status"),
            "thumbnail_url": thumb,
            "spend": spend, "impressions": i.get("impressions", 0),
            "ctr": i.get("ctr", 0), "roas": i.get("roas"),
            "purchases": res["purchases"], "leads": res["leads"],
            "results": res["results"], "result_type": i.get("result_type", "none"),
            "cost_per_result": i.get("cost_per_result"),
            "verdict": verdict,
        })

    return {"ads": ads, "count": len(ads), "campaign_id": campaign_id, "date_preset": date_preset}


def saas_page_posts(page_access_token: str, page_id: str) -> dict:
    """Fetch recent Facebook Page posts with reach & engagement — structured JSON."""
    try:
        posts_data = _get(page_access_token, f"{page_id}/posts", params={
            "fields": "id,message,created_time,shares,full_picture,"
                      "likes.summary(true).limit(0),"
                      "comments.summary(true).limit(0),"
                      "reactions.summary(true).limit(0)",
            "limit": 10,
        })
    except ValueError as e:
        return {"error": str(e), "posts": [], "count": 0}

    posts = []
    for post in posts_data.get("data", []):
        pid = post.get("id")

        # Get counts from inline summaries (always available)
        likes = post.get("likes", {}).get("summary", {}).get("total_count", 0)
        comments = post.get("comments", {}).get("summary", {}).get("total_count", 0)
        reactions = post.get("reactions", {}).get("summary", {}).get("total_count", 0)
        shares = post.get("shares", {}).get("count", 0)

        # Try page-level insights for reach (may be unavailable for small pages)
        reach = 0
        try:
            insights = _get(page_access_token, f"{pid}/insights", params={
                "metric": "post_impressions_unique",
            })
            for m in insights.get("data", []):
                if m.get("name") == "post_impressions_unique":
                    vals = m.get("values", [{}])
                    reach = vals[0].get("value", 0) if vals else 0
        except (ValueError, Exception):
            pass

        posts.append({
            "id": pid, "message": (post.get("message") or "")[:200],
            "created_time": post.get("created_time"),
            "likes": likes,
            "comments": comments,
            "reactions": reactions,
            "shares": shares,
            "image_url": post.get("full_picture"),
            "reach": reach,
        })

    return {"posts": posts, "count": len(posts), "page_id": page_id}


# ═══════════════════════════════════════════════════════════════════════════════
# Tool Registry — ALL nutreoPak originals + SaaS JSON tools
# ═══════════════════════════════════════════════════════════════════════════════

TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _build_schema(func) -> dict:
    """Auto-generate JSON Schema from function signature."""
    sig = inspect.signature(func)
    properties = {}
    required = []
    for name, param in sig.parameters.items():
        ann = param.annotation
        ptype = TYPE_MAP.get(ann, "string") if ann != inspect.Parameter.empty else "string"
        prop: dict = {"type": ptype}
        if param.default != inspect.Parameter.empty:
            if param.default is not None:
                prop["default"] = param.default
        else:
            required.append(name)
        properties[name] = prop
    return {"type": "object", "properties": properties, "required": required}


# ── Original nutreoPak tools (all 21) ─────────────────────────────────────────
# These return formatted text/markdown. The server wraps results in the MCP
# content format: {"content": [{"type": "text", "text": "..."}]}

NUTREOP_TOOL_NAMES = [
    "get_user_ad_accounts",
    "get_ad_insights",
    "get_ad_pixel_details",
    "create_facebook_post",
    "get_page_analytics",
    "get_account_overview",
    "list_campaigns",
    "get_campaign_insights",
    "list_ad_sets",
    "list_ads",
    "get_daily_spend",
    "get_creative",
    "pause_entity",
    "enable_entity",
    "update_daily_budget",
    "list_automated_rules",
    "create_kill_rule",
    "create_scale_rule",
    "toggle_automated_rule",
    "delete_automated_rule",
    "create_meta_ad_campaign",
]

TOOLS_REGISTRY: dict[str, dict[str, Any]] = {}

for _name in NUTREOP_TOOL_NAMES:
    _func = getattr(meta_mcp, _name, None)
    if _func and callable(_func):
        _doc = (_func.__doc__ or "").strip()
        _desc = _doc.split("\n")[0] if _doc else _name
        TOOLS_REGISTRY[_name] = {
            "function": _func,
            "description": _desc,
            "inputSchema": _build_schema(_func),
            "returns": "text",
        }

log.info(f"Loaded {len(TOOLS_REGISTRY)} original nutreoPak tools")


def get_account_audit_data(access_token: str, ad_account_id: str, date_preset: str = "last_30d") -> dict:
    """Fetch ad-level performance data for account audit — returns structured JSON."""
    act_id = _clean_act_id(ad_account_id)
    data = _get(access_token, f"{act_id}/insights", {
        "level": "ad",
        "date_preset": date_preset,
        "fields": "ad_name,ad_id,spend,impressions,clicks,actions,cost_per_action_type,ctr",
        "limit": "200",
    })
    rows = data.get("data", [])

    cleaned = []
    for row in rows:
        actions = row.get("actions") or []
        res = _extract_results(actions)
        cost_per_action = row.get("cost_per_action_type") or []

        # Find cost-per for the dominant result type
        purchase_cpa = next(
            (float(c["value"]) for c in cost_per_action
             if c.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase")),
            None,
        )
        lead_cpa = next(
            (float(c["value"]) for c in cost_per_action
             if c.get("action_type") in ("lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead")),
            None,
        )
        spend = float(row.get("spend", 0))
        roas = round((res["purchases"] * (purchase_cpa or 0)) / spend, 2) if spend > 0 and purchase_cpa else None
        cost_per_result = round(spend / res["results"], 2) if res["results"] > 0 else None

        cleaned.append({
            "ad_id": row.get("ad_id"),
            "ad_name": row.get("ad_name"),
            "spend": spend,
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "ctr": float(row.get("ctr", 0)),
            "purchases": res["purchases"],
            "leads": res["leads"],
            "results": res["results"],
            "result_type": res["result_type"],
            "cost_per_purchase": purchase_cpa,
            "cost_per_lead": lead_cpa,
            "cost_per_result": cost_per_result,
            "roas": roas,
        })

    total_spend = sum(r["spend"] for r in cleaned)

    # Fetch audience demographics (age x gender breakdown)
    demographics = {}
    try:
        demo_data = _get(access_token, f"{act_id}/insights", {
            "date_preset": date_preset,
            "fields": "spend",
            "breakdowns": "age,gender",
            "limit": "100",
        })
        demo_rows = demo_data.get("data", [])
        if demo_rows:
            total_demo_spend = sum(float(r.get("spend", 0)) for r in demo_rows)
            age_groups: dict[str, float] = {}
            gender_split: dict[str, float] = {}
            for r in demo_rows:
                s = float(r.get("spend", 0))
                pct = round(s / total_demo_spend * 100, 1) if total_demo_spend > 0 else 0
                age = r.get("age", "unknown")
                gender = r.get("gender", "unknown")
                age_groups[age] = age_groups.get(age, 0) + pct
                gender_split[gender] = gender_split.get(gender, 0) + pct
            demographics = {
                "age_groups": {k: round(v, 1) for k, v in sorted(age_groups.items())},
                "gender": {k: round(v, 1) for k, v in sorted(gender_split.items())},
            }
    except Exception:
        pass

    total_results = sum(r["results"] for r in cleaned)
    total_leads = sum(r["leads"] for r in cleaned)
    total_purchases = sum(r["purchases"] for r in cleaned)
    # Determine dominant result type across all ads
    dominant_type = "leads" if total_leads > total_purchases else "purchases" if total_purchases > 0 else ("leads" if total_leads > 0 else "none")

    result = {
        "total_spend": round(total_spend, 2),
        "total_purchases": total_purchases,
        "total_leads": total_leads,
        "total_results": total_results,
        "dominant_result_type": dominant_type,
        "ad_count": len(cleaned),
        "ads": cleaned,
    }
    if demographics:
        result["demographics"] = demographics
    return result


# ── Market Research & Performance Insights tools ──────────────────────────────

_niche_cache: dict[str, dict] = {}  # key: "niche|YYYY-MM-DD" → result


_website_cache: dict[str, dict] = {}


def scrape_website(url: str, access_token: str = "") -> dict:
    """
    Scrape one or more website URLs using Tavily Extract API and return the
    raw content.  *url* may be a single URL string **or** a comma-separated
    list of URLs (e.g. "https://a.com, https://b.com/products").

    Each URL is cached daily.  Results are returned as:
      {"pages": [{"url": ..., "raw_content": ..., "content_length": ...}, ...],
       "url": <first-url>,  "raw_content": <first-page>,  "content_length": ...}

    The top-level url / raw_content / content_length keys keep backward
    compatibility with callers that only expect a single page.
    """
    urls = [u.strip() for u in url.split(",") if u.strip()]
    if not urls:
        return {"error": "No URL provided", "url": "", "raw_content": ""}

    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if not tavily_key:
        return {"error": "TAVILY_API_KEY not configured", "url": urls[0], "raw_content": ""}

    pages: list[dict] = []
    # Batch URLs into a single Tavily call (API supports up to 20)
    uncached_urls = []
    for u in urls:
        cache_key = f"{u.lower()}|{date.today().isoformat()}"
        if cache_key in _website_cache:
            log.info("scrape_website: cache hit for '%s'", u)
            pages.append(_website_cache[cache_key])
        else:
            uncached_urls.append(u)

    if uncached_urls:
        try:
            resp = requests.post("https://api.tavily.com/extract", json={
                "api_key": tavily_key,
                "urls": uncached_urls[:20],
            }, timeout=60)
            resp.raise_for_status()
            data = resp.json()

            for r in data.get("results", []):
                raw_content = r.get("raw_content", "")
                if len(raw_content) > 8000:
                    raw_content = raw_content[:8000] + "\n... [truncated]"
                page = {
                    "url": r.get("url", ""),
                    "raw_content": raw_content,
                    "content_length": len(raw_content),
                }
                cache_key = f"{page['url'].lower()}|{date.today().isoformat()}"
                _website_cache[cache_key] = page
                pages.append(page)
        except Exception as e:
            log.warning("Tavily extract failed for %s: %s", uncached_urls, e)
            for u in uncached_urls:
                pages.append({"url": u, "raw_content": "", "error": str(e)})

    # Backward-compatible top-level keys from first page
    first = pages[0] if pages else {"url": urls[0], "raw_content": "", "content_length": 0}
    return {
        "url": first.get("url", ""),
        "raw_content": first.get("raw_content", ""),
        "content_length": first.get("content_length", 0),
        "pages": pages,
    }


def research_niche_trends(niche: str, country: str = "US", access_token: str = "") -> dict:
    """Research current advertising trends for a niche — returns structured JSON."""
    # Guard: niche may arrive as a list from MCP client
    if isinstance(niche, list):
        niche = ", ".join(str(n) for n in niche) if niche else "general"
    cache_key = f"{niche.lower().strip()}|{date.today().isoformat()}"
    if cache_key in _niche_cache:
        log.info(f"research_niche_trends: cache hit for '{niche}'")
        return _niche_cache[cache_key]

    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if not tavily_key:
        return {"error": "TAVILY_API_KEY not configured", "trends": [], "top_formats": [], "audience_insights": [], "competitor_angles": []}

    queries = [
        f"{niche} advertising trends 2026",
        f"{niche} top performing ad formats social media",
    ]
    all_snippets: list[str] = []
    for q in queries:
        try:
            resp = requests.post("https://api.tavily.com/search", json={
                "query": q,
                "api_key": tavily_key,
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": True,
            }, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            # Tavily returns an AI-generated answer + individual results
            answer = data.get("answer", "")
            if answer:
                all_snippets.append(answer)
            for r in data.get("results", [])[:5]:
                content = r.get("content", "")
                if content:
                    all_snippets.append(content[:200])
        except Exception as e:
            log.warning(f"Tavily search failed for '{q}': {e}")

    # Structure the raw snippets into categories
    result = {
        "niche": niche,
        "country": country,
        "source": "tavily",
        "raw_insights": all_snippets[:10],
        "trends": [s for s in all_snippets[:4]],
        "top_formats": [s for s in all_snippets[4:7]],
        "audience_insights": [s for s in all_snippets[7:9]],
        "competitor_angles": [s for s in all_snippets[9:10]],
    }
    _niche_cache[cache_key] = result
    return result


def get_performance_insights(access_token: str, ad_account_id: str, date_preset: str = "last_30d") -> dict:
    """Analyze ad creative patterns — top/worst performers, CTA types, copy lengths — returns structured JSON."""
    act_id = _clean_act_id(ad_account_id)

    # Fetch ad-level insights
    data = _get(access_token, f"{act_id}/insights", {
        "level": "ad",
        "date_preset": date_preset,
        "fields": "ad_name,ad_id,spend,impressions,clicks,actions,cost_per_action_type,ctr",
        "limit": "200",
    })
    rows = data.get("data", [])

    # Fetch creative text for each ad
    creatives = {}
    try:
        ads_data = _get(access_token, f"{act_id}/ads", {
            "fields": "id,name,creative{body,title,link_url,call_to_action_type}",
            "limit": "200",
        })
        for ad in ads_data.get("data", []):
            creative = ad.get("creative", {})
            creatives[ad["id"]] = {
                "body": creative.get("body", ""),
                "title": creative.get("title", ""),
                "cta_type": creative.get("call_to_action_type", ""),
                "link_url": creative.get("link_url", ""),
            }
    except Exception as e:
        log.warning(f"Failed to fetch ad creatives: {e}")

    # Build structured ad records
    ads = []
    for row in rows:
        actions = row.get("actions") or []
        purchases = sum(
            int(a.get("value", 0))
            for a in actions
            if a.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase")
        )
        cost_per_action = row.get("cost_per_action_type") or []
        cpa = next(
            (float(c["value"]) for c in cost_per_action
             if c.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase")),
            None,
        )
        spend = float(row.get("spend", 0))
        revenue = purchases * (cpa or 0) if cpa else 0
        roas = round(revenue / spend, 2) if spend > 0 else 0

        ad_id = row.get("ad_id", "")
        creative = creatives.get(ad_id, {})

        ads.append({
            "ad_id": ad_id,
            "ad_name": row.get("ad_name", ""),
            "spend": spend,
            "ctr": float(row.get("ctr", 0)),
            "purchases": purchases,
            "cpa": cpa,
            "roas": roas,
            "headline": creative.get("title", ""),
            "body_snippet": (creative.get("body", "") or "")[:120],
            "body_length": len(creative.get("body", "") or ""),
            "cta_type": creative.get("cta_type", ""),
        })

    # Split into top/worst performers
    top_performers = sorted([a for a in ads if a["roas"] >= 2.0], key=lambda x: -x["roas"])[:5]
    worst_performers = sorted([a for a in ads if a["spend"] > 0 and a["roas"] < 1.5], key=lambda x: x["roas"])[:3]

    # Aggregate patterns from top performers
    cta_counts: dict[str, int] = {}
    body_lengths: list[int] = []
    headline_lengths: list[int] = []
    hooks: list[str] = []

    for a in top_performers:
        if a["cta_type"]:
            cta_counts[a["cta_type"]] = cta_counts.get(a["cta_type"], 0) + 1
        if a["body_length"] > 0:
            body_lengths.append(a["body_length"])
        if a["headline"]:
            headline_lengths.append(len(a["headline"]))
            hooks.append(a["headline"])

    avg_cpa = round(sum(a["cpa"] for a in ads if a["cpa"]) / max(len([a for a in ads if a["cpa"]]), 1), 2)
    avg_roas = round(sum(a["roas"] for a in ads if a["spend"] > 0) / max(len([a for a in ads if a["spend"] > 0]), 1), 2)

    return {
        "top_performers": [{"ad_name": a["ad_name"], "headline": a["headline"], "body_snippet": a["body_snippet"], "roas": a["roas"], "cpa": a["cpa"], "ctr": a["ctr"]} for a in top_performers],
        "worst_performers": [{"ad_name": a["ad_name"], "headline": a["headline"], "body_snippet": a["body_snippet"], "roas": a["roas"], "cpa": a["cpa"], "ctr": a["ctr"]} for a in worst_performers],
        "avg_cpa": avg_cpa,
        "avg_roas": avg_roas,
        "cta_types_ranked": sorted(cta_counts.items(), key=lambda x: -x[1]),
        "creative_patterns": {
            "hooks_that_work": hooks[:5],
            "avg_headline_length": round(sum(headline_lengths) / max(len(headline_lengths), 1)),
            "optimal_body_length_range": [min(body_lengths, default=0), max(body_lengths, default=0)],
        },
    }


# ── Targeting & Research tools ─────────────────────────────────────────────────

def validate_meta_interests(access_token: str, keywords_json: str) -> dict:
    """Validate keywords against Meta's ad interest taxonomy — returns matched interests with audience sizes."""
    import json as _json
    keywords = _json.loads(keywords_json) if isinstance(keywords_json, str) else keywords_json
    validated = []
    for kw in keywords[:15]:
        try:
            data = _get(access_token, "search", params={
                "type": "adinterest",
                "q": kw,
                "limit": 10,  # fetch more so we can pick the broadest
            })
            for item in data.get("data", []):
                # audience_size_upper_bound is more reliably returned than audience_size
                size = item.get("audience_size_upper_bound") or item.get("audience_size") or item.get("audience_size_lower_bound") or 0
                validated.append({
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "audience_size": size,
                    "topic": item.get("topic", ""),
                    "matched_keyword": kw,
                })
        except Exception as e:
            log.warning(f"Interest search failed for '{kw}': {e}")

    # Deduplicate by id, keeping largest audience_size
    by_id = {}
    for v in validated:
        vid = v["id"]
        if vid not in by_id or v["audience_size"] > by_id[vid]["audience_size"]:
            by_id[vid] = v

    # Sort by audience_size descending — broad topics first, niche pages last
    unique = sorted(by_id.values(), key=lambda x: x["audience_size"], reverse=True)

    # Blocklist: reject interests that are entertainment, alcohol, brands, etc.
    BLOCKED_TERMS = {
        "whisky", "whiskey", "vodka", "beer", "wine", "rum", "gin", "tequila",
        "cocktail", "bourbon", "brandy", "ale", "lager", "liquor", "liqueur",
        "musical", "movie", "film", "tv show", "television", "series", "album",
        "song", "band", "singer", "actor", "actress", "celebrity", "magazine",
        "novel", "book", "game", "video game", "anime", "manga",
    }

    def _is_blocked(name: str) -> bool:
        nl = name.lower()
        return any(term in nl for term in BLOCKED_TERMS)

    unique = [v for v in unique if not _is_blocked(v["name"])]

    # Per-keyword: keep only the BEST match — must contain the keyword in its name
    best_per_kw = {}
    for v in unique:
        kw = v["matched_keyword"].lower()
        name = v["name"].lower()
        name_matches = kw in name
        if kw not in best_per_kw:
            best_per_kw[kw] = (v, name_matches)
        else:
            prev, prev_matches = best_per_kw[kw]
            if (name_matches and not prev_matches) or \
               (name_matches == prev_matches and v["audience_size"] > prev["audience_size"]):
                best_per_kw[kw] = (v, name_matches)

    # Build result: best-per-keyword first
    result = [v for v, _ in best_per_kw.values()]
    # Then append remaining, but ONLY if their name contains their matched keyword
    for v in unique:
        if v not in result and v["matched_keyword"].lower() in v["name"].lower():
            result.append(v)

    return {"content": [{"type": "text", "text": _json.dumps(result)}]}


def search_meta_interests(access_token: str, keywords_json: str, target_country: str = "US") -> dict:
    """
    Search and validate culturally relevant Meta ad interests for a target country.

    Takes AI-suggested keywords and the target country ISO code, queries Meta's
    Graph API /search?type=adinterest for each keyword, and returns a clean array
    of valid Meta Interest objects with real IDs and audience sizes.

    Returns JSON: [{"id": "...", "name": "...", "audience_size": ...}, ...]
    """
    import json as _json
    keywords = _json.loads(keywords_json) if isinstance(keywords_json, str) else keywords_json

    # Cultural blocklist per region
    ISLAMIC_COUNTRIES = {"PK", "SA", "AE", "BD", "MY", "TR", "NG", "KE"}
    BLOCKED_CULTURAL = set()
    if target_country.upper() in ISLAMIC_COUNTRIES:
        BLOCKED_CULTURAL = {
            "whisky", "whiskey", "vodka", "beer", "wine", "rum", "gin", "tequila",
            "cocktail", "bourbon", "brandy", "ale", "lager", "liquor", "liqueur",
            "pork", "bacon", "ham", "sausage", "salami",
            "gambling", "casino", "betting", "poker",
        }

    # Universal blocklist (entertainment / irrelevant)
    BLOCKED_UNIVERSAL = {
        "musical", "movie", "film", "tv show", "television", "series", "album",
        "song", "band", "singer", "actor", "actress", "celebrity", "magazine",
        "novel", "book", "video game", "anime", "manga",
    }

    all_blocked = BLOCKED_CULTURAL | BLOCKED_UNIVERSAL

    def _is_blocked(name: str) -> bool:
        nl = name.lower()
        return any(term in nl for term in all_blocked)

    validated = []
    for kw in keywords[:10]:
        try:
            data = _get(access_token, "search", params={
                "type": "adinterest",
                "q": kw,
                "limit": 10,
            })
            for item in data.get("data", []):
                size = (
                    item.get("audience_size_upper_bound")
                    or item.get("audience_size")
                    or item.get("audience_size_lower_bound")
                    or 0
                )
                if size <= 0:
                    continue
                name = item.get("name", "")
                if _is_blocked(name):
                    continue
                validated.append({
                    "id": item.get("id"),
                    "name": name,
                    "audience_size": size,
                    "matched_keyword": kw,
                })
        except Exception as e:
            log.warning(f"search_meta_interests failed for '{kw}' (country={target_country}): {e}")

    # Deduplicate by id, keep largest audience_size
    by_id = {}
    for v in validated:
        vid = v["id"]
        if vid not in by_id or v["audience_size"] > by_id[vid]["audience_size"]:
            by_id[vid] = v

    # Sort broadest first, pick best per keyword
    unique = sorted(by_id.values(), key=lambda x: x["audience_size"], reverse=True)

    best_per_kw = {}
    for v in unique:
        kw = v["matched_keyword"].lower()
        name = v["name"].lower()
        name_matches = kw in name
        if kw not in best_per_kw:
            best_per_kw[kw] = (v, name_matches)
        else:
            prev, prev_matches = best_per_kw[kw]
            if (name_matches and not prev_matches) or \
               (name_matches == prev_matches and v["audience_size"] > prev["audience_size"]):
                best_per_kw[kw] = (v, name_matches)

    # Clean output: just id, name, audience_size
    result = []
    seen_ids = set()
    for v, _ in best_per_kw.values():
        if v["id"] not in seen_ids:
            result.append({"id": v["id"], "name": v["name"], "audience_size": v["audience_size"]})
            seen_ids.add(v["id"])

    log.info(f"search_meta_interests: country={target_country}, keywords={keywords}, found={len(result)} interests")
    return result


def resolve_geo_locations(access_token: str, cities_json: str, country_code: str = "PK") -> dict:
    """Resolve city names to Meta geo-location keys."""
    import json as _json
    cities = _json.loads(cities_json) if isinstance(cities_json, str) else cities_json
    geo_cities = []
    for city in cities[:10]:
        try:
            data = _get(access_token, "search", params={
                "type": "adgeolocation",
                "location_types": '["city"]',
                "q": city,
                "limit": 1,
            })
            for item in data.get("data", []):
                geo_cities.append({
                    "key": item.get("key"),
                    "name": item.get("name"),
                    "country_code": item.get("country_code", country_code),
                })
        except Exception as e:
            log.warning(f"Geo search failed for '{city}': {e}")
    result = {"countries": [country_code]}
    if geo_cities:
        result["cities"] = geo_cities
    return {"content": [{"type": "text", "text": _json.dumps(result)}]}


def fetch_competitor_ads(access_token: str, keywords_json: str, country_code: str = "PK") -> dict:
    """Search Meta Ad Library for competitor ads matching keywords."""
    import json as _json
    keywords = _json.loads(keywords_json) if isinstance(keywords_json, str) else keywords_json
    search_term = " ".join(keywords[:5])
    ads = []
    try:
        data = _get(access_token, "ads_archive", params={
            "search_terms": search_term,
            "ad_reached_countries": f'["{country_code}"]',
            "ad_active_status": "ACTIVE",
            "fields": "id,ad_creation_time,ad_creative_bodies,ad_creative_link_titles,page_name,ad_snapshot_url",
            "limit": 10,
        })
        for ad in data.get("data", []):
            bodies = ad.get("ad_creative_bodies", [])
            titles = ad.get("ad_creative_link_titles", [])
            ads.append({
                "id": ad.get("id"),
                "page_name": ad.get("page_name", "Unknown"),
                "created": ad.get("ad_creation_time", ""),
                "body": bodies[0] if bodies else "",
                "title": titles[0] if titles else "",
                "snapshot_url": ad.get("ad_snapshot_url", ""),
            })
    except Exception as e:
        log.warning(f"Ad Library search failed: {e}")
    return {"content": [{"type": "text", "text": _json.dumps({"ads": ads, "count": len(ads), "search_term": search_term})}]}


def fetch_ad_account_pixels(access_token: str, ad_account_id: str) -> dict:
    """List Meta Pixels available on an ad account."""
    act_id = _clean_act_id(ad_account_id)
    try:
        data = _get(access_token, f"{act_id}/adspixels", params={
            "fields": "id,name,creation_time,is_unavailable,last_fired_time",
        })
        pixels = []
        for px in data.get("data", []):
            pixels.append({
                "id": px.get("id"),
                "name": px.get("name"),
                "created": px.get("creation_time", ""),
                "is_unavailable": px.get("is_unavailable", False),
                "last_fired": px.get("last_fired_time"),
            })
        return {"pixels": pixels, "count": len(pixels)}
    except Exception as e:
        return {"pixels": [], "count": 0, "error": str(e)}


def fetch_pixel_performance(access_token: str, pixel_id: str, ad_account_id: str) -> dict:
    """Get Pixel conversion performance data."""
    act_id = _clean_act_id(ad_account_id)
    try:
        data = _get(access_token, f"{pixel_id}/stats", params={
            "aggregation": "event",
        })
        events = []
        for item in data.get("data", []):
            events.append({
                "event": item.get("event", ""),
                "count_today": item.get("count", 0),
                "count_last_7d": item.get("count_7d", 0),
            })
        return {"pixel_id": pixel_id, "events": events}
    except Exception as e:
        return {"pixel_id": pixel_id, "events": [], "error": str(e)}


def get_pixel_events(access_token: str, pixel_id: str) -> dict:
    """
    Fetch active conversion events recorded by a specific Meta Pixel.
    Hits /{pixel_id}/stats?aggregation=event — returns hourly buckets
    with nested event data. We aggregate across all buckets to get
    unique event names with total counts.
    """
    try:
        # Fetch all pages of stats
        totals: dict[str, int] = {}
        url_path = f"{pixel_id}/stats"
        params: dict = {"aggregation": "event", "limit": "100"}

        data = _get(access_token, url_path, params=params)
        for bucket in data.get("data", []):
            for entry in bucket.get("data", []):
                name = entry.get("value", "")
                count = int(entry.get("count", 0))
                if name:
                    totals[name] = totals.get(name, 0) + count

        events = [
            {"event": name, "count_7d": count}
            for name, count in totals.items()
            if count > 0
        ]
        events.sort(key=lambda e: e["count_7d"], reverse=True)
        return {"pixel_id": pixel_id, "events": events}
    except Exception as e:
        return {"pixel_id": pixel_id, "events": [], "error": str(e)}


def saas_time_series_insights(
    access_token: str, ad_account_id: str, date_preset: str = "last_30d",
) -> dict:
    """Get daily time-series performance data for charts — structured JSON."""
    act_id = _clean_act_id(ad_account_id)
    preset = DATE_PRESETS.get(date_preset, "last_30d")
    try:
        data = _get(access_token, f"{act_id}/insights", params={
            "fields": "spend,impressions,clicks,actions,purchase_roas,date_start",
            "date_preset": preset,
            "time_increment": 1,
            "limit": 90,
        })
        daily = []
        for row in data.get("data", []):
            rl = row.get("purchase_roas", [])
            roas_raw = float(rl[0].get("value", 0)) if rl else 0.0
            res = _extract_results(row.get("actions", []))
            daily.append({
                "date": row.get("date_start"),
                "spend": float(row.get("spend", 0)),
                "impressions": int(row.get("impressions", 0)),
                "clicks": int(row.get("clicks", 0)),
                "roas": roas_raw if res["purchases"] > 0 else None,
                "purchases": res["purchases"],
                "leads": res["leads"],
                "results": res["results"],
                "result_type": res["result_type"],
            })
        # Per-campaign breakdown (aggregated over the period)
        by_campaign = []
        try:
            camp_data = _get(access_token, f"{act_id}/insights", params={
                "fields": "campaign_id,campaign_name,spend,impressions,clicks,actions,purchase_roas,inline_link_click_ctr,reach,outbound_clicks",
                "date_preset": preset,
                "level": "campaign",
                "limit": 50,
            })
            for row in camp_data.get("data", []):
                rl = row.get("purchase_roas", [])
                roas_raw = float(rl[0].get("value", 0)) if rl else 0.0
                res = _extract_results(row.get("actions", []))
                spend = float(row.get("spend", 0))
                cpr = round(spend / res["results"], 2) if res["results"] > 0 else None
                by_campaign.append({
                    "id": row.get("campaign_id"),
                    "name": row.get("campaign_name", "Unnamed"),
                    "spend": spend,
                    "impressions": int(row.get("impressions", 0)),
                    "reach": int(row.get("reach", 0)),
                    "clicks": int(row.get("clicks", 0)),
                    "ctr": float(row.get("inline_link_click_ctr", 0)),
                    "roas": roas_raw if res["purchases"] > 0 else None,
                    "purchases": res["purchases"],
                    "leads": res["leads"],
                    "results": res["results"],
                    "result_type": res["result_type"],
                    "cost_per_result": cpr,
                })
        except Exception:
            pass

        return {"daily": daily, "by_campaign": by_campaign, "count": len(daily)}
    except Exception as e:
        return {"daily": [], "by_campaign": [], "count": 0, "error": str(e)}


def fetch_social_identities(access_token: str, ad_account_id: str = "") -> dict:
    """
    Fetch Facebook Pages linked to the user's account, along with any
    connected Instagram Business Account for each page.
    """
    try:
        pages = _get(
            access_token, "me/accounts",
            params={
                "fields": "id,name,access_token,instagram_business_account{id,username,profile_picture_url}",
                "limit": "25",
            },
        )
        page_list = pages.get("data", [])
        logger.info("fetch_social_identities: found %d pages", len(page_list))
        result = []
        for p in page_list:
            entry = {
                "page_id": p["id"],
                "page_name": p.get("name", ""),
                "instagram_actor_id": None,
                "instagram_username": None,
                "instagram_profile_pic": None,
            }
            ig = p.get("instagram_business_account")
            page_token = p.get("access_token", access_token)
            if ig:
                logger.info("Page %s: IG found via instagram_business_account", p["id"])
            if not ig:
                # Fallback A: re-query Page with page token
                try:
                    ig_resp = _get(
                        page_token, p["id"],
                        params={"fields": "instagram_business_account{id,username,profile_picture_url},connected_instagram_account{id,username,profile_picture_url}"},
                    )
                    ig = ig_resp.get("instagram_business_account") or ig_resp.get("connected_instagram_account")
                    if ig:
                        logger.info("Page %s: IG found via fallback A (connected_instagram_account)", p["id"])
                except Exception as e:
                    logger.warning("Page %s: fallback A failed: %s", p["id"], e)
            if not ig:
                # Fallback A2: page_backed_instagram_accounts edge (works for
                # IG accounts connected at Page level even without Business type)
                try:
                    pbia = _get(
                        page_token, f"{p['id']}/page_backed_instagram_accounts",
                        params={"fields": "id,username,profile_picture_url"},
                    )
                    pbia_list = pbia.get("data", [])
                    if pbia_list:
                        ig = pbia_list[0]
                        logger.info("Page %s: IG found via fallback A2 (page_backed_instagram_accounts) data=%s", p["id"], ig)
                        # This endpoint may not return username — fetch it via user token
                        if ig.get("id") and not ig.get("username"):
                            try:
                                ig_detail = _get(access_token, ig["id"], params={"fields": "id,username,name,profile_picture_url"})
                                ig["username"] = ig_detail.get("username") or ig_detail.get("name") or ""
                                if ig_detail.get("profile_picture_url"):
                                    ig["profile_picture_url"] = ig_detail["profile_picture_url"]
                                logger.info("Page %s: fetched IG username=%s", p["id"], ig.get("username"))
                            except Exception as e2:
                                logger.warning("Page %s: failed to fetch IG username: %s", p["id"], e2)
                    else:
                        logger.info("Page %s: fallback A2 returned empty list", p["id"])
                except Exception as e:
                    logger.warning("Page %s: fallback A2 failed: %s", p["id"], e)
            if ig:
                entry["instagram_actor_id"] = ig.get("id")
                entry["instagram_username"] = ig.get("username")
                entry["instagram_profile_pic"] = ig.get("profile_picture_url")
            else:
                logger.info("Page %s: no IG account found after all page-level fallbacks", p["id"])
            result.append(entry)
        # Fallback B: if no Page had an IG linked, try the ad account's
        # instagram_accounts edge (works when IG is connected at Business
        # Manager level rather than Page level)
        if ad_account_id and not any(r["instagram_actor_id"] for r in result):
            try:
                act_id = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"
                ig_accounts = _get(
                    access_token, f"{act_id}/instagram_accounts",
                    params={"fields": "id,username,profile_pic"},
                )
                ig_list = ig_accounts.get("data", [])
                logger.info("Fallback B (ad account IG): found %d accounts", len(ig_list))
                if ig_list and result:
                    # Attach the first IG account to the first Page
                    ig = ig_list[0]
                    result[0]["instagram_actor_id"] = ig.get("id")
                    result[0]["instagram_username"] = ig.get("username")
                    result[0]["instagram_profile_pic"] = ig.get("profile_pic")
            except Exception as e:
                logger.warning("Fallback B failed: %s", e)

        return {"pages": result, "count": len(result)}
    except Exception as e:
        return {"pages": [], "count": 0, "error": str(e)}


def publish_page_photo(page_id: str, image_url: str, message: str, access_token: str) -> dict:
    """
    Publish a photo post to a Facebook Page. Returns the post_id.

    This creates a real, published Page post that can then be used as
    an ad creative via object_story_id — bypassing dark post restrictions
    in Development Mode apps.
    """
    import base64 as _b64

    try:
        # Handle data URIs: upload as multipart file
        if image_url.startswith("data:"):
            b64_data = image_url.split(",", 1)[1] if "," in image_url else ""
            img_bytes = _b64.b64decode(b64_data)
            # Use multipart upload for raw bytes
            url = f"{BASE_URL}/{page_id}/photos"
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                files={"source": ("ad_image.png", img_bytes, "image/png")},
                data={"message": message, "published": "true"},
                timeout=60,
            )
            data = resp.json()
        else:
            # Regular URL: pass url param, Meta downloads it
            data = _post(access_token, f"{page_id}/photos", {
                "url": image_url,
                "message": message,
                "published": True,
            })

        post_id = data.get("post_id") or data.get("id")
        if not post_id:
            return {"error": "No post_id returned", "raw": data}

        print(f"=== PAGE PHOTO PUBLISHED === post_id={post_id}", flush=True)
        return {"post_id": post_id}
    except Exception as e:
        return {"error": f"Page photo publish failed: {e}"}


def upload_ad_image(access_token: str, ad_account_id: str, image_url: str) -> dict:
    """
    Upload an image to a Meta ad account and return its hash.

    Accepts either a regular URL (https://...) or a base64 data URI
    (data:image/...;base64,...). Returns {"image_hash": "<hash>"}.
    """
    import base64 as _b64
    import json as _json
    act_id = _clean_act_id(ad_account_id)

    try:
        if image_url.startswith("data:"):
            # data URI: extract the base64 portion after the comma
            b64 = image_url.split(",", 1)[1] if "," in image_url else ""
        else:
            # Regular URL: download then encode
            img_resp = requests.get(image_url, timeout=30)
            img_resp.raise_for_status()
            b64 = _b64.b64encode(img_resp.content).decode()

        if not b64:
            return {"error": "Could not extract image bytes"}

        upload = _post(access_token, f"{act_id}/adimages", {"bytes": b64})
        images = upload.get("images", {})
        if images:
            first_key = list(images.keys())[0]
            image_hash = images[first_key].get("hash")
            return {"image_hash": image_hash}
        return {"error": "Meta returned no image hash", "raw": upload}
    except Exception as e:
        return {"error": f"Image upload failed: {e}"}


def upload_ad_video(access_token: str, ad_account_id: str, video_url: str) -> dict:
    """
    Upload a video to a Meta ad account.
    For local paths (/uploads/...) uses binary multipart upload.
    For remote URLs uses Meta's file_url fetch.
    Returns the video_id for use in ad creatives.
    """
    import time as _time
    act_id = _clean_act_id(ad_account_id)
    video_name = f"AI Video — {_time.strftime('%Y%m%d_%H%M%S')}"

    # Detect local file paths and upload binary via multipart
    local_path = None
    if video_url.startswith("/uploads/files/"):
        # URL: /uploads/files/{user_id}/xxx.mp4 → disk: /shared-uploads/{user_id}/xxx.mp4
        local_path = "/shared-uploads/" + video_url[len("/uploads/files/"):]
    elif video_url.startswith("/uploads/"):
        local_path = "/shared-uploads/" + video_url[len("/uploads/"):]
    elif video_url.startswith("/shared-uploads/"):
        local_path = video_url

    try:
        if local_path and os.path.isfile(local_path):
            # Binary multipart upload — Meta can't fetch local Docker paths
            log.info(f"upload_ad_video: binary upload from {local_path}")
            url = f"{BASE_URL}/{act_id}/advideos"
            with open(local_path, "rb") as f:
                resp = requests.post(
                    url,
                    params={"access_token": access_token},
                    files={"source": (os.path.basename(local_path), f, "video/mp4")},
                    data={"name": video_name},
                    timeout=120,
                )
            result = resp.json()
            if "error" in result:
                log.error(f"upload_ad_video binary upload error: {result['error']}")
                return {"error": f"Video upload failed: {_parse_meta_error(result['error'])}"}
        else:
            # Remote URL — let Meta fetch it
            result = _post(access_token, f"{act_id}/advideos", {
                "file_url": video_url,
                "name": video_name,
            })

        video_id = result.get("id")
        if not video_id:
            return {"error": "Video upload failed — no ID returned", "raw": result}
        return {
            "video_id": video_id,
            "status": "processing",
            "message": "Video uploaded. Meta is processing it — this may take a few minutes.",
        }
    except Exception as e:
        return {"error": f"Video upload failed: {e}"}


# ── Custom & Lookalike Audience Tools ─────────────────────────────────────────

def _normalize_and_hash(value: str, field_type: str) -> str:
    """Normalize and SHA-256 hash PII data per Meta's requirements."""
    value = value.strip().lower()
    if field_type == "email":
        # Remove dots from local part for gmail normalization
        pass  # just lowercase + strip is sufficient per Meta docs
    elif field_type == "phone":
        # Must include country code, digits only
        value = ''.join(c for c in value if c.isdigit() or c == '+')
        if not value.startswith('+'):
            value = '+' + value
        value = value.replace('+', '')
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def create_custom_audience_from_data(
    access_token: str,
    ad_account_id: str,
    audience_name: str,
    customer_data_json: str = "[]",
) -> dict:
    """Create a Custom Audience and upload hashed customer data (emails/phones) for retargeting."""
    import json as _json
    act_id = _clean_act_id(ad_account_id)
    customer_data = _json.loads(customer_data_json) if isinstance(customer_data_json, str) else customer_data_json

    # Step A: Create the Custom Audience
    try:
        audience = _post(access_token, f"{act_id}/customaudiences", {
            "name": audience_name,
            "subtype": "CUSTOM",
            "description": f"Auto-synced customer list: {audience_name}",
            "customer_file_source": "USER_PROVIDED_ONLY",
        })
    except ValueError as e:
        return {"error": f"Audience creation failed: {e}", "step": "create"}

    audience_id = audience.get("id")
    if not audience_id:
        return {"error": "No audience_id returned", "raw": audience, "step": "create"}

    # Step B: Hash and format customer data
    schema = []
    data_rows = []

    # Detect available fields from first record
    if customer_data:
        sample = customer_data[0]
        if "email" in sample:
            schema.append("EMAIL")
        if "phone" in sample:
            schema.append("PHONE")

    if not schema:
        return {"audience_id": audience_id, "users_uploaded": 0, "warning": "No email or phone fields found in data"}

    for record in customer_data:
        row = []
        if "EMAIL" in schema:
            email = record.get("email", "")
            row.append(_normalize_and_hash(email, "email") if email else "")
        if "PHONE" in schema:
            phone = record.get("phone", "")
            row.append(_normalize_and_hash(phone, "phone") if phone else "")
        if any(row):  # skip empty rows
            data_rows.append(row)

    if not data_rows:
        return {"audience_id": audience_id, "users_uploaded": 0, "warning": "No valid records to upload"}

    # Step C: Upload hashed users
    payload = {
        "payload": _json.dumps({
            "schema": schema,
            "data": data_rows,
        }),
    }
    try:
        upload_result = _post(access_token, f"{audience_id}/users", payload)
    except ValueError as e:
        return {"audience_id": audience_id, "error": f"User upload failed: {e}", "step": "upload"}

    return {
        "audience_id": audience_id,
        "users_uploaded": len(data_rows),
        "schema": schema,
        "upload_result": upload_result,
    }


def create_lookalike_audience(
    access_token: str,
    ad_account_id: str,
    origin_audience_id: str,
    country_code: str = "PK",
    ratio: float = 0.01,
    audience_name: str = "",
) -> dict:
    """Create a 1% Lookalike Audience from a source Custom Audience."""
    import json as _json
    act_id = _clean_act_id(ad_account_id)

    pct = int(ratio * 100) if ratio < 1 else int(ratio)
    name = audience_name or f"{pct}% LAL - {origin_audience_id[:12]}"

    try:
        lal = _post(access_token, f"{act_id}/customaudiences", {
            "name": name,
            "subtype": "LOOKALIKE",
            "origin_audience_id": origin_audience_id,
            "lookalike_spec": _json.dumps({
                "type": "similarity",
                "country": country_code,
                "ratio": ratio if ratio < 1 else ratio / 100,
            }),
        })
    except ValueError as e:
        return {"error": f"LAL creation failed: {e}", "step": "create"}

    lal_id = lal.get("id")
    if not lal_id:
        return {"error": "No LAL audience_id returned", "raw": lal, "step": "create"}

    return {
        "audience_id": lal_id,
        "name": name,
        "origin_audience_id": origin_audience_id,
        "country": country_code,
        "ratio": ratio if ratio < 1 else ratio / 100,
    }


def stage_advanced_campaign(
    access_token: str, ad_account_id: str,
    campaign_name: str = "AI Campaign",
    daily_budget: float = 10.0,
    headline: str = "",
    body_text: str = "",
    link_url: str = "",
    image_url: str = "",
    video_url: str = "",
    cta_type: str = "SHOP_NOW",
    targeting_json: str = "{}",
    pixel_id: str = "",
    whatsapp_number: str = "",
    placements: str = "BOTH",
    page_id: str = "",
    instagram_actor_id: str = "",
    bid_amount: int = 0,
    bid_strategy: str = "",
    objective_hint: str = "",
    tracking_specs: str = "",
) -> dict:
    """
    Create a full campaign funnel (campaign + ad set + ad creative + ad).

    When pixel_id is provided: OUTCOME_SALES + OFFSITE_CONVERSIONS.
    When whatsapp_number is provided (no pixel): OUTCOME_ENGAGEMENT + CONVERSATIONS (WhatsApp/COD mode).
    """
    import json as _json
    act_id = _clean_act_id(ad_account_id)
    targeting_obj = _json.loads(targeting_json) if isinstance(targeting_json, str) else targeting_json

    # Decide objective: pixel overrides, then LLM hint, then default
    # NOTE: ENGAGEMENT/LEADS need extra setup (promoted_object, lead forms) — restrict to TRAFFIC/SALES for now
    has_pixel = bool(pixel_id)
    if has_pixel:
        objective = "OUTCOME_SALES"
        optimization = "OFFSITE_CONVERSIONS"
    else:
        objective = "OUTCOME_TRAFFIC"
        optimization = "LINK_CLICKS"

    # Build wa.me link for WhatsApp/COD mode
    wa_link = None
    if not has_pixel and whatsapp_number:
        clean_num = whatsapp_number.replace("+", "").replace(" ", "").replace("-", "")
        wa_link = f"https://wa.me/{clean_num}"

    # Inject publisher_platforms based on placement preference
    if placements == "FACEBOOK_ONLY":
        targeting_obj["publisher_platforms"] = ["facebook"]
        targeting_obj["facebook_positions"] = ["feed", "right_hand_column", "marketplace"]
    elif placements == "INSTAGRAM_ONLY":
        targeting_obj["publisher_platforms"] = ["instagram"]
        targeting_obj["instagram_positions"] = ["stream", "story", "explore", "reels"]
    # else BOTH: omit publisher_platforms → Meta auto-places

    # Step 1: Create campaign
    campaign_payload = {
        "name": campaign_name,
        "objective": objective,
        "status": "PAUSED",
        "special_ad_categories": [],
        "is_adset_budget_sharing_enabled": False,
    }
    print(f"=== CAMPAIGN PAYLOAD === {_json.dumps(campaign_payload, default=str)}", flush=True)
    try:
        campaign = _post(access_token, f"{act_id}/campaigns", campaign_payload)
    except ValueError as e:
        return {"error": f"Campaign creation failed: {e}", "step": "campaign"}
    campaign_id = campaign.get("id")
    if not campaign_id:
        return {"error": "Campaign creation failed — no ID returned", "raw": campaign, "step": "campaign"}

    # Step 2: Create ad set
    # destination_type is required by Meta API v18+ for OUTCOME_TRAFFIC/SALES
    if has_pixel:
        destination_type = "WEBSITE"
    elif wa_link:
        destination_type = "WHATSAPP"
    else:
        destination_type = "WEBSITE"

    # Inject targeting_automation (required by Meta API v22+)
    targeting_obj["targeting_automation"] = {"advantage_audience": 0}

    adset_payload = {
        "name": f"{campaign_name} — Ad Set",
        "campaign_id": campaign_id,
        "daily_budget": int(daily_budget * 100),
        "billing_event": "IMPRESSIONS",
        "optimization_goal": optimization,
        "targeting": targeting_obj,
        "destination_type": destination_type,
        "status": "PAUSED",
    }
    # Lock bid_strategy + bid_amount together — Meta requires both for Cost Cap
    if bid_amount > 0:
        adset_payload["bid_strategy"] = "COST_CAP"
        adset_payload["bid_amount"] = bid_amount
    else:
        adset_payload["bid_strategy"] = bid_strategy if bid_strategy else "LOWEST_COST_WITHOUT_CAP"
        adset_payload.pop("bid_amount", None)
    if has_pixel:
        adset_payload["promoted_object"] = {
            "pixel_id": pixel_id,
            "custom_event_type": "PURCHASE",
        }
    # Tracking specs — tell Meta which pixel events to track
    if tracking_specs:
        try:
            adset_payload["tracking_specs"] = _json.loads(tracking_specs) if isinstance(tracking_specs, str) else tracking_specs
        except Exception:
            pass

    print(f"=== ADSET PAYLOAD (final) === {_json.dumps(adset_payload, default=str)}", flush=True)
    try:
        adset = _post(access_token, f"{act_id}/adsets", adset_payload)
    except ValueError as e:
        return {"error": f"Ad set creation failed: {e}", "step": "adset", "campaign_id": campaign_id}
    adset_id = adset.get("id")

    # Step 3: Discover user's Facebook Page + Page Access Token
    # Always fetch page access token — needed for page posts in dev mode
    resolved_page_id = page_id or None
    page_access_token = None
    try:
        pages = _get(access_token, "me/accounts", params={"fields": "id,name,access_token", "limit": "10"})
        page_list = pages.get("data", [])
        if page_list:
            if resolved_page_id:
                # Find matching page's access token
                for p in page_list:
                    if p["id"] == resolved_page_id:
                        page_access_token = p.get("access_token")
                        break
                if not page_access_token:
                    page_access_token = page_list[0].get("access_token")
            else:
                resolved_page_id = page_list[0]["id"]
                page_access_token = page_list[0].get("access_token")
    except Exception as e:
        log.warning(f"Could not fetch Pages: {e}")
    print(f"=== PAGE RESOLVED === page_id={resolved_page_id}, has_page_token={bool(page_access_token)}", flush=True)

    # NOTE: instagram_actor_id intentionally NOT included in object_story_spec.
    # Meta auto-routes to Instagram via the Page connection. Sending an unverified
    # IG actor ID triggers Error 31/3858385 or Error 100 "pending action" blocks.

    # Step 4: Create ad creative + ad
    # MINIMAL payload — no instagram_actor_id (Meta auto-routes IG via Page).
    # Only page_id + link_data/video_data in object_story_spec.
    # CTA kept simple: {"type": "LEARN_MORE", "value": {"link": "<url>"}}.
    ad_id = None
    creative_id = None
    creative_error = None

    if resolved_page_id and adset_id:
        creative_link = wa_link or link_url or "https://example.com"

        # --- Helper: resolve local image to ad-account image hash ---
        def _resolve_image(img_url: str) -> str | None:
            """Upload local image to Meta ad account, return its URL. Pass-through for remote."""
            if not img_url:
                return None
            if not img_url.startswith("/uploads/"):
                return img_url  # already a remote URL
            # URL: /uploads/files/{user_id}/xxx.ext → disk: /shared-uploads/{user_id}/xxx.ext
            if img_url.startswith("/uploads/files/"):
                local_path = "/shared-uploads/" + img_url[len("/uploads/files/"):]
            else:
                local_path = "/shared-uploads/" + img_url[len("/uploads/"):]
            if not os.path.isfile(local_path):
                log.warning(f"Local image not found: {local_path}")
                return None
            log.info(f"Uploading local image to Meta: {local_path}")
            url = f"{BASE_URL}/{act_id}/adimages"
            try:
                with open(local_path, "rb") as f:
                    resp = requests.post(
                        url,
                        params={"access_token": access_token},
                        files={"filename": (os.path.basename(local_path), f)},
                        timeout=60,
                    )
                data = resp.json()
                if "error" in data:
                    log.error(f"Image upload failed: {data['error']}")
                    return None
                images = data.get("images", {})
                for img_data in images.values():
                    remote_url = img_data.get("url")
                    if remote_url:
                        print(f"=== IMAGE UPLOADED === {remote_url[:80]}", flush=True)
                        return remote_url
            except Exception as e:
                log.error(f"Image upload exception: {e}")
            return None

        # --- Minimal CTA ---
        simple_cta = {
            "type": "LEARN_MORE",
            "value": {"link": creative_link},
        }

        # --- Detect media type ---
        is_video = bool(video_url)
        creative_payload = None

        if is_video:
            # Upload video to Meta ad account first
            print(f"=== UPLOADING VIDEO === {video_url[:80]}", flush=True)
            video_result = upload_ad_video(access_token, ad_account_id, video_url)
            video_id = video_result.get("video_id")
            if not video_id:
                creative_error = f"Video upload failed: {video_result.get('error', 'unknown')}"
                print(f"=== VIDEO UPLOAD FAILED === {creative_error}", flush=True)

            if video_id:
                # Resolve thumbnail — REQUIRED by Meta
                resolved_thumb = _resolve_image(image_url) if image_url else None
                if not resolved_thumb:
                    resolved_thumb = "https://images.unsplash.com/photo-1558642452-9d2a7deb7f62?w=1080&q=80"
                    print("=== VIDEO THUMBNAIL === using fallback placeholder", flush=True)

                creative_payload = {
                    "name": f"{campaign_name} — Video Creative",
                    "object_story_spec": {
                        "page_id": resolved_page_id,
                        "video_data": {
                            "video_id": video_id,
                            "message": body_text or "",
                            "title": headline or campaign_name,
                            "image_url": resolved_thumb,
                            "call_to_action": simple_cta,
                        },
                    },
                }
        else:
            # Image ad — resolve picture URL
            resolved_picture = _resolve_image(image_url)

            link_data = {
                "link": creative_link,
                "message": body_text or "",
                "name": headline or campaign_name,
                "call_to_action": simple_cta,
            }
            if resolved_picture:
                link_data["picture"] = resolved_picture

            creative_payload = {
                "name": f"{campaign_name} — Creative",
                "object_story_spec": {
                    "page_id": resolved_page_id,
                    "link_data": link_data,
                },
            }

        # --- POST AdCreative ---
        if creative_error:
            print(f"=== SKIPPING CREATIVE — prior error === {creative_error}", flush=True)
        elif creative_payload:
            print(f"=== [POINT-OF-FAILURE: AdCreative] POST {act_id}/adcreatives ===", flush=True)
            print(f"=== CREATIVE PAYLOAD === {_json.dumps(creative_payload, default=str)}", flush=True)
            try:
                creative = _post(access_token, f"{act_id}/adcreatives", creative_payload)
                creative_id = creative.get("id")
                print(f"=== CREATIVE CREATED === creative_id={creative_id}", flush=True)
            except ValueError as e:
                creative_error = str(e)
                print(f"=== CREATIVE FAILED === {e}", flush=True)

        # --- POST Ad (minimal: name + adset_id + creative + status) ---
        if creative_id and adset_id:
            ad_payload = {
                "name": f"{campaign_name} — Ad",
                "adset_id": adset_id,
                "creative": {"creative_id": creative_id},
                "status": "PAUSED",
            }
            print(f"=== [POINT-OF-FAILURE: Ad] POST {act_id}/ads ===", flush=True)
            print(f"=== AD PAYLOAD === {_json.dumps(ad_payload, default=str)}", flush=True)
            try:
                ad = _post(access_token, f"{act_id}/ads", ad_payload)
                ad_id = ad.get("id")
                print(f"=== AD CREATED === ad_id={ad_id}", flush=True)
            except Exception as e:
                creative_error = str(e)
                print(f"=== AD FAILED === {e}", flush=True)
    else:
        creative_error = f"Missing: page_id={resolved_page_id}, adset_id={adset_id}"
        print(f"=== SKIPPED AD CREATION === {creative_error}", flush=True)

    result = {
        "campaign_id": campaign_id,
        "adset_id": adset_id,
        "ad_id": ad_id,
        "page_id": resolved_page_id,
        "objective": objective,
        "optimization": optimization,
        "wa_link": wa_link,
        "creative_id": creative_id,
        "status": "PAUSED",
    }
    if creative_error and not ad_id:
        result["creative_error"] = creative_error
    return result


# ── Optimization Co-Pilot tools ──────────────────────────────────────────────

def get_deep_ad_insights(access_token: str, ad_account_id: str, date_preset: str = "last_7d",
                          entity_level: str = "campaign") -> dict:
    """Get performance breakdowns by age, gender, and placement for optimization analysis."""
    act_id = _clean_act_id(ad_account_id)
    preset = DATE_PRESETS.get(date_preset, "last_7d")
    fields = "campaign_id,campaign_name,adset_id,adset_name,spend,impressions,clicks,ctr,cpm,frequency,actions,cost_per_action_type"
    breakdowns_map = {
        "age": "age",
        "gender": "gender",
        "placement": "publisher_platform,platform_position",
    }
    result = {"ad_account_id": ad_account_id, "date_preset": preset, "entity_level": entity_level}
    for bk_name, bk_value in breakdowns_map.items():
        url = f"{BASE_URL}/{act_id}/insights"
        params = {
            "access_token": access_token,
            "fields": fields,
            "date_preset": preset,
            "level": entity_level,
            "breakdowns": bk_value,
            "limit": 200,
        }
        resp = requests.get(url, params=params, timeout=30)
        data = resp.json()
        rows = []
        for r in data.get("data", []):
            actions = r.get("actions", [])
            res = _extract_results(actions)
            cpa_list = r.get("cost_per_action_type", [])
            cost_per_result = None
            for cpa in cpa_list:
                if cpa.get("action_type") in ("purchase", "lead", "offsite_conversion.fb_pixel_purchase", "onsite_conversion.lead_grouped"):
                    cost_per_result = round(float(cpa.get("value", 0)), 2)
                    break
            row = {
                "campaign_id": r.get("campaign_id"),
                "campaign_name": r.get("campaign_name"),
                "adset_id": r.get("adset_id"),
                "adset_name": r.get("adset_name"),
                "spend": round(float(r.get("spend", 0)), 2),
                "impressions": int(r.get("impressions", 0)),
                "clicks": int(r.get("clicks", 0)),
                "ctr": round(float(r.get("ctr", 0)), 2),
                "cpm": round(float(r.get("cpm", 0)), 2),
                "frequency": round(float(r.get("frequency", 0)), 2),
                **res,
                "cost_per_result": cost_per_result,
            }
            if bk_name == "age":
                row["age"] = r.get("age", "unknown")
            elif bk_name == "gender":
                row["gender"] = r.get("gender", "unknown")
            else:
                row["publisher_platform"] = r.get("publisher_platform", "unknown")
                row["platform_position"] = r.get("platform_position", "unknown")
            rows.append(row)
        result[f"by_{bk_name}"] = rows

    # Fetch 3-day trend data for fatigue detection (frequency + CTR over short window)
    trend_url = f"{BASE_URL}/{act_id}/insights"
    trend_params = {
        "access_token": access_token,
        "fields": "campaign_id,campaign_name,adset_id,adset_name,spend,impressions,clicks,ctr,frequency",
        "date_preset": "last_3d",
        "level": entity_level,
        "limit": 100,
    }
    try:
        trend_resp = requests.get(trend_url, params=trend_params, timeout=30)
        trend_data = trend_resp.json()
        trend_rows = []
        for r in trend_data.get("data", []):
            trend_rows.append({
                "campaign_id": r.get("campaign_id"),
                "campaign_name": r.get("campaign_name"),
                "adset_id": r.get("adset_id"),
                "adset_name": r.get("adset_name"),
                "spend": round(float(r.get("spend", 0)), 2),
                "impressions": int(r.get("impressions", 0)),
                "clicks": int(r.get("clicks", 0)),
                "ctr": round(float(r.get("ctr", 0)), 2),
                "frequency": round(float(r.get("frequency", 0)), 2),
            })
        result["trend_3d"] = trend_rows
    except Exception as e:
        log.warning(f"Failed to fetch 3-day trend data: {e}")
        result["trend_3d"] = []

    return result


def update_adset_budget(access_token: str, adset_id: str, daily_budget: int | None = None,
                         lifetime_budget: int | None = None) -> dict:
    """Update an adset's daily or lifetime budget. Amounts in CENTS (minor currency units)."""
    url = f"{BASE_URL}/{adset_id}"
    params: dict[str, Any] = {"access_token": access_token}
    if daily_budget is not None:
        params["daily_budget"] = daily_budget
    if lifetime_budget is not None:
        params["lifetime_budget"] = lifetime_budget
    if len(params) == 1:
        return {"success": False, "error": "Provide daily_budget or lifetime_budget"}
    resp = requests.post(url, params=params, timeout=15)
    data = resp.json()
    if data.get("success") or data.get("id"):
        return {"success": True, "adset_id": adset_id, "daily_budget": daily_budget, "lifetime_budget": lifetime_budget}
    return {"success": False, "error": data.get("error", {}).get("message", str(data))}


def update_adset_targeting(access_token: str, adset_id: str,
                           exclude_publisher_platforms: list[str] | None = None,
                           bid_strategy: str | None = None,
                           bid_amount: int | None = None) -> dict:
    """Update an adset's targeting (exclude placements) or bid strategy (COST_CAP)."""
    url = f"{BASE_URL}/{adset_id}"
    params: dict[str, Any] = {"access_token": access_token}
    if exclude_publisher_platforms:
        # To exclude placements, we set publisher_platforms to everything EXCEPT excluded
        all_platforms = {"facebook", "instagram", "audience_network", "messenger"}
        keep = list(all_platforms - set(exclude_publisher_platforms))
        if not keep:
            return {"success": False, "error": "Cannot exclude all platforms"}
        params["targeting"] = json.dumps({"publisher_platforms": keep})
    if bid_strategy:
        params["bid_strategy"] = bid_strategy
    if bid_amount is not None:
        params["bid_amount"] = bid_amount
    if len(params) == 1:
        return {"success": False, "error": "No changes specified"}
    resp = requests.post(url, params=params, timeout=15)
    data = resp.json()
    if data.get("success") or data.get("id"):
        return {"success": True, "adset_id": adset_id, "changes": {k: v for k, v in params.items() if k != "access_token"}}
    return {"success": False, "error": data.get("error", {}).get("message", str(data))}


def update_entity_status(access_token: str, entity_id: str, status: str) -> dict:
    """Update the status of a campaign, adset, or ad. Status: ACTIVE or PAUSED."""
    if status not in ("ACTIVE", "PAUSED"):
        return {"success": False, "error": "Status must be ACTIVE or PAUSED"}
    url = f"{BASE_URL}/{entity_id}"
    resp = requests.post(url, params={"access_token": access_token, "status": status}, timeout=15)
    data = resp.json()
    if data.get("success") or data.get("id"):
        return {"success": True, "entity_id": entity_id, "new_status": status}
    return {"success": False, "error": data.get("error", {}).get("message", str(data))}


def get_ad_creatives_with_performance(
    access_token: str, ad_account_id: str, date_preset: str = "last_7d",
) -> dict:
    """
    Fetch all active ads with their creative text (body, headline, CTA) AND
    performance metrics. Used by the Co-Pilot to write research-backed ad copy.
    """
    act_id = _clean_act_id(ad_account_id)
    preset = DATE_PRESETS.get(date_preset, "last_7d")

    # Step 1: Fetch active ads with creative details
    try:
        ads_data = _get(access_token, f"{act_id}/ads", {
            "fields": "id,name,status,effective_status,adset_id,campaign_id,creative{id,body,title,link_url,call_to_action_type,object_story_spec}",
            "filtering": '[{"field":"effective_status","operator":"IN","value":["ACTIVE","PAUSED"]}]',
            "limit": "50",
        })
    except Exception as e:
        return {"error": str(e), "ads": []}

    # Step 2: Fetch ad-level insights
    ins_map: dict[str, dict] = {}
    try:
        ins_data = _get(access_token, f"{act_id}/insights", {
            "fields": "ad_id,ad_name,spend,impressions,clicks,ctr,cpm,frequency,actions,cost_per_action_type",
            "date_preset": preset,
            "level": "ad",
            "limit": "100",
        })
        for r in ins_data.get("data", []):
            aid = r.get("ad_id")
            res = _extract_results(r.get("actions", []))
            spend = float(r.get("spend", 0))
            cpr = round(spend / res["results"], 2) if res["results"] > 0 else None
            ins_map[aid] = {
                "spend": round(spend, 2),
                "impressions": int(r.get("impressions", 0)),
                "clicks": int(r.get("clicks", 0)),
                "ctr": round(float(r.get("ctr", 0)), 2),
                "cpm": round(float(r.get("cpm", 0)), 2),
                "frequency": round(float(r.get("frequency", 0)), 2),
                "results": res["results"],
                "result_type": res["result_type"],
                "cost_per_result": cpr,
            }
    except Exception:
        pass

    # Step 3: Merge creative text + performance
    ads = []
    for ad in ads_data.get("data", []):
        aid = ad["id"]
        creative = ad.get("creative", {})
        perf = ins_map.get(aid, {})

        # Extract body text from creative or object_story_spec
        body = creative.get("body", "")
        title = creative.get("title", "")
        story_spec = creative.get("object_story_spec", {})
        if not body and story_spec:
            link_data = story_spec.get("link_data", {})
            body = link_data.get("message", "")
            title = title or link_data.get("name", "")

        ads.append({
            "ad_id": aid,
            "ad_name": ad.get("name", ""),
            "status": ad.get("effective_status", ad.get("status", "")),
            "adset_id": ad.get("adset_id", ""),
            "campaign_id": ad.get("campaign_id", ""),
            "body_text": body,
            "headline": title,
            "cta_type": creative.get("call_to_action_type", ""),
            "link_url": creative.get("link_url", ""),
            **perf,
        })

    # Sort by spend descending (most active first)
    ads.sort(key=lambda a: a.get("spend", 0), reverse=True)

    return {
        "ad_account_id": ad_account_id,
        "date_preset": preset,
        "total_ads": len(ads),
        "ads": ads,
    }


# ── Agentic Co-Pilot tools (V3) ──────────────────────────────────────────────

def duplicate_ad_with_mutations(
    access_token: str, ad_account_id: str, source_ad_id: str,
    new_body_text: str = "", new_cta: str = "", new_name_suffix: str = "B",
) -> dict:
    """
    Duplicate a winning ad with mutations (new copy, CTA, etc.) for A/B testing.
    Reads the source ad's creative, creates a new creative with mutations, then
    creates a new ad in the same adset.
    """
    import json as _json
    act_id = _clean_act_id(ad_account_id)

    # Step 1: Read the source ad to get its adset_id and creative
    url = f"{BASE_URL}/{source_ad_id}"
    resp = requests.get(url, params={
        "access_token": access_token,
        "fields": "name,adset_id,creative{id,name,object_story_spec,thumbnail_url}",
    }, timeout=15)
    source = resp.json()
    if "error" in source:
        return {"success": False, "error": source["error"].get("message", str(source)), "step": "read_source_ad"}

    adset_id = source.get("adset_id")
    source_creative = source.get("creative", {})
    source_story_spec = source_creative.get("object_story_spec", {})
    source_name = source.get("name", "Ad")

    if not adset_id:
        return {"success": False, "error": "Could not determine adset_id from source ad", "step": "read_source_ad"}

    # Step 2: Mutate the creative — update body text and/or CTA
    link_data = source_story_spec.get("link_data", {})
    if new_body_text:
        link_data["message"] = new_body_text
    if new_cta and link_data.get("call_to_action"):
        link_data["call_to_action"]["type"] = new_cta

    mutated_spec = {**source_story_spec, "link_data": link_data}

    # Step 3: Create new creative
    creative_payload = {
        "name": f"{source_creative.get('name', source_name)} — {new_name_suffix}",
        "object_story_spec": mutated_spec,
    }
    try:
        new_creative = _post(access_token, f"{act_id}/adcreatives", creative_payload)
    except ValueError as e:
        return {"success": False, "error": str(e), "step": "create_creative"}

    new_creative_id = new_creative.get("id")
    if not new_creative_id:
        return {"success": False, "error": "No creative_id returned", "raw": new_creative, "step": "create_creative"}

    # Step 4: Create new ad in same adset
    try:
        new_ad = _post(access_token, f"{act_id}/ads", {
            "name": f"{source_name} — {new_name_suffix}",
            "adset_id": adset_id,
            "creative": {"creative_id": new_creative_id},
            "status": "PAUSED",
        })
    except ValueError as e:
        return {"success": False, "error": str(e), "step": "create_ad", "creative_id": new_creative_id}

    return {
        "success": True,
        "source_ad_id": source_ad_id,
        "new_ad_id": new_ad.get("id"),
        "new_creative_id": new_creative_id,
        "adset_id": adset_id,
        "mutations": {"body_text": new_body_text or "(unchanged)", "cta": new_cta or "(unchanged)"},
    }


def shift_budget_between_entities(
    access_token: str, source_entity_id: str, target_entity_id: str,
    amount_cents: int,
) -> dict:
    """
    Robin Hood: decrease source adset/campaign budget by amount_cents and increase
    target adset/campaign budget by the same amount. Both must be adsets with daily budgets.
    """
    errors = []

    # Step 1: Read current budgets from both entities
    src_resp = requests.get(f"{BASE_URL}/{source_entity_id}", params={
        "access_token": access_token, "fields": "daily_budget,name",
    }, timeout=15).json()
    tgt_resp = requests.get(f"{BASE_URL}/{target_entity_id}", params={
        "access_token": access_token, "fields": "daily_budget,name",
    }, timeout=15).json()

    src_budget = int(src_resp.get("daily_budget", 0))
    tgt_budget = int(tgt_resp.get("daily_budget", 0))

    if src_budget < amount_cents:
        return {"success": False, "error": f"Source budget ({src_budget}) < transfer amount ({amount_cents})"}

    new_src = src_budget - amount_cents
    new_tgt = tgt_budget + amount_cents

    # Step 2: Decrease source
    resp1 = requests.post(f"{BASE_URL}/{source_entity_id}", params={
        "access_token": access_token, "daily_budget": new_src,
    }, timeout=15)
    d1 = resp1.json()
    if not (d1.get("success") or d1.get("id")):
        errors.append({"entity": source_entity_id, "error": d1.get("error", {}).get("message", str(d1))})

    # Step 3: Increase target
    resp2 = requests.post(f"{BASE_URL}/{target_entity_id}", params={
        "access_token": access_token, "daily_budget": new_tgt,
    }, timeout=15)
    d2 = resp2.json()
    if not (d2.get("success") or d2.get("id")):
        errors.append({"entity": target_entity_id, "error": d2.get("error", {}).get("message", str(d2))})

    if errors:
        return {"success": False, "errors": errors, "partial": True}

    return {
        "success": True,
        "source": {"id": source_entity_id, "name": src_resp.get("name"), "old_budget": src_budget, "new_budget": new_src},
        "target": {"id": target_entity_id, "name": tgt_resp.get("name"), "old_budget": tgt_budget, "new_budget": new_tgt},
        "transferred_cents": amount_cents,
    }


def create_lookalike_from_campaign(
    access_token: str, ad_account_id: str, campaign_id: str,
    country_code: str = "PK", ratio: float = 0.01,
) -> dict:
    """
    Auto-create a 1% LAL from a campaign's lead data. Reads the campaign's custom
    audiences (if any), or creates a Website Custom Audience from the campaign's pixel,
    then builds a LAL from it.
    """
    act_id = _clean_act_id(ad_account_id)

    # Step 1: Find adsets in this campaign to locate the pixel / custom audiences
    adsets_resp = requests.get(f"{BASE_URL}/{campaign_id}/adsets", params={
        "access_token": access_token,
        "fields": "id,name,targeting",
        "limit": 10,
    }, timeout=15).json()

    adsets = adsets_resp.get("data", [])
    if not adsets:
        return {"success": False, "error": "No adsets found in campaign", "step": "find_adsets"}

    # Look for existing custom_audiences in targeting
    origin_audience_id = None
    for adset in adsets:
        targeting = adset.get("targeting", {})
        cas = targeting.get("custom_audiences", [])
        if cas:
            origin_audience_id = cas[0].get("id")
            break

    # Step 2: If no existing audience, try to create one from campaign leads
    if not origin_audience_id:
        # Create an engagement-based custom audience from this campaign
        import json as _json
        try:
            ca = _post(access_token, f"{act_id}/customaudiences", {
                "name": f"Engagers - Campaign {campaign_id[:12]}",
                "subtype": "ENGAGEMENT",
                "rule": _json.dumps({
                    "inclusions": {"operator": "or", "rules": [
                        {"event_sources": [{"type": "campaign", "id": campaign_id}],
                         "retention_seconds": 2592000}  # 30 days
                    ]}
                }),
            })
            origin_audience_id = ca.get("id")
        except ValueError as e:
            return {"success": False, "error": f"Failed to create source audience: {e}", "step": "create_source"}

    if not origin_audience_id:
        return {"success": False, "error": "Could not find or create source audience", "step": "resolve_source"}

    # Step 3: Create the LAL
    pct = int(ratio * 100) if ratio < 1 else int(ratio)
    lal_name = f"{pct}% LAL - Campaign {campaign_id[:12]}"

    return create_lookalike_audience(
        access_token=access_token,
        ad_account_id=ad_account_id,
        origin_audience_id=origin_audience_id,
        country_code=country_code,
        ratio=ratio,
        audience_name=lal_name,
    )


# ── SaaS JSON tools (7 + 2 new + 7 targeting/research + 3 optimization) ────

SAAS_TOOLS: dict[str, dict[str, Any]] = {
    "saas_account_overview": {
        "function": saas_account_overview,
        "description": "Account health snapshot with 30d spend, ROAS, purchases — returns structured JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string", "description": "Ad account ID (without act_ prefix)"},
            },
            "required": ["access_token", "ad_account_id"],
        },
        "returns": "json",
    },
    "saas_list_campaigns": {
        "function": saas_list_campaigns,
        "description": "List campaigns with status, budget, and 7d metrics — returns structured JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string"},
                "status_filter": {"type": "string", "enum": ["all", "active", "paused", "archived"], "default": "all"},
                "limit": {"type": "integer", "default": 25},
            },
            "required": ["access_token", "ad_account_id"],
        },
        "returns": "json",
    },
    "saas_campaign_insights": {
        "function": saas_campaign_insights,
        "description": "Detailed performance insights for a campaign — returns structured JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "campaign_id": {"type": "string"},
                "date_preset": {"type": "string", "default": "last_7d"},
            },
            "required": ["access_token", "campaign_id"],
        },
        "returns": "json",
    },
    "saas_campaign_detail": {
        "function": saas_campaign_detail,
        "description": "Full campaign detail: summary, daily time-series, ads, and demographic/placement breakdowns — structured JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "campaign_id": {"type": "string"},
                "date_preset": {"type": "string", "default": "last_7d"},
            },
            "required": ["access_token", "campaign_id"],
        },
        "returns": "json",
    },
    "saas_list_ads": {
        "function": saas_list_ads,
        "description": "List all ads in a campaign with per-ad ROAS verdicts — returns structured JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "campaign_id": {"type": "string"},
                "date_preset": {"type": "string", "default": "last_7d"},
                "status_filter": {"type": "string", "enum": ["all", "active", "paused"], "default": "all"},
            },
            "required": ["access_token", "campaign_id"],
        },
        "returns": "json",
    },
    "saas_page_posts": {
        "function": saas_page_posts,
        "description": "Fetch recent Facebook Page posts with reach & engagement — returns structured JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_access_token": {"type": "string"},
                "page_id": {"type": "string"},
            },
            "required": ["page_access_token", "page_id"],
        },
        "returns": "json",
    },
    "get_account_audit_data": {
        "function": get_account_audit_data,
        "description": "Fetch ad-level performance data for account audit (last 30 days) — returns structured JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string", "description": "Ad account ID (without act_ prefix)"},
                "date_preset": {"type": "string", "default": "last_30d"},
            },
            "required": ["access_token", "ad_account_id"],
        },
        "returns": "json",
    },
    "research_niche_trends": {
        "function": research_niche_trends,
        "description": "Research current advertising trends and best practices for a niche via web search — returns structured JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "niche": {"type": "string", "description": "Industry or niche to research (e.g. 'DTC Skincare', 'B2B SaaS')"},
                "country": {"type": "string", "default": "US"},
            },
            "required": ["niche"],
        },
        "returns": "json",
    },
    "get_performance_insights": {
        "function": get_performance_insights,
        "description": "Analyze ad creative patterns — identifies top/worst performers, winning headlines, CTA types, and copy length patterns — returns structured JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string", "description": "Ad account ID (without act_ prefix)"},
                "date_preset": {"type": "string", "default": "last_30d"},
            },
            "required": ["access_token", "ad_account_id"],
        },
        "returns": "json",
    },
    "validate_meta_interests": {
        "function": validate_meta_interests,
        "description": "Validate keywords against Meta's ad interest taxonomy — returns matched interests with audience sizes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "keywords_json": {"type": "string", "description": "JSON array of keyword strings"},
            },
            "required": ["access_token", "keywords_json"],
        },
        "returns": "json",
    },
    "search_meta_interests": {
        "function": search_meta_interests,
        "description": "Search and validate culturally relevant Meta ad interests for a target country. Returns clean JSON array of valid Meta Interest objects with real IDs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "keywords_json": {"type": "string", "description": "JSON array of AI-suggested interest keyword strings"},
                "target_country": {"type": "string", "description": "ISO country code (e.g. PK, US, GB)", "default": "US"},
            },
            "required": ["access_token", "keywords_json", "target_country"],
        },
        "returns": "json",
    },
    "resolve_geo_locations": {
        "function": resolve_geo_locations,
        "description": "Resolve city names to Meta geo-location keys for ad targeting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "cities_json": {"type": "string", "description": "JSON array of city name strings"},
                "country_code": {"type": "string", "default": "PK"},
            },
            "required": ["access_token", "cities_json"],
        },
        "returns": "json",
    },
    "fetch_competitor_ads": {
        "function": fetch_competitor_ads,
        "description": "Search Meta Ad Library for active competitor ads matching keywords.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "keywords_json": {"type": "string", "description": "JSON array of keyword strings"},
                "country_code": {"type": "string", "default": "PK"},
            },
            "required": ["access_token", "keywords_json"],
        },
        "returns": "json",
    },
    "fetch_ad_account_pixels": {
        "function": fetch_ad_account_pixels,
        "description": "List Meta Pixels available on an ad account.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string"},
            },
            "required": ["access_token", "ad_account_id"],
        },
        "returns": "json",
    },
    "fetch_pixel_performance": {
        "function": fetch_pixel_performance,
        "description": "Get Pixel conversion performance data (events fired).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "pixel_id": {"type": "string"},
                "ad_account_id": {"type": "string"},
            },
            "required": ["access_token", "pixel_id", "ad_account_id"],
        },
        "returns": "json",
    },
    "get_pixel_events": {
        "function": get_pixel_events,
        "description": "Fetch active conversion events recorded by a Meta Pixel (events with recent activity).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "pixel_id": {"type": "string"},
            },
            "required": ["access_token", "pixel_id"],
        },
        "returns": "json",
    },
    "saas_time_series_insights": {
        "function": saas_time_series_insights,
        "description": "Get daily time-series performance data for charts — structured JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string"},
                "date_preset": {"type": "string", "default": "last_30d"},
            },
            "required": ["access_token", "ad_account_id"],
        },
        "returns": "json",
    },
    "scrape_website": {
        "function": scrape_website,
        "description": "Scrape a website URL using Tavily Extract API. Returns raw page content for analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "url": {"type": "string", "description": "The website URL to scrape"},
            },
            "required": ["url"],
        },
        "returns": "json",
    },
    "fetch_social_identities": {
        "function": fetch_social_identities,
        "description": "Fetch Facebook Pages and linked Instagram Business Accounts for the authenticated user.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string", "description": "Ad account ID (optional, for context)"},
            },
            "required": ["access_token"],
        },
        "returns": "json",
    },
    "publish_page_photo": {
        "function": publish_page_photo,
        "description": "Publish a photo post to a Facebook Page. Returns the post_id for use as object_story_id in ad creatives.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string", "description": "Facebook Page ID"},
                "image_url": {"type": "string", "description": "Image URL or base64 data URI"},
                "message": {"type": "string", "description": "Post caption / ad copy"},
                "access_token": {"type": "string", "description": "Page access token or user token with pages_manage_posts"},
            },
            "required": ["page_id", "image_url", "message", "access_token"],
        },
        "returns": "json",
    },
    "upload_ad_image": {
        "function": upload_ad_image,
        "description": "Upload an image to a Meta ad account. Accepts a URL or base64 data URI. Returns the image_hash for use in ad creatives.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string", "description": "Ad account ID (without act_ prefix)"},
                "image_url": {"type": "string", "description": "Image URL (https://...) or base64 data URI (data:image/...;base64,...)"},
            },
            "required": ["access_token", "ad_account_id", "image_url"],
        },
        "returns": "json",
    },
    "upload_ad_video": {
        "function": upload_ad_video,
        "description": "Upload a video to a Meta ad account from a URL. Returns video_id for use in video ad creatives.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string", "description": "Ad account ID (without act_ prefix)"},
                "video_url": {"type": "string", "description": "Public video URL (https://...)"},
            },
            "required": ["access_token", "ad_account_id", "video_url"],
        },
        "returns": "json",
    },
    "stage_advanced_campaign": {
        "function": stage_advanced_campaign,
        "description": "Create a full campaign funnel (campaign + ad set + creative + ad). Uses OUTCOME_SALES with pixel or OUTCOME_ENGAGEMENT with WhatsApp.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string"},
                "campaign_name": {"type": "string", "default": "AI Campaign"},
                "daily_budget": {"type": "number", "default": 10.0},
                "headline": {"type": "string", "description": "Ad headline text"},
                "body_text": {"type": "string", "description": "Ad body/primary text"},
                "link_url": {"type": "string", "description": "Landing page URL"},
                "image_url": {"type": "string", "description": "Image URL to upload as ad image"},
                "video_url": {"type": "string", "description": "Video URL for video ad creative (omit for image ads)"},
                "cta_type": {"type": "string", "default": "SHOP_NOW", "description": "CTA button type (SHOP_NOW, WHATSAPP_MESSAGE, etc.)"},
                "targeting_json": {"type": "string", "description": "JSON targeting object with geo_locations, interests, etc."},
                "pixel_id": {"type": "string", "description": "Meta Pixel ID for conversion tracking (omit for WhatsApp mode)"},
                "whatsapp_number": {"type": "string", "description": "WhatsApp number for COD mode (used when no pixel)"},
                "placements": {"type": "string", "default": "BOTH", "description": "BOTH, FACEBOOK_ONLY, or INSTAGRAM_ONLY"},
                "page_id": {"type": "string", "description": "Pre-stored Facebook Page ID (skips discovery)"},
                "instagram_actor_id": {"type": "string", "description": "Instagram Business Account ID for creative linking"},
                "tracking_specs": {"type": "string", "description": "JSON array of tracking specs for pixel conversion tracking"},
            },
            "required": ["access_token", "ad_account_id"],
        },
        "returns": "json",
    },
    "create_custom_audience_from_data": {
        "function": create_custom_audience_from_data,
        "description": "Create a Custom Audience and upload hashed customer data (emails/phones) for retargeting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string", "description": "Ad account ID (without act_ prefix)"},
                "audience_name": {"type": "string", "description": "Name for the Custom Audience"},
                "customer_data_json": {"type": "string", "description": "JSON array of objects with 'email' and/or 'phone' fields"},
            },
            "required": ["access_token", "ad_account_id", "audience_name"],
        },
        "returns": "json",
    },
    "create_lookalike_audience": {
        "function": create_lookalike_audience,
        "description": "Create a Lookalike Audience from a source Custom Audience.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string", "description": "Ad account ID (without act_ prefix)"},
                "origin_audience_id": {"type": "string", "description": "Source Custom Audience ID"},
                "country_code": {"type": "string", "default": "PK", "description": "Target country for LAL"},
                "ratio": {"type": "number", "default": 0.01, "description": "LAL ratio (0.01 = 1%)"},
                "audience_name": {"type": "string", "description": "Optional custom name for the LAL"},
            },
            "required": ["access_token", "ad_account_id", "origin_audience_id"],
        },
        "returns": "json",
    },
    # ── Optimization Co-Pilot tools ──────────────────────────────────────────
    "get_ad_creatives_with_performance": {
        "function": get_ad_creatives_with_performance,
        "description": "Fetch all ads with their creative text (body, headline, CTA) and performance metrics. For Co-Pilot research-backed copy generation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string", "description": "Ad account ID (without act_ prefix)"},
                "date_preset": {"type": "string", "default": "last_7d"},
            },
            "required": ["access_token", "ad_account_id"],
        },
        "returns": "json",
    },
    "get_deep_ad_insights": {
        "function": get_deep_ad_insights,
        "description": "Get performance breakdowns by age, gender, and placement for optimization analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string", "description": "Ad account ID (without act_ prefix)"},
                "date_preset": {"type": "string", "default": "last_7d", "description": "Date range: last_7d, last_14d, last_30d"},
                "entity_level": {"type": "string", "default": "campaign", "description": "Level: campaign, adset, or ad"},
            },
            "required": ["access_token", "ad_account_id"],
        },
        "returns": "json",
    },
    "update_adset_budget": {
        "function": update_adset_budget,
        "description": "Update an adset's daily or lifetime budget. Amounts in cents (minor currency units).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "adset_id": {"type": "string", "description": "The adset ID to update"},
                "daily_budget": {"type": "integer", "description": "New daily budget in cents"},
                "lifetime_budget": {"type": "integer", "description": "New lifetime budget in cents"},
            },
            "required": ["access_token", "adset_id"],
        },
        "returns": "json",
    },
    "update_entity_status": {
        "function": update_entity_status,
        "description": "Update the status of a campaign, adset, or ad to ACTIVE or PAUSED.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "entity_id": {"type": "string", "description": "Campaign, adset, or ad ID"},
                "status": {"type": "string", "enum": ["ACTIVE", "PAUSED"], "description": "New status"},
            },
            "required": ["access_token", "entity_id", "status"],
        },
        "returns": "json",
    },
    "update_adset_targeting": {
        "function": update_adset_targeting,
        "description": "Update an adset's targeting (exclude placements) or bid strategy (COST_CAP with bid_amount in cents).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "adset_id": {"type": "string", "description": "The adset ID to update"},
                "exclude_publisher_platforms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Platforms to exclude: audience_network, messenger, etc.",
                },
                "bid_strategy": {"type": "string", "enum": ["LOWEST_COST_WITHOUT_CAP", "COST_CAP"], "description": "Bid strategy"},
                "bid_amount": {"type": "integer", "description": "Bid cap in cents (required for COST_CAP)"},
            },
            "required": ["access_token", "adset_id"],
        },
        "returns": "json",
    },
    # ── Agentic Co-Pilot tools (V3) ──────────────────────────────────────────
    "duplicate_ad_with_mutations": {
        "function": duplicate_ad_with_mutations,
        "description": "Duplicate a winning ad with mutations (new body text, CTA) for A/B testing. Creates a new creative + ad in the same adset.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string", "description": "Ad account ID (without act_ prefix)"},
                "source_ad_id": {"type": "string", "description": "The winning ad to duplicate"},
                "new_body_text": {"type": "string", "description": "New ad copy text (leave empty to keep original)"},
                "new_cta": {"type": "string", "description": "New CTA type e.g. SHOP_NOW, LEARN_MORE, SIGN_UP"},
                "new_name_suffix": {"type": "string", "default": "B", "description": "Suffix for the new ad name"},
            },
            "required": ["access_token", "ad_account_id", "source_ad_id"],
        },
        "returns": "json",
    },
    "shift_budget_between_entities": {
        "function": shift_budget_between_entities,
        "description": "Robin Hood: move budget from a losing adset to a winning adset. Reads current budgets, decreases source, increases target by the same amount.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "source_entity_id": {"type": "string", "description": "Losing adset/campaign ID to take budget from"},
                "target_entity_id": {"type": "string", "description": "Winning adset/campaign ID to give budget to"},
                "amount_cents": {"type": "integer", "description": "Amount to transfer in cents"},
            },
            "required": ["access_token", "source_entity_id", "target_entity_id", "amount_cents"],
        },
        "returns": "json",
    },
    "create_lookalike_from_campaign": {
        "function": create_lookalike_from_campaign,
        "description": "Auto-create a 1% Lookalike Audience from a successful campaign's engaged audience. Finds or creates source audience, then builds LAL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "access_token": {"type": "string"},
                "ad_account_id": {"type": "string", "description": "Ad account ID (without act_ prefix)"},
                "campaign_id": {"type": "string", "description": "Source campaign with good leads/conversions"},
                "country_code": {"type": "string", "default": "PK", "description": "Target country for LAL"},
                "ratio": {"type": "number", "default": 0.01, "description": "LAL ratio (0.01 = 1%)"},
            },
            "required": ["access_token", "ad_account_id", "campaign_id"],
        },
        "returns": "json",
    },
}

TOOLS_REGISTRY.update(SAAS_TOOLS)
log.info(f"Total tools: {len(TOOLS_REGISTRY)} ({len(NUTREOP_TOOL_NAMES)} nutreoPak + {len(SAAS_TOOLS)} SaaS)")


# ═══════════════════════════════════════════════════════════════════════════════
# JSON-RPC 2.0 Handler
# ═══════════════════════════════════════════════════════════════════════════════

def handle_jsonrpc(request_body: dict) -> dict:
    req_id = request_body.get("id", 1)
    method = request_body.get("method", "")
    params = request_body.get("params", {})

    if method == "tools/list":
        tools_list = []
        for name, info in TOOLS_REGISTRY.items():
            tools_list.append({
                "name": name,
                "description": info["description"],
                "inputSchema": info["inputSchema"],
            })
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_list}}

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name not in TOOLS_REGISTRY:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}

        tool_info = TOOLS_REGISTRY[tool_name]
        tool_fn = tool_info["function"]
        returns = tool_info["returns"]

        try:
            result = tool_fn(**arguments)

            if returns == "json":
                # SaaS tools return dicts — pass through directly
                return {"jsonrpc": "2.0", "id": req_id, "result": result}
            else:
                # nutreoPak tools return text — wrap in MCP content format
                if isinstance(result, str):
                    return {"jsonrpc": "2.0", "id": req_id, "result": {
                        "content": [{"type": "text", "text": result}],
                    }}
                else:
                    return {"jsonrpc": "2.0", "id": req_id, "result": result}

        except TypeError as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32602, "message": f"Invalid params: {e}"}}
        except ValueError as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": str(e)}}
        except Exception as e:
            log.exception("Tool execution failed")
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": f"Tool error: {e}"}}

    elif method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "meta-marketing-mcp", "version": "2.0.0"},
        }}

    else:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"}}


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP Server
# ═══════════════════════════════════════════════════════════════════════════════

class MCPHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path not in ("/mcp", "/mcp/"):
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            request_body = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        tool_name = request_body.get("params", {}).get("name", "")
        log.info(f"<- {request_body.get('method', '?')} {tool_name}")
        response = handle_jsonrpc(request_body)
        log.info(f"-> {'error' if 'error' in response else 'ok'}")

        response_bytes = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_GET(self):
        if self.path in ("/health", "/"):
            body = json.dumps({
                "status": "ok",
                "service": "meta-marketing-mcp",
                "tools": len(TOOLS_REGISTRY),
                "nutreoPak_tools": len(NUTREOP_TOOL_NAMES),
                "saas_tools": len(SAAS_TOOLS),
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), MCPHandler)
    log.info(f"MCP Server on 0.0.0.0:{PORT} -- {len(TOOLS_REGISTRY)} tools loaded")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down...")
        server.server_close()
