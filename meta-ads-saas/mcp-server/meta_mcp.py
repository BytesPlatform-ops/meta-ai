"""
Multi-Tenant Meta Marketing API MCP Server
Stateless MCP server — all Meta credentials are passed per-call by the orchestrator.

Setup:
    python3 server.py
"""

import json
from typing import Optional, Literal

import requests
from fastmcp import FastMCP

# ── Constants ──────────────────────────────────────────────────────────────────
API_VERSION = "v22.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"
CHARACTER_LIMIT = 25_000

# ── Server ─────────────────────────────────────────────────────────────────────
mcp = FastMCP(
    "meta-marketing-mcp",
    instructions="""
    Multi-tenant Meta Marketing API server. All tools are stateless — pass
    the user's access_token, page_id, or ad_account_id on every call.

    The orchestrator/agent is responsible for resolving credentials from the
    connected user's session before invoking any tool.

    Workflow tips:
    - Start with get_user_ad_accounts to discover which accounts the user owns
    - Use list_campaigns → get_campaign_insights → list_ads to drill down
    - Use create_kill_rule and create_scale_rule to automate budget decisions
    - ROAS flags: 🟢 ≥3x (scale) | 🟡 1.5–3x (hold) | 🔴 <1.5x (review) | ⚪ no data
    """,
)


# ── API Helpers ────────────────────────────────────────────────────────────────

def _headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def _parse_meta_error(err: dict) -> str:
    """Return a human-readable string from Meta's error JSON."""
    code = err.get("code", "unknown")
    etype = err.get("type", "unknown")
    message = err.get("message", "No message provided.")
    subcode = err.get("error_subcode")
    blame = err.get("error_data", {}).get("blame_field_specs") if isinstance(err.get("error_data"), dict) else None

    # Log full error for debugging
    print(f"=== META ERROR DETAIL === {json.dumps(err, default=str)}", flush=True)

    hint = ""
    if code == 190:
        hint = " Hint: The access token is expired or invalid. The user needs to re-authenticate."
    elif code == 100:
        blame_hint = f" Blame field: {blame}" if blame else ""
        hint = f" Hint: A required permission is missing, or a parameter is invalid.{blame_hint}"
    elif code == 17:
        hint = " Hint: API rate limit reached. Wait a moment and try again."
    elif code == 10:
        hint = " Hint: Insufficient permissions for this operation."
    elif code == 4:
        hint = " Hint: Too many API calls. Back off and retry."

    sub = f" (subcode {subcode})" if subcode else ""
    return f"Meta API Error {code}{sub} ({etype}): {message}{hint}"


def _get(access_token: str, path: str, params: dict | None = None) -> dict:
    url = f"{BASE_URL}/{path}"
    try:
        resp = requests.get(url, headers=_headers(access_token), params=params or {}, timeout=30)
        data = resp.json()
    except requests.RequestException as e:
        raise ValueError(f"Network error calling Meta API: {e}")
    except ValueError:
        raise ValueError(f"Meta API returned non-JSON response (HTTP {resp.status_code}).")
    if "error" in data:
        raise ValueError(_parse_meta_error(data["error"]))
    return data


def _post(access_token: str, path: str, payload: dict) -> dict:
    url = f"{BASE_URL}/{path}"
    print(f"=== META POST === {path} keys={list(payload.keys())}", flush=True)
    # Meta Marketing API expects form-encoded data with access_token as param.
    # Nested dicts/lists (e.g. targeting, object_story_spec, creative) must be
    # JSON-stringified values — this is how Meta's own SDKs send them.
    form_data = {}
    for k, v in payload.items():
        if isinstance(v, (dict, list)):
            form_data[k] = json.dumps(v)
        elif isinstance(v, bool):
            form_data[k] = json.dumps(v)
        else:
            form_data[k] = v
    try:
        resp = requests.post(
            url,
            params={"access_token": access_token},
            data=form_data,
            timeout=30,
        )
        data = resp.json()
    except requests.RequestException as e:
        raise ValueError(f"Network error calling Meta API: {e}")
    except ValueError:
        raise ValueError(f"Meta API returned non-JSON response (HTTP {resp.status_code}).")
    if "error" in data:
        print(f"=== META POST FAILED === path={path} payload={json.dumps(payload, default=str)}", flush=True)
        print(f"=== META ERROR RESPONSE === {json.dumps(data, default=str)}", flush=True)
        print(f"=== META ERROR DETAIL === {json.dumps(data.get('error', {}), default=str)}", flush=True)
        raise ValueError(_parse_meta_error(data["error"]))
    return data


def _delete(access_token: str, path: str) -> dict:
    url = f"{BASE_URL}/{path}"
    try:
        resp = requests.delete(url, headers=_headers(access_token), timeout=30)
        data = resp.json()
    except requests.RequestException as e:
        raise ValueError(f"Network error calling Meta API: {e}")
    except ValueError:
        raise ValueError(f"Meta API returned non-JSON response (HTTP {resp.status_code}).")
    return data


def minor_to_display(minor: int) -> float:
    """Convert Meta minor units to display currency value."""
    return minor / 100


def display_to_minor(value: float) -> int:
    """Convert display currency value to Meta minor units (multiply by 100)."""
    return int(value * 100)


def _truncate(text: str) -> str:
    if len(text) > CHARACTER_LIMIT:
        return text[:CHARACTER_LIMIT] + "\n\n[Truncated — use filters or date ranges to narrow results]"
    return text


DATE_PRESETS = {
    "today": "today",
    "yesterday": "yesterday",
    "last_7d": "last_7d",
    "last_14d": "last_14d",
    "last_28d": "last_28d",
    "last_30d": "last_30d",
    "last_90d": "last_90d",
    "this_month": "this_month",
    "last_month": "last_month",
    "maximum": "maximum",
}


def _roas_flag(roas: float, spend: float = 0) -> str:
    if roas >= 3.0:
        return "🟢"
    if roas >= 1.5:
        return "🟡"
    if roas > 0 or spend > 0:
        return "🔴"
    return "⚪"


def _extract_action(actions: list, action_type: str, value_type: str = "value") -> float:
    for a in actions:
        if a.get("action_type") == action_type:
            return float(a.get(value_type, 0))
    return 0.0


def _minutes_to_utc_str(minutes: int) -> str:
    """Convert schedule_start_minute to a UTC time string."""
    h = (minutes // 60) % 24
    m = minutes % 60
    return f"{h:02d}:{m:02d} UTC"


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def get_user_ad_accounts(user_access_token: str) -> str:
    """
    Discover which ad accounts the authenticated user owns or has access to.
    Returns account name, act_ ID, and currency for each.

    Args:
        user_access_token: A valid user access token with ads_read permission.
    """
    try:
        data = _get(user_access_token, "me/adaccounts", params={
            "fields": "id,name,currency,account_status,timezone_name",
            "limit": 50,
        })
    except ValueError as e:
        return str(e)

    accounts = data.get("data", [])
    if not accounts:
        return "No ad accounts found for this user. The token may lack ads_read permission."

    status_map = {
        1: "Active", 2: "Disabled", 3: "Unsettled",
        7: "Pending Review", 9: "Grace Period", 201: "Closed",
    }

    lines = [f"# Ad Accounts ({len(accounts)} found)", ""]
    for acc in accounts:
        status = status_map.get(acc.get("account_status", 0), "Unknown")
        lines.extend([
            f"## {acc.get('name', 'Unnamed')}",
            f"- **ID:** `{acc.get('id')}`",
            f"- **Currency:** {acc.get('currency', 'N/A')}",
            f"- **Status:** {status}",
            f"- **Timezone:** {acc.get('timezone_name', 'N/A')}",
            "",
        ])

    return _truncate("\n".join(lines))


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def get_ad_insights(
    user_access_token: str,
    ad_account_id: str,
    time_preset: Literal["today", "yesterday", "last_7d", "last_14d", "last_30d", "this_month", "last_month", "maximum"] = "last_30d",
) -> str:
    """
    Fetch ad performance for an entire ad account broken down by publisher_platform.
    Shows Spend, Impressions, Clicks, CPC, and CTR per platform (Facebook, Instagram, etc.).

    Args:
        user_access_token: A valid access token with ads_read permission.
        ad_account_id: The ad account ID (with or without act_ prefix).
        time_preset: Time range for data. Default "last_30d".
    """
    if not ad_account_id.startswith("act_"):
        ad_account_id = f"act_{ad_account_id}"

    preset = DATE_PRESETS.get(time_preset, "last_30d")

    try:
        data = _get(user_access_token, f"{ad_account_id}/insights", params={
            "fields": "spend,impressions,clicks,cpc,ctr,date_start,date_stop",
            "date_preset": preset,
            "breakdowns": "publisher_platform",
        })
    except ValueError as e:
        return str(e)

    rows = data.get("data", [])
    if not rows:
        return f"No insights data for `{ad_account_id}` in **{time_preset}**."

    lines = [
        f"# Ad Account Insights — {ad_account_id}",
        f"**Period:** {time_preset} ({rows[0].get('date_start', '?')} → {rows[0].get('date_stop', '?')})",
        "",
        "| Platform | Spend | Impressions | Clicks | CPC | CTR |",
        "|----------|-------|-------------|--------|-----|-----|",
    ]

    total_spend = 0.0
    for row in rows:
        spend = float(row.get("spend", 0))
        total_spend += spend
        lines.append(
            f"| {row.get('publisher_platform', 'N/A')} "
            f"| {spend:,.2f} "
            f"| {int(row.get('impressions', 0)):,} "
            f"| {int(row.get('clicks', 0)):,} "
            f"| {float(row.get('cpc', 0)):,.2f} "
            f"| {float(row.get('ctr', 0)):.2f}% |"
        )

    lines.extend(["", f"**Total Spend:** {total_spend:,.2f}"])
    return _truncate("\n".join(lines))


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def get_ad_pixel_details(user_access_token: str, ad_id: str) -> str:
    """
    Fetch the tracking pixel associated with a specific ad.
    Parses tracking_specs to extract the pixel_id, then fetches Pixel Name and last_fired_time.

    Args:
        user_access_token: A valid access token with ads_read permission.
        ad_id: The ad ID to inspect.
    """
    try:
        ad_data = _get(user_access_token, ad_id, params={"fields": "name,tracking_specs"})
    except ValueError as e:
        return str(e)

    tracking_specs = ad_data.get("tracking_specs", [])
    pixel_id = None
    for spec in tracking_specs:
        if "fb_pixel" in spec:
            pixel_ids = spec["fb_pixel"]
            if isinstance(pixel_ids, list) and pixel_ids:
                pixel_id = pixel_ids[0]
            elif isinstance(pixel_ids, str):
                pixel_id = pixel_ids
            break

    if not pixel_id:
        return (
            f"No Facebook Pixel found in tracking_specs for ad `{ad_id}` "
            f"(\"{ad_data.get('name', 'Unnamed')}\"). "
            "The ad may use a dataset or no pixel tracking."
        )

    try:
        pixel_data = _get(user_access_token, pixel_id, params={"fields": "name,last_fired_time,id"})
    except ValueError as e:
        return f"Found pixel ID `{pixel_id}` but failed to fetch details: {e}"

    lines = [
        f"# Pixel Details for Ad: {ad_data.get('name', ad_id)}",
        "",
        f"**Pixel ID:** `{pixel_data.get('id')}`",
        f"**Pixel Name:** {pixel_data.get('name', 'N/A')}",
        f"**Last Fired:** {pixel_data.get('last_fired_time', 'Never / Unknown')}",
    ]
    return "\n".join(lines)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
def create_pixel(
    access_token: str,
    ad_account_id: str,
    pixel_name: str = "AI Pixel",
) -> str:
    """
    Create a new Meta Pixel on the ad account.

    Args:
        access_token: A valid access token with ads_management permission.
        ad_account_id: The ad account ID (numeric, without act_ prefix).
        pixel_name: Name for the new pixel (default: AI Pixel).
    """
    act_id = f"act_{ad_account_id}"
    try:
        result = _post(access_token, f"{act_id}/adspixels", {"name": pixel_name})
    except ValueError as e:
        return json.dumps({"error": str(e)})

    pixel_id = result.get("id")
    if not pixel_id:
        return json.dumps({"error": f"Pixel creation failed. Response: {json.dumps(result)}"})

    base_code = (
        "<!-- Meta Pixel Code -->\n"
        "<script>\n"
        "!function(f,b,e,v,n,t,s)\n"
        "{f.fbq||(n=f.fbq=function(){n.callMethod?\n"
        "n.callMethod.apply(n,arguments):n.queue.push(arguments)},\n"
        "f._fbq||(f._fbq=n),n.push=n,n.loaded=!0,n.version='2.0',\n"
        "n.queue=[],t=b.createElement(e),t.async=!0,\n"
        "t.src=v,s=b.getElementsByTagName(e)[0],\n"
        "s.parentNode.insertBefore(t,s))}(window, document,'script',\n"
        "'https://connect.facebook.net/en_US/fbevents.js');\n"
        f"fbq('init', '{pixel_id}');\n"
        "fbq('track', 'PageView');\n"
        "</script>\n"
        '<noscript><img height="1" width="1" style="display:none"\n'
        f'src="https://www.facebook.com/tr?id={pixel_id}&ev=PageView&noscript=1"\n'
        "/></noscript>\n"
        "<!-- End Meta Pixel Code -->"
    )

    return json.dumps({
        "pixel_id": pixel_id,
        "name": pixel_name,
        "base_code": base_code,
    })


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
def create_facebook_post(page_access_token: str, page_id: str, message: str) -> str:
    """
    Publish a text post to a Facebook Page.

    Args:
        page_access_token: A valid Page access token with pages_manage_posts permission.
        page_id: The Facebook Page ID to post to.
        message: The text content of the post.
    """
    if not message.strip():
        return "Error: message cannot be empty."

    try:
        result = _post(page_access_token, f"{page_id}/feed", {"message": message})
    except ValueError as e:
        return str(e)

    post_id = result.get("id")
    if post_id:
        return (
            f"Post published successfully.\n\n"
            f"**Post ID:** `{post_id}`\n"
            f"**Page ID:** `{page_id}`"
        )
    return f"Unexpected response (no post ID returned): {json.dumps(result)}"


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def get_page_analytics(page_access_token: str, page_id: str) -> str:
    """
    Fetch recent posts from a Facebook Page with their reach and engagement insights.

    Args:
        page_access_token: A valid Page access token with read_insights permission.
        page_id: The Facebook Page ID.
    """
    try:
       posts_data = _get(page_access_token, f"{page_id}/posts", params={
            "fields": "id,message,created_time,shares",
            "limit": 10,
        })
    except ValueError as e:
        return str(e)

    posts = posts_data.get("data", [])
    if not posts:
        return f"No posts found on page `{page_id}`."

    lines = [f"# Page Analytics — {page_id}", f"**Recent Posts:** {len(posts)}", ""]

    for post in posts:
        post_id = post.get("id")
        msg = (post.get("message") or "")[:80]
        if len(post.get("message", "")) > 80:
            msg += "..."
        shares = post.get("shares", {}).get("count", 0)

        # Fetch per-post insights
        reach = 0
        engagement = 0
        try:
            insights = _get(page_access_token, f"{post_id}/insights", params={
                "metric": "post_impressions_unique,post_engaged_users",
            })
            for metric in insights.get("data", []):
                name = metric.get("name")
                values = metric.get("values", [{}])
                val = values[0].get("value", 0) if values else 0
                if name == "post_impressions_unique":
                    reach = val
                elif name == "post_engaged_users":
                    engagement = val
        except ValueError:
            pass  # Insights may not be available for all posts

        lines.extend([
            f"## {post.get('created_time', 'N/A')[:10]}",
            f"- **Post ID:** `{post_id}`",
            f"- **Text:** {msg or '(no text)'}",
            f"- **Reach:** {reach:,}",
            f"- **Engaged Users:** {engagement:,}",
            f"- **Shares:** {shares}",
            "",
        ])

    return _truncate("\n".join(lines))


# ── Account Overview & Campaign Tools ──────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def get_account_overview(access_token: str, ad_account_id: str) -> str:
    """
    Get a high-level health snapshot of a Meta ad account.
    Shows account name, status, currency, timezone, lifetime spend, and active campaign count.

    Args:
        access_token: A valid access token with ads_read permission.
        ad_account_id: The ad account ID (numeric, without act_ prefix).
    """
    try:
        account = _get(
            access_token,
            f"act_{ad_account_id}",
            params={"fields": "name,currency,timezone_name,account_status,amount_spent,spend_cap,balance"},
        )
        campaigns = _get(
            access_token,
            f"act_{ad_account_id}/campaigns",
            params={
                "fields": "id,status",
                "filtering": '[{"field":"effective_status","operator":"IN","value":["ACTIVE"]}]',
                "limit": 100,
            },
        )
    except ValueError as e:
        return str(e)

    active_count = len(campaigns.get("data", []))
    currency = account.get("currency", "USD")

    status_map = {
        1: "Active", 2: "Disabled", 3: "Unsettled",
        7: "Pending Risk Review", 9: "In Grace Period", 201: "Closed",
    }
    status = status_map.get(account.get("account_status", 0), "Unknown")

    spent = int(account.get("amount_spent", 0))
    spend_cap = account.get("spend_cap")
    cap_str = f"{minor_to_display(int(spend_cap)):,.0f} {currency}" if spend_cap else "None set"

    lines = [
        f"# Ad Account Overview",
        "",
        f"**Account Name:** {account.get('name', 'N/A')}",
        f"**Status:** {status}",
        f"**Currency:** {currency}",
        f"**Timezone:** {account.get('timezone_name', 'N/A')}",
        "",
        "## Spend Summary",
        f"**Lifetime Spend:** {minor_to_display(spent):,.0f} {currency}",
        f"**Spend Cap:** {cap_str}",
        "",
        "## Active Campaigns",
        f"**Currently Active:** {active_count} campaign(s)",
    ]

    return _truncate("\n".join(lines))


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def list_campaigns(
    access_token: str,
    ad_account_id: str,
    status_filter: Literal["all", "active", "paused", "archived"] = "all",
    limit: int = 20,
) -> str:
    """
    List all campaigns in an ad account with status, objective, and budget info.

    Args:
        access_token: A valid access token with ads_read permission.
        ad_account_id: The ad account ID (numeric, without act_ prefix).
        status_filter: Filter by campaign status. Default "all".
        limit: Max campaigns to return (1–100). Default 20.
    """
    limit = max(1, min(100, limit))

    params: dict = {
        "fields": "id,name,status,effective_status,objective,daily_budget,lifetime_budget,created_time",
        "limit": limit,
    }
    if status_filter != "all":
        meta_status = {"active": "ACTIVE", "paused": "PAUSED", "archived": "ARCHIVED"}[status_filter]
        params["filtering"] = f'[{{"field":"effective_status","operator":"IN","value":["{meta_status}"]}}]'

    try:
        data = _get(access_token, f"act_{ad_account_id}/campaigns", params=params)
    except ValueError as e:
        return str(e)

    campaigns = data.get("data", [])
    if not campaigns:
        return f"No campaigns found with filter '{status_filter}'."

    currency = "—"
    # Attempt to get currency from account
    try:
        acc = _get(access_token, f"act_{ad_account_id}", params={"fields": "currency"})
        currency = acc.get("currency", "—")
    except ValueError:
        pass

    lines = [f"# Campaigns ({len(campaigns)} found — filter: {status_filter})", ""]

    for c in campaigns:
        daily = c.get("daily_budget")
        lifetime = c.get("lifetime_budget")
        if daily:
            budget_str = f"{minor_to_display(int(daily)):,.0f} {currency}/day"
        elif lifetime:
            budget_str = f"{minor_to_display(int(lifetime)):,.0f} {currency} lifetime"
        else:
            budget_str = "N/A (campaign budget optimization)"

        status = c.get("effective_status", c.get("status", "N/A"))
        status_icon = "✅" if status == "ACTIVE" else ("⏸️" if status == "PAUSED" else "📦")

        lines.extend([
            f"## {status_icon} {c.get('name', 'Unnamed')}",
            f"- **ID:** `{c.get('id')}`",
            f"- **Status:** {status}",
            f"- **Objective:** {c.get('objective', 'N/A')}",
            f"- **Budget:** {budget_str}",
            f"- **Created:** {c.get('created_time', 'N/A')[:10]}",
            "",
        ])

    if data.get("paging", {}).get("next"):
        lines.append("_More campaigns available. Increase `limit` to see more._")

    return _truncate("\n".join(lines))


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def get_campaign_insights(
    access_token: str,
    campaign_id: str,
    date_preset: Literal["today", "yesterday", "last_7d", "last_14d", "last_30d", "this_month", "last_month", "maximum"] = "last_7d",
    breakdown: Optional[Literal["day", "age", "gender", "placement"]] = None,
) -> str:
    """
    Get detailed performance insights for a specific campaign.
    Returns spend, ROAS, purchases, CTR, CPM, CPC, impressions, reach, and funnel data.

    Args:
        access_token: A valid access token with ads_read permission.
        campaign_id: The campaign ID.
        date_preset: Time range for data. Default "last_7d".
        breakdown: Optional breakdown. "day" shows a daily trend table.
    """
    preset = DATE_PRESETS.get(date_preset, "last_7d")

    params: dict = {
        "fields": ",".join([
            "campaign_name", "spend", "impressions", "reach", "clicks",
            "inline_link_clicks", "inline_link_click_ctr", "cpm", "cpc",
            "purchase_roas", "actions", "action_values", "cost_per_action_type",
            "frequency", "date_start", "date_stop",
        ]),
        "date_preset": preset,
        "level": "campaign",
    }

    if breakdown == "day":
        params["time_increment"] = 1
    elif breakdown in ("age", "gender", "placement"):
        params["breakdowns"] = breakdown

    try:
        data = _get(access_token, f"{campaign_id}/insights", params=params)
    except ValueError as e:
        return str(e)

    rows = data.get("data", [])
    if not rows:
        return (
            f"No data for campaign `{campaign_id}` in **{date_preset}**. "
            "The campaign may not have had delivery in this period."
        )

    if breakdown == "day":
        lines = [f"# Daily Performance — {rows[0].get('campaign_name', campaign_id)}", f"**Period:** {date_preset}", ""]
        total_spend = 0.0
        for row in rows:
            spend = float(row.get("spend", 0))
            total_spend += spend
            roas_list = row.get("purchase_roas", [])
            roas = float(roas_list[0].get("value", 0)) if roas_list else 0.0
            purchases = int(_extract_action(row.get("actions", []), "offsite_conversion.fb_pixel_purchase"))
            ctr = float(row.get("inline_link_click_ctr", 0))
            lines.append(
                f"**{row.get('date_start')}** — "
                f"Spend: {spend:,.0f} | ROAS: {_roas_flag(roas, spend)} {roas:.2f}x | "
                f"Purchases: {purchases} | CTR: {ctr:.2f}%"
            )
        lines.extend(["", f"**Total spend over period:** {total_spend:,.0f}"])
        return _truncate("\n".join(lines))

    row = rows[0]
    spend = float(row.get("spend", 0))
    impressions = int(row.get("impressions", 0))
    reach = int(row.get("reach", 0))
    link_clicks = int(row.get("inline_link_clicks", 0))
    ctr = float(row.get("inline_link_click_ctr", 0))
    cpm = float(row.get("cpm", 0))
    cpc = float(row.get("cpc", 0))
    frequency = float(row.get("frequency", 0))

    actions = row.get("actions", [])
    action_values = row.get("action_values", [])
    cost_per = row.get("cost_per_action_type", [])

    roas_list = row.get("purchase_roas", [])
    roas = float(roas_list[0].get("value", 0)) if roas_list else 0.0

    purchases = int(_extract_action(actions, "offsite_conversion.fb_pixel_purchase"))
    purchase_value = _extract_action(action_values, "offsite_conversion.fb_pixel_purchase")
    cost_per_purchase = _extract_action(cost_per, "offsite_conversion.fb_pixel_purchase")
    initiate_checkout = int(_extract_action(actions, "offsite_conversion.fb_pixel_initiate_checkout"))
    add_to_cart = int(_extract_action(actions, "offsite_conversion.fb_pixel_add_to_cart"))

    flag = _roas_flag(roas, spend)
    if roas >= 3.0:
        roas_note = "Scale eligible — above 3.0x threshold"
    elif roas >= 1.5:
        roas_note = "Profitable but below scale threshold"
    elif spend > 0 and purchases == 0:
        roas_note = "Zero purchases recorded — check pixel or kill underperforming ads"
    elif roas > 0:
        roas_note = "Below breakeven — review creative"
    else:
        roas_note = "No purchase data — verify pixel is firing"

    ctr_flag = "✅" if ctr >= 1.0 else ("⚠️" if ctr >= 0.5 else "❌")
    freq_flag = "⚠️ High" if frequency >= 3.5 else ("✅ Good" if frequency > 0 else "⚪")

    lines = [
        f"# Campaign Insights: {row.get('campaign_name', campaign_id)}",
        f"**Period:** {date_preset} ({row.get('date_start')} → {row.get('date_stop')})",
        "",
        "## Revenue & ROAS",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| **Purchase ROAS** | {flag} **{roas:.2f}x** — {roas_note} |",
        f"| Spend | {spend:,.0f} |",
        f"| Pixel Revenue | {purchase_value:,.0f} |",
        f"| Purchases | {purchases} |",
        f"| Cost per Purchase | {cost_per_purchase:,.0f} |",
        "",
        "## Funnel",
        f"| Stage | Count |",
        f"|-------|-------|",
        f"| Impressions | {impressions:,} |",
        f"| Reach | {reach:,} |",
        f"| Link Clicks | {link_clicks:,} |",
        f"| Add to Cart | {add_to_cart} |",
        f"| Initiate Checkout | {initiate_checkout} |",
        f"| Purchases | {purchases} |",
        "",
        "## Efficiency",
        f"| Metric | Value | Status |",
        f"|--------|-------|--------|",
        f"| CTR (link) | {ctr:.2f}% | {ctr_flag} (target ≥1%) |",
        f"| CPM | {cpm:,.0f} | — |",
        f"| CPC (link) | {cpc:,.0f} | — |",
        f"| Frequency | {frequency:.1f}x | {freq_flag} (pause creative if ≥3.5x) |",
    ]

    return _truncate("\n".join(lines))


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def list_ad_sets(
    access_token: str,
    campaign_id: str,
    date_preset: Literal["today", "yesterday", "last_7d", "last_30d", "maximum"] = "last_7d",
) -> str:
    """
    List all ad sets within a campaign with spend, ROAS, and budget.

    Args:
        access_token: A valid access token with ads_read permission.
        campaign_id: The campaign ID.
        date_preset: Time range for performance data. Default "last_7d".
    """
    preset = DATE_PRESETS.get(date_preset, "last_7d")

    try:
        adsets_data = _get(access_token, f"{campaign_id}/adsets", params={
            "fields": "id,name,status,effective_status,daily_budget,lifetime_budget,optimization_goal",
            "limit": 50,
        })
        ins_data = _get(access_token, f"{campaign_id}/insights", params={
            "fields": "adset_id,spend,purchase_roas,actions",
            "date_preset": preset,
            "level": "adset",
        })
    except ValueError as e:
        return str(e)

    adsets = adsets_data.get("data", [])
    if not adsets:
        return f"No ad sets found in campaign `{campaign_id}`."

    ins_map: dict = {}
    for row in ins_data.get("data", []):
        adset_id = row.get("adset_id")
        roas_list = row.get("purchase_roas", [])
        roas = float(roas_list[0].get("value", 0)) if roas_list else 0.0
        purchases = int(_extract_action(row.get("actions", []), "offsite_conversion.fb_pixel_purchase"))
        ins_map[adset_id] = {"spend": float(row.get("spend", 0)), "roas": roas, "purchases": purchases}

    lines = [f"# Ad Sets ({len(adsets)} found) — {date_preset}", ""]

    for adset in adsets:
        adset_id = adset["id"]
        ins = ins_map.get(adset_id, {})
        spend = ins.get("spend", 0.0)
        roas = ins.get("roas", 0.0)
        flag = _roas_flag(roas, spend)

        daily = adset.get("daily_budget")
        lifetime = adset.get("lifetime_budget")
        if daily:
            budget_str = f"{minor_to_display(int(daily)):,.0f}/day"
        elif lifetime:
            budget_str = f"{minor_to_display(int(lifetime)):,.0f} lifetime"
        else:
            budget_str = "Managed by campaign"

        status = adset.get("effective_status", adset.get("status", "N/A"))
        status_icon = "✅" if status == "ACTIVE" else "⏸️"

        lines.extend([
            f"## {status_icon} {adset.get('name', 'Unnamed')}",
            f"- **ID:** `{adset_id}`",
            f"- **Status:** {status}",
            f"- **Budget:** {budget_str}",
            f"- **Optimization:** {adset.get('optimization_goal', 'N/A')}",
            f"- **Spend ({date_preset}):** {spend:,.0f}",
            f"- **ROAS:** {flag} {roas:.2f}x",
            f"- **Purchases:** {ins.get('purchases', 0)}",
            "",
        ])

    lines.append("**Legend:** 🟢 ≥3x (scale) | 🟡 1.5–3x (hold) | 🔴 underperforming | ⚪ no data")
    return _truncate("\n".join(lines))


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def list_ads(
    access_token: str,
    campaign_id: str,
    date_preset: Literal["today", "yesterday", "last_7d", "last_30d", "maximum"] = "last_7d",
    status_filter: Literal["all", "active", "paused"] = "all",
) -> str:
    """
    List all ads in a campaign with individual performance. Flags kill candidates and scale winners.

    Args:
        access_token: A valid access token with ads_read permission.
        campaign_id: The campaign ID.
        date_preset: Time range for performance. Default "last_7d".
        status_filter: Filter by ad status. Default "all".
    """
    preset = DATE_PRESETS.get(date_preset, "last_7d")

    params: dict = {
        "fields": "id,name,status,effective_status",
        "limit": 50,
    }
    if status_filter != "all":
        meta_status = {"active": "ACTIVE", "paused": "PAUSED"}[status_filter]
        params["filtering"] = f'[{{"field":"effective_status","operator":"IN","value":["{meta_status}"]}}]'

    try:
        data = _get(access_token, f"{campaign_id}/ads", params=params)
        ins_data = _get(access_token, f"{campaign_id}/insights", params={
            "fields": "ad_id,ad_name,spend,inline_link_click_ctr,purchase_roas,actions,cost_per_action_type",
            "date_preset": preset,
            "level": "ad",
        })
    except ValueError as e:
        return str(e)

    ads = data.get("data", [])
    if not ads:
        return f"No ads found in campaign `{campaign_id}` with filter '{status_filter}'."

    ins_map: dict = {}
    for row in ins_data.get("data", []):
        ad_id = row.get("ad_id")
        roas_list = row.get("purchase_roas", [])
        roas = float(roas_list[0].get("value", 0)) if roas_list else 0.0
        purchases = int(_extract_action(row.get("actions", []), "offsite_conversion.fb_pixel_purchase"))
        cost_per_purchase = _extract_action(row.get("cost_per_action_type", []), "offsite_conversion.fb_pixel_purchase")
        ins_map[ad_id] = {
            "spend": float(row.get("spend", 0)),
            "ctr": float(row.get("inline_link_click_ctr", 0)),
            "roas": roas,
            "purchases": purchases,
            "cost_per_purchase": cost_per_purchase,
        }

    lines = [f"# Ads ({len(ads)} found) — {date_preset}", ""]

    for ad in ads:
        ad_id = ad["id"]
        ins = ins_map.get(ad_id, {})
        spend = ins.get("spend", 0.0)
        roas = ins.get("roas", 0.0)
        ctr = ins.get("ctr", 0.0)
        purchases = ins.get("purchases", 0)

        if roas >= 3.0:
            verdict = "🟢 SCALE"
        elif roas >= 1.5:
            verdict = "🟡 HOLD"
        elif spend >= 2000 and purchases == 0:
            verdict = "🔴 KILL CANDIDATE"
        elif spend > 0 and roas > 0:
            verdict = "🔴 UNDERPERFORMING"
        elif spend > 0:
            verdict = "🔴 ZERO PURCHASES"
        else:
            verdict = "⚪ NO DATA"

        ctr_flag = "✅" if ctr >= 1.0 else ("⚠️" if ctr >= 0.5 else "❌")
        status = ad.get("effective_status", ad.get("status", "N/A"))

        lines.extend([
            f"## {verdict} — {ad.get('name', 'Unnamed')}",
            f"- **ID:** `{ad_id}`",
            f"- **Status:** {status}",
            f"- **Spend:** {spend:,.0f}",
            f"- **ROAS:** {roas:.2f}x",
            f"- **Purchases:** {purchases} @ {ins.get('cost_per_purchase', 0):,.0f} each",
            f"- **CTR:** {ctr_flag} {ctr:.2f}%",
            "",
        ])

    lines.extend([
        "**Legend:** 🟢 SCALE | 🟡 HOLD | 🔴 Action needed | ⚪ No data",
        "**CTR:** ✅ ≥1% | ⚠️ 0.5–1% | ❌ <0.5%",
    ])

    return _truncate("\n".join(lines))


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def get_daily_spend(
    access_token: str,
    campaign_id: str,
    date_preset: Literal["last_7d", "last_14d", "last_30d", "this_month"] = "last_7d",
) -> str:
    """
    Get a daily spend table for a campaign.

    Args:
        access_token: A valid access token with ads_read permission.
        campaign_id: The campaign ID.
        date_preset: Time range. Default "last_7d".
    """
    preset = DATE_PRESETS.get(date_preset, "last_7d")

    try:
        data = _get(access_token, f"{campaign_id}/insights", params={
            "fields": "campaign_name,spend,impressions,inline_link_clicks,actions",
            "date_preset": preset,
            "time_increment": 1,
            "level": "campaign",
        })
    except ValueError as e:
        return str(e)

    rows = data.get("data", [])
    if not rows:
        return f"No spend data for campaign `{campaign_id}` in {date_preset}."

    campaign_name = rows[0].get("campaign_name", campaign_id)
    total_spend = sum(float(r.get("spend", 0)) for r in rows)

    lines = [
        f"# Daily Spend: {campaign_name}",
        f"**Period:** {date_preset} | **Total:** {total_spend:,.0f}",
        "",
        "| Date | Spend | Impressions | Clicks | Purchases |",
        "|------|-------|-------------|--------|-----------|",
    ]

    for row in rows:
        spend = float(row.get("spend", 0))
        impressions = int(row.get("impressions", 0))
        clicks = int(row.get("inline_link_clicks", 0))
        purchases = int(_extract_action(row.get("actions", []), "offsite_conversion.fb_pixel_purchase"))
        lines.append(f"| {row.get('date_start')} | {spend:,.0f} | {impressions:,} | {clicks} | {purchases} |")

    return _truncate("\n".join(lines))


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def get_creative(access_token: str, ad_id: str) -> str:
    """
    Get the creative details for a specific ad — copy, headline, description, CTA, and media info.

    Args:
        access_token: A valid access token with ads_read permission.
        ad_id: The ad ID.
    """
    try:
        ad_data = _get(access_token, ad_id, params={
            "fields": "name,effective_status,creative{id,name,title,body,object_story_spec,image_url,thumbnail_url,call_to_action_type}"
        })
    except ValueError as e:
        return str(e)

    creative = ad_data.get("creative", {})
    if not creative:
        return f"No creative data found for ad `{ad_id}`."

    story_spec = creative.get("object_story_spec", {})
    link_data = story_spec.get("link_data", {})
    video_data = story_spec.get("video_data", {})

    headline = creative.get("title") or link_data.get("name") or video_data.get("title") or "N/A"
    body = creative.get("body") or link_data.get("message") or video_data.get("message") or "N/A"
    description = link_data.get("description") or video_data.get("link_description") or "N/A"
    cta = creative.get("call_to_action_type") or "N/A"

    lines = [
        f"# Ad Creative: {ad_data.get('name', ad_id)}",
        f"**Ad Status:** {ad_data.get('effective_status', 'N/A')}",
        f"**Creative ID:** `{creative.get('id')}`",
        "",
        "## Copy",
        f"**Headline:** {headline}",
        f"**Body/Caption:** {body}",
        f"**Description:** {description}",
        f"**CTA Button:** {cta}",
        "",
        "## Media",
        f"**Image URL:** {creative.get('image_url') or 'N/A (may be video)'}",
        f"**Thumbnail URL:** {creative.get('thumbnail_url') or 'N/A'}",
    ]

    return _truncate("\n".join(lines))


# ── Action Tools ───────────────────────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
def pause_entity(
    access_token: str,
    entity_id: str,
    entity_type: Literal["ad", "adset", "campaign"],
) -> str:
    """
    Pause an ad, ad set, or campaign. Reversible with enable_entity.

    Args:
        access_token: A valid access token with ads_management permission.
        entity_id: The ID of the entity to pause.
        entity_type: Whether this is an "ad", "adset", or "campaign".
    """
    try:
        result = _post(access_token, entity_id, {"status": "PAUSED"})
    except ValueError as e:
        return str(e)

    if result.get("success"):
        return f"{entity_type.capitalize()} `{entity_id}` paused successfully."
    return f"Failed to pause {entity_type} `{entity_id}`. Response: {json.dumps(result)}"


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
def enable_entity(
    access_token: str,
    entity_id: str,
    entity_type: Literal["ad", "adset", "campaign"],
) -> str:
    """
    Resume (enable) a paused ad, ad set, or campaign.

    Args:
        access_token: A valid access token with ads_management permission.
        entity_id: The ID of the entity to enable.
        entity_type: Whether this is an "ad", "adset", or "campaign".
    """
    try:
        result = _post(access_token, entity_id, {"status": "ACTIVE"})
    except ValueError as e:
        return str(e)

    if result.get("success"):
        return f"{entity_type.capitalize()} `{entity_id}` enabled successfully."
    return f"Failed to enable {entity_type} `{entity_id}`. Response: {json.dumps(result)}"


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
def update_daily_budget(
    access_token: str,
    adset_id: str,
    new_budget: float,
) -> str:
    """
    Update the daily budget for an ad set. Provide the budget in the account's display currency.

    Args:
        access_token: A valid access token with ads_management permission.
        adset_id: The ad set ID to update.
        new_budget: New daily budget in display currency units (e.g. 5000 = 5,000 in account currency).
    """
    if new_budget <= 0:
        return "Error: Budget must be greater than 0."

    budget_minor = display_to_minor(new_budget)

    try:
        result = _post(access_token, adset_id, {"daily_budget": budget_minor})
    except ValueError as e:
        return str(e)

    if result.get("success"):
        return f"Budget updated for ad set `{adset_id}` to {new_budget:,.0f}/day."
    return f"Failed to update budget. Response: {json.dumps(result)}"


# ── Automated Rules ────────────────────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def list_automated_rules(access_token: str, ad_account_id: str, limit: int = 25) -> str:
    """
    List all automated rules on an ad account.

    Args:
        access_token: A valid access token with ads_management permission.
        ad_account_id: The ad account ID (numeric, without act_ prefix).
        limit: Max rules to return (1–50). Default 25.
    """
    limit = max(1, min(50, limit))

    try:
        data = _get(access_token, f"act_{ad_account_id}/adrules_library", params={
            "fields": "id,name,status,evaluation_spec,filter_spec,execution_spec,created_time,updated_time",
            "limit": limit,
        })
    except ValueError as e:
        return str(e)

    rules = data.get("data", [])
    if not rules:
        return "No automated rules found on this ad account."

    lines = [f"# Automated Rules ({len(rules)} found)", ""]

    for rule in rules:
        status = rule.get("status", "N/A")
        status_icon = "✅" if status == "ENABLED" else "⏸️"

        exec_spec = rule.get("execution_spec", {})
        exec_type = exec_spec.get("execution_type", "N/A")
        exec_value = exec_spec.get("execution_value", "")
        exec_options = exec_spec.get("execution_options", [])

        if exec_type == "PAUSE":
            action = "Pause entity"
        elif exec_type == "CHANGE_BUDGET":
            if "PERCENTAGE_INCREASE" in exec_options:
                action = f"Increase budget by {exec_value}%"
            elif "PERCENTAGE_DECREASE" in exec_options:
                action = f"Decrease budget by {exec_value}%"
            else:
                action = f"Change budget by {exec_value}"
        elif exec_type == "REACTIVATE":
            action = "Re-enable entity"
        else:
            action = exec_type

        eval_spec = rule.get("evaluation_spec", {})
        schedule = eval_spec.get("schedule_spec", {})
        start_min = schedule.get("schedule_start_minute", 0)
        schedule_str = f"{schedule.get('schedule_type', 'N/A')} at {_minutes_to_utc_str(start_min)}"

        lines.extend([
            f"## {status_icon} {rule.get('name', 'Unnamed Rule')}",
            f"- **ID:** `{rule.get('id')}`",
            f"- **Status:** {status}",
            f"- **Action:** {action}",
            f"- **Schedule:** {schedule_str}",
            f"- **Created:** {rule.get('created_time', 'N/A')[:10]}",
            f"- **Updated:** {rule.get('updated_time', 'N/A')[:10]}",
            "",
        ])

    return _truncate("\n".join(lines))


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
def create_kill_rule(
    access_token: str,
    ad_account_id: str,
    campaign_id: str,
    spend_threshold: float = 4000,
    schedule_minute_utc: int = 180,
    rule_name: Optional[str] = None,
) -> str:
    """
    Create an automated rule that pauses any ad which has spent over a threshold with zero purchases.

    Args:
        access_token: A valid access token with ads_management permission.
        ad_account_id: The ad account ID (numeric, without act_ prefix).
        campaign_id: Apply the rule to ads within this campaign.
        spend_threshold: Spend threshold in display currency before pausing. Default 4000.
        schedule_minute_utc: Minute of day (UTC) to run the rule. Default 180 (03:00 UTC).
        rule_name: Custom name. Auto-generated if not provided.
    """
    name = rule_name or f"Kill Zero-Purchase Ads (spend >= {spend_threshold:,.0f})"

    payload = {
        "name": name,
        "evaluation_spec": {
            "evaluation_type": "SCHEDULE",
            "schedule_spec": {
                "schedule_type": "DAILY",
                "schedule_start_minute": schedule_minute_utc,
            },
        },
        "filter_spec": {
            "filters": [
                {"field": "entity_type", "operator": "EQUAL", "value": "AD"},
                {"field": "campaign_id", "operator": "EQUAL", "value": campaign_id},
                {"field": "ad_status", "operator": "EQUAL", "value": "ACTIVE"},
                {"field": "spend", "operator": "GREATER_THAN", "value": display_to_minor(spend_threshold)},
                {"field": "actions:offsite_conversion.fb_pixel_purchase", "operator": "EQUAL", "value": 0},
            ]
        },
        "execution_spec": {"execution_type": "PAUSE"},
        "execution_options": ["IGNORE_ERRORS"],
        "status": "ENABLED",
    }

    try:
        result = _post(access_token, f"act_{ad_account_id}/adrules_library", payload)
    except ValueError as e:
        return str(e)

    rule_id = result.get("id")
    if rule_id:
        return (
            f"Kill rule created.\n\n"
            f"**Rule ID:** `{rule_id}`\n"
            f"**Name:** {name}\n"
            f"**Schedule:** Daily at {_minutes_to_utc_str(schedule_minute_utc)}\n"
            f"**Action:** Pause ads in campaign `{campaign_id}` with spend >= {spend_threshold:,.0f} and zero purchases."
        )
    return f"Failed to create kill rule. Response: {json.dumps(result)}"


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
def create_scale_rule(
    access_token: str,
    ad_account_id: str,
    campaign_id: str,
    roas_threshold: float = 3.0,
    budget_increase_percent: int = 15,
    schedule_minute_utc: int = 180,
    rule_name: Optional[str] = None,
) -> str:
    """
    Create an automated rule that increases daily budget by a % when ROAS exceeds a threshold.

    Args:
        access_token: A valid access token with ads_management permission.
        ad_account_id: The ad account ID (numeric, without act_ prefix).
        campaign_id: Apply the rule to ad sets within this campaign.
        roas_threshold: ROAS that triggers scaling. Default 3.0.
        budget_increase_percent: Percentage to increase daily budget by. Default 15.
        schedule_minute_utc: Minute of day (UTC) to run the rule. Default 180 (03:00 UTC).
        rule_name: Custom name. Auto-generated if not provided.
    """
    name = rule_name or f"Scale ROAS >= {roas_threshold}x -> +{budget_increase_percent}%"

    payload = {
        "name": name,
        "evaluation_spec": {
            "evaluation_type": "SCHEDULE",
            "schedule_spec": {
                "schedule_type": "DAILY",
                "schedule_start_minute": schedule_minute_utc,
            },
        },
        "filter_spec": {
            "filters": [
                {"field": "entity_type", "operator": "EQUAL", "value": "ADSET"},
                {"field": "campaign_id", "operator": "EQUAL", "value": campaign_id},
                {"field": "adset_status", "operator": "EQUAL", "value": "ACTIVE"},
                {"field": "purchase_roas", "operator": "GREATER_THAN", "value": roas_threshold},
            ]
        },
        "execution_spec": {
            "execution_type": "CHANGE_BUDGET",
            "execution_value": budget_increase_percent,
            "execution_options": ["PERCENTAGE_INCREASE"],
        },
        "execution_options": ["IGNORE_ERRORS"],
        "limit_per_day": 1,
        "status": "ENABLED",
    }

    try:
        result = _post(access_token, f"act_{ad_account_id}/adrules_library", payload)
    except ValueError as e:
        return str(e)

    rule_id = result.get("id")
    if rule_id:
        return (
            f"Scale rule created.\n\n"
            f"**Rule ID:** `{rule_id}`\n"
            f"**Name:** {name}\n"
            f"**Schedule:** Daily at {_minutes_to_utc_str(schedule_minute_utc)}\n"
            f"**Action:** Increase budget by {budget_increase_percent}% for ad sets in campaign `{campaign_id}` with ROAS >= {roas_threshold}x.\n"
            f"**Limit:** 1 increase per ad set per day."
        )
    return f"Failed to create scale rule. Response: {json.dumps(result)}"


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
def toggle_automated_rule(
    access_token: str,
    rule_id: str,
    action: Literal["enable", "disable"],
) -> str:
    """
    Enable or disable an automated rule without deleting it.

    Args:
        access_token: A valid access token with ads_management permission.
        rule_id: The rule ID.
        action: "enable" to activate, "disable" to pause the rule.
    """
    status = "ENABLED" if action == "enable" else "DISABLED"

    try:
        result = _post(access_token, rule_id, {"status": status})
    except ValueError as e:
        return str(e)

    if result.get("success"):
        return f"Rule `{rule_id}` has been {action}d successfully."
    return f"Failed to {action} rule `{rule_id}`. Response: {json.dumps(result)}"


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True})
def delete_automated_rule(access_token: str, rule_id: str, confirm: bool = False) -> str:
    """
    Permanently delete an automated rule. Cannot be undone.
    Must pass confirm=True to actually delete — dry run by default.

    Args:
        access_token: A valid access token with ads_management permission.
        rule_id: The rule ID to delete.
        confirm: Must be True to confirm permanent deletion.
    """
    if not confirm:
        return (
            f"Confirmation required. You are about to permanently delete rule `{rule_id}`. "
            f"Call again with `confirm=True` to proceed."
        )

    try:
        result = _delete(access_token, rule_id)
    except ValueError as e:
        return str(e)

    if result.get("success"):
        return f"Rule `{rule_id}` has been permanently deleted."
    return f"Failed to delete rule `{rule_id}`. Response: {json.dumps(result)}"


# ── Campaign Creation (Full Funnel) ───────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
def create_meta_ad_campaign(
    access_token: str,
    ad_account_id: str,
    campaign_name: str,
    daily_budget: float,
    headline: str,
    body_text: str,
    link_url: str,
    image_url: Optional[str] = None,
    cta_type: str = "LEARN_MORE",
    objective: str = "OUTCOME_TRAFFIC",
    targeting: Optional[str] = None,
    page_id: Optional[str] = None,
) -> str:
    """
    Create a complete Meta ad funnel: Campaign → Ad Set → Ad Creative → Ad.

    This tool handles the full sequential creation flow. All entities are created
    in PAUSED status so the advertiser can review before going live.

    Args:
        access_token: A valid access token with ads_management permission.
        ad_account_id: The ad account ID (without 'act_' prefix).
        campaign_name: Name for the campaign.
        daily_budget: Daily budget in dollars (converted to cents internally).
        headline: Ad headline text.
        body_text: Primary ad copy / body text.
        link_url: Destination URL when user clicks the ad.
        image_url: URL of the ad image. If omitted, a link-only ad is created.
        cta_type: Call-to-action button type (e.g., LEARN_MORE, SHOP_NOW, SIGN_UP).
        objective: Campaign objective (OUTCOME_TRAFFIC, OUTCOME_AWARENESS, OUTCOME_ENGAGEMENT, OUTCOME_SALES).
        targeting: JSON string of Meta targeting spec. If omitted, broad targeting is used.
        page_id: Facebook Page ID to publish the ad from. Required for most ad formats.

    Returns:
        JSON summary with campaign_id, adset_id, creative_id, and ad_id.
    """
    act = f"act_{ad_account_id}" if not ad_account_id.startswith("act_") else ad_account_id
    budget_cents = display_to_minor(daily_budget)

    # Parse targeting or use broad defaults
    if targeting:
        try:
            targeting_spec = json.loads(targeting) if isinstance(targeting, str) else targeting
        except (json.JSONDecodeError, TypeError):
            return "Error: `targeting` must be a valid JSON string."
    else:
        targeting_spec = {
            "age_min": 18,
            "age_max": 65,
            "geo_locations": {"countries": ["US"]},
        }

    results = {}

    # ── Step 1: Create Campaign ──────────────────────────────────────────────
    try:
        campaign = _post(access_token, f"{act}/campaigns", {
            "name": campaign_name,
            "objective": objective,
            "status": "PAUSED",
            "special_ad_categories": [],
            "is_adset_budget_sharing_enabled": False,
        })
        results["campaign_id"] = campaign["id"]
    except ValueError as e:
        return f"Failed to create campaign: {e}"

    # ── Step 2: Create Ad Set ────────────────────────────────────────────────
    targeting_spec["targeting_automation"] = {"advantage_audience": 0}
    try:
        adset = _post(access_token, f"{act}/adsets", {
            "name": f"{campaign_name} — Ad Set",
            "campaign_id": results["campaign_id"],
            "daily_budget": budget_cents,
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "LINK_CLICKS",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "targeting": targeting_spec,
            "destination_type": "WEBSITE",
            "status": "PAUSED",
        })
        results["adset_id"] = adset["id"]
    except ValueError as e:
        return f"Campaign created ({results['campaign_id']}) but ad set failed: {e}"

    # ── Step 3: Create Ad Creative ───────────────────────────────────────────
    creative_data: dict = {
        "name": f"{campaign_name} — Creative",
        "object_story_spec": {
            "link_data": {
                "link": link_url,
                "message": body_text,
                "name": headline,
                "call_to_action": {"type": cta_type},
            },
        },
    }
    if page_id:
        creative_data["object_story_spec"]["page_id"] = page_id
    if image_url:
        creative_data["object_story_spec"]["link_data"]["picture"] = image_url

    try:
        creative = _post(access_token, f"{act}/adcreatives", creative_data)
        results["creative_id"] = creative["id"]
    except ValueError as e:
        return f"Campaign + Ad Set created but creative failed: {e}. IDs so far: {json.dumps(results)}"

    # ── Step 4: Create Ad ────────────────────────────────────────────────────
    try:
        ad = _post(access_token, f"{act}/ads", {
            "name": f"{campaign_name} — Ad",
            "adset_id": results["adset_id"],
            "creative": {"creative_id": results["creative_id"]},
            "status": "PAUSED",
        })
        results["ad_id"] = ad["id"]
    except ValueError as e:
        return f"Campaign + Ad Set + Creative created but ad failed: {e}. IDs so far: {json.dumps(results)}"

    return json.dumps({
        "success": True,
        "message": f"Full ad funnel created in PAUSED status. Enable the campaign to go live.",
        **results,
    })


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
