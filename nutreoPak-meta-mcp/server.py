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

    hint = ""
    if code == 190:
        hint = " Hint: The access token is expired or invalid. The user needs to re-authenticate."
    elif code == 100:
        hint = " Hint: A required permission is missing, or a parameter is invalid. Check the token's granted scopes."
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
    try:
        resp = requests.post(
            url,
            headers={**_headers(access_token), "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=30,
        )
        data = resp.json()
    except requests.RequestException as e:
        raise ValueError(f"Network error calling Meta API: {e}")
    except ValueError:
        raise ValueError(f"Meta API returned non-JSON response (HTTP {resp.status_code}).")
    if "error" in data:
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
    "last_7d": "last_7_d",
    "last_14d": "last_14_d",
    "last_30d": "last_30_d",
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

    preset = DATE_PRESETS.get(time_preset, "last_30_d")

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
    preset = DATE_PRESETS.get(date_preset, "last_7_d")

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
    preset = DATE_PRESETS.get(date_preset, "last_7_d")

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
    preset = DATE_PRESETS.get(date_preset, "last_7_d")

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
    preset = DATE_PRESETS.get(date_preset, "last_7_d")

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
    objective: str = "OUTCOME_SALES",
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
        })
        results["campaign_id"] = campaign["id"]
    except ValueError as e:
        return f"Failed to create campaign: {e}"

    # ── Step 2: Create Ad Set ────────────────────────────────────────────────
    try:
        adset = _post(access_token, f"{act}/adsets", {
            "name": f"{campaign_name} — Ad Set",
            "campaign_id": results["campaign_id"],
            "daily_budget": budget_cents,
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "OFFSITE_CONVERSIONS",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "targeting": targeting_spec,
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


# ── Account Audit Tool ─────────────────────────────────────────────────────────

@mcp.tool()
def get_account_audit_data(
    access_token: str,
    ad_account_id: str,
    date_preset: str = "last_30d",
) -> str:
    """
    Fetch ad-level performance data for an account audit.
    Returns spend, ROAS, CTR, and cost-per-action for every ad in the last 30 days.
    Used by the SaaS backend to build AI-powered account health reports.
    """
    fields = "ad_name,ad_id,spend,impressions,clicks,actions,cost_per_action_type,ctr"
    params = {
        "level": "ad",
        "date_preset": date_preset,
        "fields": fields,
        "limit": "200",
    }
    data = _get(access_token, f"act_{ad_account_id}/insights", params)
    rows = data.get("data", [])

    cleaned = []
    for row in rows:
        actions = row.get("actions") or []
        purchases = sum(
            int(a.get("value", 0))
            for a in actions
            if a.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase")
        )
        cost_per_action = row.get("cost_per_action_type") or []
        cpa = next(
            (float(c["value"]) for c in cost_per_action if c.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase")),
            None,
        )
        spend = float(row.get("spend", 0))
        roas = (purchases * (cpa or 0)) / spend if spend > 0 and cpa else None

        cleaned.append({
            "ad_id": row.get("ad_id"),
            "ad_name": row.get("ad_name"),
            "spend": spend,
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "ctr": float(row.get("ctr", 0)),
            "purchases": purchases,
            "cost_per_purchase": cpa,
            "roas": round(roas, 2) if roas else None,
        })

    total_spend = sum(r["spend"] for r in cleaned)
    total_purchases = sum(r["purchases"] for r in cleaned)
    avg_roas = round(total_spend / sum(r.get("cost_per_purchase", 0) or 0 for r in cleaned if r["purchases"] > 0), 2) if total_purchases > 0 else None

    return json.dumps({
        "total_spend": round(total_spend, 2),
        "total_purchases": total_purchases,
        "avg_roas": avg_roas,
        "ad_count": len(cleaned),
        "ads": cleaned,
    })[:CHARACTER_LIMIT]


# ── Pixel Tools ───────────────────────────────────────────────────────────────

@mcp.tool()
def fetch_ad_account_pixels(
    access_token: str,
    ad_account_id: str,
) -> str:
    """
    List all Meta Pixels available on an ad account.

    Args:
        access_token: Valid access token with ads_management permission.
        ad_account_id: The ad account ID (without 'act_' prefix).

    Returns:
        JSON array of pixels: [{id, name}].
    """
    act = f"act_{ad_account_id}" if not ad_account_id.startswith("act_") else ad_account_id
    try:
        data = _get(access_token, f"{act}/adspixels", {"fields": "id,name"})
    except ValueError as e:
        return json.dumps({"error": str(e)})

    pixels = [
        {"id": p["id"], "name": p.get("name", f"Pixel {p['id']}")}
        for p in data.get("data", [])
    ]
    return json.dumps(pixels)


@mcp.tool()
def fetch_pixel_performance(
    access_token: str,
    pixel_id: str,
    ad_account_id: str,
    date_preset: str = "last_7d",
) -> str:
    """
    Get conversion performance data attributed to a specific Meta Pixel.

    Fetches ad-level insights filtered to purchase conversions tracked by the pixel,
    returning ROAS and total purchase value for the specified time window.

    Args:
        access_token: Valid access token with ads_management permission.
        pixel_id: The Meta Pixel ID to filter by.
        ad_account_id: The ad account ID (without 'act_' prefix).
        date_preset: Time range (default "last_7d").

    Returns:
        JSON with total_spend, total_purchase_value, roas, and per-ad breakdown.
    """
    act = f"act_{ad_account_id}" if not ad_account_id.startswith("act_") else ad_account_id
    try:
        data = _get(access_token, f"{act}/insights", {
            "level": "ad",
            "date_preset": date_preset,
            "fields": "ad_id,ad_name,spend,actions,action_values",
            "filtering": json.dumps([{
                "field": "action_type",
                "operator": "IN",
                "value": ["offsite_conversion.fb_pixel_purchase"],
            }]),
            "limit": "100",
        })
    except ValueError as e:
        return json.dumps({"error": str(e)})

    rows = data.get("data", [])
    ads = []
    total_spend = 0.0
    total_purchase_value = 0.0

    for row in rows:
        spend = float(row.get("spend", 0))
        total_spend += spend

        # Extract purchase values
        purchase_value = 0.0
        for av in (row.get("action_values") or []):
            if av.get("action_type") in ("offsite_conversion.fb_pixel_purchase", "purchase"):
                purchase_value += float(av.get("value", 0))
        total_purchase_value += purchase_value

        # Extract purchase count
        purchases = 0
        for a in (row.get("actions") or []):
            if a.get("action_type") in ("offsite_conversion.fb_pixel_purchase", "purchase"):
                purchases += int(a.get("value", 0))

        ads.append({
            "ad_id": row.get("ad_id"),
            "ad_name": row.get("ad_name"),
            "spend": spend,
            "purchases": purchases,
            "purchase_value": purchase_value,
        })

    roas = round(total_purchase_value / total_spend, 2) if total_spend > 0 else None

    return json.dumps({
        "pixel_id": pixel_id,
        "date_preset": date_preset,
        "total_spend": round(total_spend, 2),
        "total_purchase_value": round(total_purchase_value, 2),
        "roas": roas,
        "ad_count": len(ads),
        "ads": ads,
    })


# ── Targeting & Research Tools ─────────────────────────────────────────────────

@mcp.tool()
def validate_meta_interests(
    access_token: str,
    keywords_json: str,
    min_audience: int = 1_000_000,
    max_audience: int = 15_000_000,
) -> str:
    """
    Validate keywords against Meta's ad interest taxonomy.

    Searches each keyword via the Graph API adinterest search and returns only
    interests whose audience_size falls within the given range.

    Args:
        access_token: Valid access token with ads_management permission.
        keywords_json: JSON array of keyword strings, e.g. '["fitness", "honey"]'.
        min_audience: Minimum audience size to include (default 1M).
        max_audience: Maximum audience size to include (default 15M).

    Returns:
        JSON array of validated interests: [{id, name, audience_size}].
    """
    try:
        keywords = json.loads(keywords_json) if isinstance(keywords_json, str) else keywords_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "keywords_json must be a valid JSON array of strings."})

    valid = []
    for kw in keywords:
        try:
            data = _get(access_token, "search", {"type": "adinterest", "q": kw})
            for item in data.get("data", []):
                size = item.get("audience_size", 0)
                if min_audience <= size <= max_audience:
                    valid.append({
                        "id": item["id"],
                        "name": item["name"],
                        "audience_size": size,
                    })
        except ValueError:
            # Skip keywords that cause Meta API errors (permissions, bad params)
            continue

    return json.dumps(valid)


@mcp.tool()
def resolve_geo_locations(
    access_token: str,
    cities_json: str,
    country_code: str = "PK",
) -> str:
    """
    Resolve city names to Meta geo-location keys and build a targeting geo spec.

    Args:
        access_token: Valid access token.
        cities_json: JSON array of city name strings, e.g. '["Karachi", "Lahore"]'.
        country_code: ISO country code for country-level targeting (default "PK").

    Returns:
        JSON geo_locations spec: {cities: [{key, name}], countries: [code]}.
    """
    try:
        cities = json.loads(cities_json) if isinstance(cities_json, str) else cities_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "cities_json must be a valid JSON array of strings."})

    resolved = []
    for city_name in cities:
        try:
            data = _get(access_token, "search", {
                "type": "adgeolocation",
                "location_types": "city",
                "q": city_name,
            })
            results = data.get("data", [])
            if results:
                hit = results[0]
                resolved.append({"key": hit["key"], "name": hit.get("name", city_name)})
        except ValueError:
            continue

    geo: dict = {"countries": [country_code]}
    if resolved:
        geo["cities"] = resolved

    return json.dumps(geo)


@mcp.tool()
def fetch_competitor_ads(
    access_token: str,
    keywords_json: str,
    country_code: str = "PK",
    limit: int = 10,
) -> str:
    """
    Fetch active competitor ads from the Meta Ad Library for market research.

    Searches the Ad Library for each keyword and extracts ad copy, media format,
    and call-to-action data from active ads.

    Args:
        access_token: Valid access token with ads_read permission.
        keywords_json: JSON array of search term strings.
        country_code: ISO country code to filter by reach (default "PK").
        limit: Max ads to return per keyword (default 10).

    Returns:
        JSON array of competitor ad summaries: [{body, headline, caption, cta, media_type, keyword}].
    """
    try:
        keywords = json.loads(keywords_json) if isinstance(keywords_json, str) else keywords_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "keywords_json must be a valid JSON array of strings."})

    ads = []
    for kw in keywords:
        try:
            data = _get(access_token, "ads_archive", {
                "search_terms": kw,
                "ad_reached_countries": json.dumps([country_code]),
                "ad_active_status": "ACTIVE",
                "fields": "ad_creative_bodies,ad_creative_link_titles,ad_creative_link_captions,call_to_action_type,media_type",
                "limit": str(limit),
            })
            for item in data.get("data", []):
                bodies = item.get("ad_creative_bodies", [])
                titles = item.get("ad_creative_link_titles", [])
                captions = item.get("ad_creative_link_captions", [])
                ads.append({
                    "body": bodies[0] if bodies else "",
                    "headline": titles[0] if titles else "",
                    "caption": captions[0] if captions else "",
                    "cta": item.get("call_to_action_type", ""),
                    "media_type": item.get("media_type", ""),
                    "keyword": kw,
                })
        except ValueError:
            # Ad Library access may fail due to permissions — skip gracefully
            continue

    return json.dumps(ads)[:CHARACTER_LIMIT]


@mcp.tool()
def stage_advanced_campaign(
    access_token: str,
    ad_account_id: str,
    campaign_name: str,
    daily_budget: float,
    headline: str,
    body_text: str,
    link_url: str,
    targeting_json: str,
    image_url: Optional[str] = None,
    cta_type: str = "SHOP_NOW",
    page_id: Optional[str] = None,
    pixel_id: Optional[str] = None,
    whatsapp_number: Optional[str] = None,
) -> str:
    """
    Create an Advantage+-enabled campaign funnel with smart Pixel/WhatsApp routing.

    **FLOW A (Pixel provided):** OUTCOME_SALES → OFFSITE_CONVERSIONS with pixel
    tracking in the ad set's promoted_object.

    **FLOW B (No Pixel — WhatsApp/COD fallback):** OUTCOME_ENGAGEMENT →
    CONVERSATIONS destination WHATSAPP, optimized for messaging-based orders.

    Builds Campaign → Ad Set → Creative → Ad, all in PAUSED status.

    Args:
        access_token: Valid access token with ads_management permission.
        ad_account_id: The ad account ID (without 'act_' prefix).
        campaign_name: Name for the campaign.
        daily_budget: Daily budget in dollars (converted to cents internally).
        headline: Ad headline text.
        body_text: Primary ad copy / body text.
        link_url: Destination URL when user clicks the ad.
        targeting_json: JSON string of targeting spec (geo_locations, flexible_spec, etc.).
        image_url: URL of the ad image. If omitted, a link-only ad is created.
        cta_type: Call-to-action button type (default SHOP_NOW).
        page_id: Facebook Page ID to publish the ad from.
        pixel_id: Meta Pixel ID for conversion tracking. If provided, uses OUTCOME_SALES flow.
        whatsapp_number: WhatsApp business number for COD flow (used when pixel_id is None).

    Returns:
        JSON summary with campaign_id, adset_id, creative_id, ad_id, and flow used.
    """
    act = f"act_{ad_account_id}" if not ad_account_id.startswith("act_") else ad_account_id
    budget_cents = display_to_minor(daily_budget)

    try:
        targeting_spec = json.loads(targeting_json) if isinstance(targeting_json, str) else targeting_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "targeting_json must be a valid JSON string."})

    # Inject Advantage+ audience expansion
    targeting_spec["targeting_automation"] = {"advantage_audience": 1}

    # Determine flow based on pixel presence
    has_pixel = bool(pixel_id)
    flow = "pixel_sales" if has_pixel else "whatsapp_cod"

    results = {"flow": flow}

    # ── Step 1: Campaign ────────────────────────────────────────────────────
    objective = "OUTCOME_SALES" if has_pixel else "OUTCOME_ENGAGEMENT"
    try:
        campaign = _post(access_token, f"{act}/campaigns", {
            "name": campaign_name,
            "objective": objective,
            "status": "PAUSED",
            "special_ad_categories": [],
        })
        results["campaign_id"] = campaign["id"]
    except ValueError as e:
        return json.dumps({"error": f"Campaign creation failed: {e}"})

    # ── Step 2: Ad Set ──────────────────────────────────────────────────────
    adset_params: dict = {
        "name": f"{campaign_name} — Ad Set",
        "campaign_id": results["campaign_id"],
        "daily_budget": budget_cents,
        "billing_event": "IMPRESSIONS",
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "targeting": targeting_spec,
        "status": "PAUSED",
    }

    if has_pixel:
        # FLOW A: Website conversion tracking via Pixel
        adset_params["optimization_goal"] = "OFFSITE_CONVERSIONS"
        adset_params["promoted_object"] = {
            "pixel_id": pixel_id,
            "custom_event_type": "PURCHASE",
        }
    else:
        # FLOW B: WhatsApp/Messenger COD conversations
        adset_params["optimization_goal"] = "CONVERSATIONS"
        adset_params["destination_type"] = "WHATSAPP"
        if page_id:
            promoted = {"page_id": page_id}
            if whatsapp_number:
                promoted["whatsapp_number"] = whatsapp_number
            adset_params["promoted_object"] = promoted

    try:
        adset = _post(access_token, f"{act}/adsets", adset_params)
        results["adset_id"] = adset["id"]
    except ValueError as e:
        return json.dumps({"error": f"Ad Set failed: {e}", **results})

    # ── Step 3: Creative ────────────────────────────────────────────────────
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

    if not has_pixel and whatsapp_number:
        # Override CTA for WhatsApp flow
        creative_data["object_story_spec"]["link_data"]["call_to_action"] = {
            "type": "WHATSAPP_MESSAGE",
            "value": {"whatsapp_number": whatsapp_number},
        }

    if page_id:
        creative_data["object_story_spec"]["page_id"] = page_id
    if image_url:
        creative_data["object_story_spec"]["link_data"]["picture"] = image_url

    try:
        creative = _post(access_token, f"{act}/adcreatives", creative_data)
        results["creative_id"] = creative["id"]
    except ValueError as e:
        return json.dumps({"error": f"Creative failed: {e}", **results})

    # ── Step 4: Ad ──────────────────────────────────────────────────────────
    try:
        ad = _post(access_token, f"{act}/ads", {
            "name": f"{campaign_name} — Ad",
            "adset_id": results["adset_id"],
            "creative": {"creative_id": results["creative_id"]},
            "status": "PAUSED",
        })
        results["ad_id"] = ad["id"]
    except ValueError as e:
        return json.dumps({"error": f"Ad failed: {e}", **results})

    flow_msg = (
        f"OUTCOME_SALES funnel with Pixel {pixel_id} tracking"
        if has_pixel
        else "OUTCOME_ENGAGEMENT WhatsApp/COD funnel"
    )
    return json.dumps({
        "success": True,
        "message": f"{flow_msg} created in PAUSED status.",
        **results,
    })


# ── Time-Series Analytics Tool ────────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def saas_time_series_insights(
    access_token: str,
    ad_account_id: str,
    date_preset: Literal["last_7d", "last_14d", "last_30d"] = "last_30d",
) -> str:
    """
    Get daily time-series performance data and campaign-level breakdown for charts.

    Returns two datasets:
    - daily: [{date, spend, roas, impressions, ctr, purchases, cpm}]
    - by_campaign: [{id, name, spend, roas, purchases, impressions}]

    Args:
        access_token: Valid access token with ads_read permission.
        ad_account_id: The ad account ID (numeric, without act_ prefix).
        date_preset: Time range (last_7d, last_14d, last_30d).
    """
    act = f"act_{ad_account_id}" if not ad_account_id.startswith("act_") else ad_account_id
    preset = DATE_PRESETS.get(date_preset, "last_30_d")

    # Daily breakdown
    daily = []
    try:
        data = _get(access_token, f"{act}/insights", params={
            "fields": "spend,impressions,inline_link_click_ctr,actions,purchase_roas,cpm",
            "date_preset": preset,
            "time_increment": 1,
            "limit": 90,
        })
        for row in data.get("data", []):
            spend = float(row.get("spend", 0))
            purchases = int(_extract_action(row.get("actions", []), "offsite_conversion.fb_pixel_purchase"))
            roas_arr = row.get("purchase_roas", [])
            roas = float(roas_arr[0]["value"]) if roas_arr else 0.0
            daily.append({
                "date": row.get("date_start", ""),
                "spend": round(spend, 2),
                "roas": round(roas, 2),
                "impressions": int(row.get("impressions", 0)),
                "ctr": round(float(row.get("inline_link_click_ctr", 0)), 2),
                "purchases": purchases,
                "cpm": round(float(row.get("cpm", 0)), 2),
            })
    except ValueError:
        pass

    # Campaign-level breakdown
    by_campaign = []
    try:
        data = _get(access_token, f"{act}/insights", params={
            "fields": "campaign_id,campaign_name,spend,purchase_roas,actions,impressions",
            "date_preset": preset,
            "level": "campaign",
            "limit": 50,
        })
        for row in data.get("data", []):
            spend = float(row.get("spend", 0))
            purchases = int(_extract_action(row.get("actions", []), "offsite_conversion.fb_pixel_purchase"))
            roas_arr = row.get("purchase_roas", [])
            roas = float(roas_arr[0]["value"]) if roas_arr else 0.0
            by_campaign.append({
                "id": row.get("campaign_id", ""),
                "name": row.get("campaign_name", ""),
                "spend": round(spend, 2),
                "roas": round(roas, 2),
                "purchases": purchases,
                "impressions": int(row.get("impressions", 0)),
            })
    except ValueError:
        pass

    return json.dumps({"daily": daily, "by_campaign": by_campaign})


# ── Campaign Detail (SaaS) ────────────────────────────────────────────────────

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


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def saas_campaign_detail(
    access_token: str,
    campaign_id: str,
    date_preset: Literal["last_7d", "last_14d", "last_30d"] = "last_7d",
) -> str:
    """
    Full campaign detail for the SaaS dashboard: summary metrics, daily time-series,
    individual ad performance, demographic breakdowns, and pixel conversion analytics.

    Returns JSON with keys: summary, daily, ads, breakdowns, pixel.
    The pixel key is null if no pixel events are detected.

    Args:
        access_token: Valid access token with ads_read permission.
        campaign_id: The campaign ID.
        date_preset: Time range (last_7d, last_14d, last_30d).
    """
    preset = DATE_PRESETS.get(date_preset, "last_7_d")
    insight_fields = [
        "campaign_name", "spend", "impressions", "reach", "clicks",
        "inline_link_clicks", "inline_link_click_ctr", "cpm", "cpc",
        "purchase_roas", "actions", "action_values", "cost_per_action_type",
        "frequency", "date_start", "date_stop",
    ]

    # ── 1. Summary ────────────────────────────────────────────────
    summary: dict = {"campaign_id": campaign_id, "no_data": True}
    try:
        data = _get(access_token, f"{campaign_id}/insights", params={
            "fields": ",".join(insight_fields),
            "date_preset": preset,
            "level": "campaign",
        })
        rows = data.get("data", [])
        if rows:
            row = rows[0]
            actions = row.get("actions", [])
            action_values = row.get("action_values", [])
            cost_per = row.get("cost_per_action_type", [])
            roas_list = row.get("purchase_roas", [])
            roas = float(roas_list[0].get("value", 0)) if roas_list else None

            purchases = int(_extract_action(actions, "offsite_conversion.fb_pixel_purchase"))
            leads = int(_extract_action(actions, "lead"))
            if purchases > 0:
                result_type = "purchases"
                results = purchases
                cost_per_result = _extract_action(cost_per, "offsite_conversion.fb_pixel_purchase")
            elif leads > 0:
                result_type = "leads"
                results = leads
                cost_per_result = _extract_action(cost_per, "lead")
            else:
                result_type = "purchases"
                results = 0
                cost_per_result = None

            summary = {
                "campaign_id": campaign_id,
                "campaign_name": row.get("campaign_name", ""),
                "no_data": False,
                "spend": float(row.get("spend", 0)),
                "roas": roas,
                "impressions": int(row.get("impressions", 0)),
                "reach": int(row.get("reach", 0)),
                "clicks": int(row.get("clicks", 0)),
                "link_clicks": int(row.get("inline_link_clicks", 0)),
                "ctr": float(row.get("inline_link_click_ctr", 0)),
                "cpm": float(row.get("cpm", 0)),
                "cpc": float(row.get("cpc", 0)),
                "frequency": float(row.get("frequency", 0)),
                "purchases": purchases,
                "leads": leads,
                "results": results,
                "result_type": result_type,
                "cost_per_result": round(cost_per_result, 2) if cost_per_result else None,
                "purchase_value": round(_extract_action(action_values, "offsite_conversion.fb_pixel_purchase"), 2),
                "add_to_cart": int(_extract_action(actions, "offsite_conversion.fb_pixel_add_to_cart")),
                "initiate_checkout": int(_extract_action(actions, "offsite_conversion.fb_pixel_initiate_checkout")),
                "date_start": row.get("date_start", ""),
                "date_stop": row.get("date_stop", ""),
            }
    except ValueError:
        pass

    if summary.get("no_data"):
        # Return early with campaign name if possible
        try:
            cdata = _get(access_token, campaign_id, params={"fields": "name"})
            summary["campaign_name"] = cdata.get("name", "")
        except ValueError:
            summary["campaign_name"] = ""
        return json.dumps({"summary": summary, "daily": [], "ads": [], "breakdowns": {"by_age": [], "by_gender": [], "by_placement": []}, "pixel": None})

    # ── 2. Daily time-series ──────────────────────────────────────
    daily: list[dict] = []
    try:
        data = _get(access_token, f"{campaign_id}/insights", params={
            "fields": "spend,impressions,inline_link_clicks,inline_link_click_ctr,cpm,purchase_roas,actions,action_values,cost_per_action_type",
            "date_preset": preset,
            "time_increment": 1,
            "level": "campaign",
            "limit": 90,
        })
        for row in data.get("data", []):
            acts = row.get("actions", [])
            roas_arr = row.get("purchase_roas", [])
            purchases = int(_extract_action(acts, "offsite_conversion.fb_pixel_purchase"))
            leads = int(_extract_action(acts, "lead"))
            if summary["result_type"] == "leads":
                res = leads
                cpr = _extract_action(row.get("cost_per_action_type", []), "lead")
            else:
                res = purchases
                cpr = _extract_action(row.get("cost_per_action_type", []), "offsite_conversion.fb_pixel_purchase")
            daily.append({
                "date": row.get("date_start", ""),
                "spend": round(float(row.get("spend", 0)), 2),
                "impressions": int(row.get("impressions", 0)),
                "clicks": int(row.get("inline_link_clicks", 0)),
                "ctr": round(float(row.get("inline_link_click_ctr", 0)), 2),
                "cpm": round(float(row.get("cpm", 0)), 2),
                "roas": round(float(roas_arr[0]["value"]), 2) if roas_arr else None,
                "purchases": purchases,
                "leads": leads,
                "results": res,
                "result_type": summary["result_type"],
                "cost_per_result": round(cpr, 2) if cpr else None,
            })
    except ValueError:
        pass

    # ── 3. Ads ────────────────────────────────────────────────────
    ads: list[dict] = []
    try:
        ads_data = _get(access_token, f"{campaign_id}/ads", params={
            "fields": "id,name,status,effective_status,creative{thumbnail_url}",
            "limit": 50,
        })
        ins_data = _get(access_token, f"{campaign_id}/insights", params={
            "fields": "ad_id,ad_name,spend,impressions,inline_link_click_ctr,purchase_roas,actions,cost_per_action_type",
            "date_preset": preset,
            "level": "ad",
        })
        ins_map: dict = {}
        for row in ins_data.get("data", []):
            ad_id = row.get("ad_id")
            roas_list = row.get("purchase_roas", [])
            roas = float(roas_list[0].get("value", 0)) if roas_list else None
            acts = row.get("actions", [])
            purchases = int(_extract_action(acts, "offsite_conversion.fb_pixel_purchase"))
            leads = int(_extract_action(acts, "lead"))
            if summary["result_type"] == "leads":
                res = leads
                cpr = _extract_action(row.get("cost_per_action_type", []), "lead")
            else:
                res = purchases
                cpr = _extract_action(row.get("cost_per_action_type", []), "offsite_conversion.fb_pixel_purchase")
            ins_map[ad_id] = {
                "spend": float(row.get("spend", 0)),
                "impressions": int(row.get("impressions", 0)),
                "ctr": float(row.get("inline_link_click_ctr", 0)),
                "roas": roas,
                "purchases": purchases,
                "leads": leads,
                "results": res,
                "result_type": summary["result_type"],
                "cost_per_result": round(cpr, 2) if cpr else None,
            }

        for ad in ads_data.get("data", []):
            ad_id = ad["id"]
            ins = ins_map.get(ad_id, {})
            spend = ins.get("spend", 0.0)
            roas = ins.get("roas")
            results = ins.get("results", 0)
            # Determine verdict
            if roas is not None and roas >= 3.0:
                verdict = "scale"
            elif roas is not None and roas >= 1.5:
                verdict = "hold"
            elif spend >= 2000 and results == 0:
                verdict = "kill"
            elif spend > 0 and results == 0:
                verdict = "no_results"
            elif spend > 0 and roas is not None and roas > 0:
                verdict = "underperforming"
            elif spend > 0:
                verdict = "no_purchases"
            else:
                verdict = "no_data"

            creative = ad.get("creative", {})
            ads.append({
                "id": ad_id,
                "name": ad.get("name", ""),
                "status": ad.get("status", ""),
                "effective_status": ad.get("effective_status", ""),
                "thumbnail_url": creative.get("thumbnail_url"),
                "spend": spend,
                "impressions": ins.get("impressions", 0),
                "ctr": ins.get("ctr", 0),
                "roas": roas,
                "purchases": ins.get("purchases", 0),
                "leads": ins.get("leads", 0),
                "results": results,
                "result_type": summary["result_type"],
                "cost_per_result": ins.get("cost_per_result"),
                "verdict": verdict,
            })
    except ValueError:
        pass

    # ── 4. Breakdowns ─────────────────────────────────────────────
    breakdowns: dict = {"by_age": [], "by_gender": [], "by_placement": []}
    for bk_key, bk_param in [("by_age", "age"), ("by_gender", "gender"), ("by_placement", "placement")]:
        try:
            bk_fields = "spend,impressions,clicks,inline_link_click_ctr,actions,cost_per_action_type"
            params: dict = {
                "fields": bk_fields,
                "date_preset": preset,
                "level": "campaign",
                "breakdowns": bk_param if bk_param != "placement" else "publisher_platform,platform_position",
            }
            data = _get(access_token, f"{campaign_id}/insights", params=params)
            for row in data.get("data", []):
                acts = row.get("actions", [])
                purchases = int(_extract_action(acts, "offsite_conversion.fb_pixel_purchase"))
                leads = int(_extract_action(acts, "lead"))
                if summary["result_type"] == "leads":
                    res = leads
                    cpr = _extract_action(row.get("cost_per_action_type", []), "lead")
                else:
                    res = purchases
                    cpr = _extract_action(row.get("cost_per_action_type", []), "offsite_conversion.fb_pixel_purchase")
                entry: dict = {
                    "spend": float(row.get("spend", 0)),
                    "impressions": int(row.get("impressions", 0)),
                    "clicks": int(row.get("clicks", 0)),
                    "ctr": round(float(row.get("inline_link_click_ctr", 0)), 2),
                    "results": res,
                    "result_type": summary["result_type"],
                    "cost_per_result": round(cpr, 2) if cpr else None,
                }
                if bk_param == "age":
                    entry["age"] = row.get("age", "")
                elif bk_param == "gender":
                    entry["gender"] = row.get("gender", "")
                else:
                    entry["publisher_platform"] = row.get("publisher_platform", "")
                    entry["platform_position"] = row.get("platform_position", "")
                breakdowns[bk_key].append(entry)
        except ValueError:
            pass

    # ── 5. Pixel analytics ────────────────────────────────────────
    pixel_section = None
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

        # Extract pixel events from the summary actions
        summary_actions = []
        summary_action_values = []
        summary_cost_per = []
        if not summary.get("no_data"):
            # Re-fetch full actions (we need these for pixel extraction)
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
            except ValueError:
                pass

        pixel_events = _extract_pixel_events(summary_actions, summary_action_values, summary_cost_per)

        if pixel_id or pixel_events:
            # Fetch pixel name if we have the ID
            pixel_name = None
            if pixel_id:
                try:
                    px_data = _get(access_token, pixel_id, params={"fields": "name"})
                    pixel_name = px_data.get("name")
                except ValueError:
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
            except ValueError:
                pass

            pixel_section = {
                "pixel_id": pixel_id,
                "pixel_name": pixel_name,
                "events": pixel_events,
                "daily_events": daily_pixel,
            }
    except ValueError:
        pass

    return json.dumps({
        "summary": summary,
        "daily": daily,
        "ads": ads,
        "breakdowns": breakdowns,
        "pixel": pixel_section,
    })


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
