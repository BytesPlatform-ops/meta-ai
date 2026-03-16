"""
HITL Optimization Engine — AI Co-Pilot for Meta Ads.

Analyzes campaign performance via MCP, uses LLM (GPT-4o-mini) to generate
structured suggestions, and saves them as PENDING for user approval.
Never executes actions directly — the user must approve each suggestion.

Execution only happens when the user clicks "Approve" on the dashboard,
which calls execute_suggestion() to route through MCP.
"""
import json
import logging
from datetime import datetime, timezone

import httpx
from openai import AsyncOpenAI

from ..core.config import get_settings
from ..db.supabase_client import get_supabase
from .mcp_client import mcp_client, MCPError

logger = logging.getLogger(__name__)
settings = get_settings()
openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def _postgrest_headers() -> dict:
    return {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _postgrest_url(table: str) -> str:
    return f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1/{table}"


# ── Product Performance Aggregator ────────────────────────────────────────────

def _get_product_performance(user_id: str, campaigns_text: str) -> str:
    """
    Cross-reference product catalog with campaign data to build a
    product-level performance summary for the LLM.

    Uses content_drafts (which has product_id + meta_campaign_id) to
    link products → campaigns, then extracts spend/ROAS from the
    campaign data string.
    """
    supabase = get_supabase()

    # 1. Get all active products
    products_result = (
        supabase.table("products")
        .select("id, name, price, currency, product_type")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .execute()
    )
    products = products_result.data or []
    if not products:
        return ""

    # 2. Get all drafts that became live campaigns (have meta_campaign_id + product_id)
    drafts_result = (
        supabase.table("content_drafts")
        .select("product_id, meta_campaign_id")
        .eq("user_id", user_id)
        .not_.is_("product_id", "null")
        .not_.is_("meta_campaign_id", "null")
        .execute()
    )
    drafts = drafts_result.data or []

    # 3. Build product_id → set of campaign_ids mapping
    product_campaigns: dict[str, set[str]] = {}
    for d in drafts:
        pid = d["product_id"]
        cid = d["meta_campaign_id"]
        product_campaigns.setdefault(pid, set()).add(cid)

    # 4. Build summary text
    lines = []
    tested_ids = set()
    for p in products:
        pid = p["id"]
        campaign_ids = product_campaigns.get(pid, set())
        if campaign_ids:
            tested_ids.add(pid)
            ids_str = ", ".join(campaign_ids)
            lines.append(
                f"- **{p['name']}** (id: {pid}, type: {p.get('product_type', 'physical')}, "
                f"price: {p.get('price') or 'N/A'} {p.get('currency', 'USD')}): "
                f"Linked campaigns: [{ids_str}]. "
                f"Cross-reference these campaign IDs with the performance data above to calculate this product's aggregate ROAS and spend."
            )
        else:
            lines.append(
                f"- **{p['name']}** (id: {pid}, type: {p.get('product_type', 'physical')}, "
                f"price: {p.get('price') or 'N/A'} {p.get('currency', 'USD')}): "
                f"UNTESTED — 0 campaigns. No ad spend data."
            )

    if not lines:
        return ""

    return "\n".join(lines)


# ── Main Pipeline ─────────────────────────────────────────────────────────────

async def run_optimization(user_id: str, ad_account_id: str | None = None) -> list[dict]:
    """
    Full optimization pipeline for a single user:
      1. Resolve ad account + access token
      2. Fetch campaign list via MCP (7d metrics)
      3. Build product performance context
      4. Send to LLM for structured analysis
      5. Insert PENDING suggestions into DB
    Returns list of created suggestion records.
    """
    supabase = get_supabase()

    # 1. Get ad account
    query = (
        supabase.table("ad_accounts")
        .select("id, meta_account_id, access_token")
        .eq("user_id", user_id)
        .eq("is_active", True)
    )
    if ad_account_id:
        query = query.eq("id", ad_account_id)
    result = query.limit(1).execute()
    if not result.data:
        raise ValueError("No active ad account found")
    account = result.data[0]
    meta_id = account["meta_account_id"].replace("act_", "")
    token = account["access_token"]

    # 2. Fetch campaign performance via MCP (saas_list_campaigns returns 7d metrics)
    try:
        campaigns_raw = await mcp_client.call_tool(
            "saas_list_campaigns",
            {"ad_account_id": meta_id, "status_filter": "all", "limit": 50},
            token,
        )
    except MCPError as e:
        logger.error(f"MCP fetch failed for user {user_id}: {e}")
        raise ValueError(f"Failed to fetch campaign data: {e}")

    # Parse MCP result (FastMCP wraps in content[0].text)
    content = campaigns_raw.get("content", [])
    if content and isinstance(content, list) and isinstance(content[0], dict) and "text" in content[0]:
        campaigns_text = content[0]["text"]
    else:
        campaigns_text = json.dumps(campaigns_raw)

    # 3. Build product performance context
    product_context = _get_product_performance(user_id, campaigns_text)

    # 4. LLM structured analysis
    suggestions = await _get_llm_suggestions(campaigns_text, product_context)

    if not suggestions:
        return []

    # 5. Insert PENDING suggestions into DB
    created = []
    for s in suggestions:
        action_payload = s.get("action_payload", {})
        if isinstance(action_payload, str):
            pass  # already a string
        else:
            action_payload = json.dumps(action_payload)

        row = {
            "user_id": user_id,
            "ad_account_id": account["id"],
            "campaign_id": s.get("campaign_id", ""),
            "adset_id": s.get("adset_id"),
            "entity_name": s.get("entity_name", "Unknown"),
            "analysis_reasoning": s.get("analysis_reasoning", ""),
            "suggested_action": s.get("suggested_action", "DO_NOTHING"),
            "action_payload": action_payload,
            "product_id": s.get("product_id") or None,
            "product_name": s.get("product_name") or None,
            "status": "PENDING",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        resp = httpx.post(
            _postgrest_url("campaign_suggestions"),
            headers=_postgrest_headers(),
            json=row,
            timeout=10,
        )
        if resp.status_code in (200, 201) and resp.json():
            created.append(resp.json()[0])
        else:
            logger.warning("Failed to insert suggestion: %s", resp.text)

    logger.info(
        "Optimization complete for user %s: %d suggestions generated",
        user_id, len(created),
    )
    return created


# ── LLM Analysis ──────────────────────────────────────────────────────────────

async def _get_llm_suggestions(campaigns_data: str, product_context: str = "") -> list[dict]:
    """Prompt LLM to analyze campaigns and return structured JSON suggestions."""

    product_section = ""
    if product_context:
        product_section = f"""

## Product Catalog & Campaign Linkage
The following products are in the user's catalog. Some are linked to campaigns above — cross-reference the campaign IDs to determine each product's aggregate performance.

{product_context}

## Product-Aware Rules (generate additional suggestions alongside campaign rules)
- **Rule: Scale Winners** — If a product's linked campaigns have aggregate ROAS > 3.0, generate a CREATE_NEW_CAMPAIGN suggestion to launch a new campaign for this product with a different angle or Lookalike audience.
- **Rule: Test Untested** — For products marked UNTESTED (0 campaigns), generate a CREATE_NEW_CAMPAIGN suggestion to launch a low-budget testing campaign ($10/day).
- **Rule: Ignore Losers** — If a product's aggregate ROAS is consistently < 1.0 across all its campaigns, do NOT suggest CREATE_NEW_CAMPAIGN for it. You may still suggest PAUSE/DECREASE on its individual campaigns.
"""

    prompt = f"""You are a Meta Ads optimization co-pilot. Analyze the campaign performance data below and generate actionable suggestions for the human advertiser.

## Campaign Performance Data (last 7 days)
{campaigns_data[:8000]}
{product_section}
## Decision Rules (STRICT — follow exactly)
1. **PAUSE** — If spend is significant (> $20 equivalent in any currency) AND purchases = 0. Reasoning: "Spent X with 0 purchases. ROAS is bleeding."
2. **INCREASE_BUDGET** (by 20%) — If ROAS > 3.0 AND has at least 1 purchase. This is a scaling opportunity.
3. **DECREASE_BUDGET** (by 30%) — If ROAS is between 0.5 and 1.5 with some spend. Underperforming but not dead.
4. **DO_NOTHING** — If campaign is too new (< 3 days), has no spend, or is already paused. Explain why you're waiting.
5. Skip campaigns that are paused with $0 spend — don't generate a suggestion for them.
6. **CREATE_NEW_CAMPAIGN** — Only for product-aware suggestions (see Product-Aware Rules above). Must include product_id and product_name.

## Output Format (STRICT JSON)
Return ONLY a JSON array. Each object must have exactly these fields:

For campaign-level suggestions (INCREASE_BUDGET, DECREASE_BUDGET, PAUSE, DO_NOTHING):
{{
  "campaign_id": "the Meta campaign ID string",
  "adset_id": null,
  "entity_name": "campaign name from the data",
  "analysis_reasoning": "2-3 sentence explanation citing specific numbers (spend, ROAS, purchases)",
  "suggested_action": "INCREASE_BUDGET" | "DECREASE_BUDGET" | "PAUSE" | "DO_NOTHING",
  "action_payload": {{}},
  "product_id": null,
  "product_name": null
}}

For product-level suggestions (CREATE_NEW_CAMPAIGN):
{{
  "campaign_id": "",
  "adset_id": null,
  "entity_name": "New campaign for [Product Name]",
  "analysis_reasoning": "2-3 sentence explanation of why this product should get a new campaign",
  "suggested_action": "CREATE_NEW_CAMPAIGN",
  "action_payload": {{"reason": "scale_winner" or "test_untested", "suggested_daily_budget": 10}},
  "product_id": "the product UUID from the catalog",
  "product_name": "the product name"
}}

For INCREASE_BUDGET: action_payload = {{"new_budget_multiplier": 1.2}}
For DECREASE_BUDGET: action_payload = {{"new_budget_multiplier": 0.7}}
For PAUSE or DO_NOTHING: action_payload = {{}}

Return ONLY the JSON array. No markdown fences. No explanatory text outside the array."""

    response = await openai_client.chat.completions.create(
        model=settings.ELITE_REASONING_MODEL,
        messages=[
            {"role": "system", "content": "You are a data-driven Meta Ads analyst. Return only valid JSON arrays."},
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=4000,
        response_format={"type": "json_object"},
    )

    text = response.choices[0].message.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()

    try:
        suggestions = json.loads(text)
        if not isinstance(suggestions, list):
            suggestions = [suggestions]
    except json.JSONDecodeError:
        logger.error(f"LLM returned invalid JSON: {text[:500]}")
        return []

    # Validate
    valid_actions = {"INCREASE_BUDGET", "DECREASE_BUDGET", "PAUSE", "DO_NOTHING", "CREATE_NEW_CAMPAIGN"}
    return [
        s for s in suggestions
        if isinstance(s, dict)
        and s.get("suggested_action") in valid_actions
        and (s.get("campaign_id") or s.get("suggested_action") == "CREATE_NEW_CAMPAIGN")
    ]


# ── Suggestion Execution (called only on user APPROVE) ───────────────────────

async def execute_suggestion(suggestion: dict, access_token: str) -> dict:
    """
    Execute a single approved suggestion via MCP tools.
    Called only when user explicitly approves a suggestion.
    """
    action = suggestion["suggested_action"]
    campaign_id = suggestion["campaign_id"]
    adset_id = suggestion.get("adset_id")
    payload = suggestion.get("action_payload", {})
    if isinstance(payload, str):
        payload = json.loads(payload) if payload else {}

    if action == "PAUSE":
        result = await mcp_client.pause_campaign(campaign_id, access_token)
        return {"success": True, "action": "PAUSE", "mcp_result": result}

    elif action in ("INCREASE_BUDGET", "DECREASE_BUDGET"):
        multiplier = payload.get("new_budget_multiplier", 1.0)
        entity_id = adset_id or campaign_id
        result = await mcp_client.call_tool(
            "update_daily_budget",
            {"adset_id": entity_id, "new_budget": multiplier},
            access_token,
        )
        return {"success": True, "action": action, "multiplier": multiplier, "mcp_result": result}

    elif action == "CREATE_NEW_CAMPAIGN":
        # CREATE_NEW_CAMPAIGN suggestions are informational — they tell the user
        # which product to feature next. Actual campaign creation goes through
        # the normal draft → approve → ad_executor flow.
        return {
            "success": True,
            "action": "CREATE_NEW_CAMPAIGN",
            "product_id": suggestion.get("product_id"),
            "product_name": suggestion.get("product_name"),
            "message": "Navigate to Products → Generate Campaigns to create this campaign.",
        }

    elif action == "DO_NOTHING":
        return {"success": True, "action": "DO_NOTHING"}

    raise ValueError(f"Unknown action: {action}")


# ── Scheduled Job: All Users ─────────────────────────────────────────────────

async def run_all_users_optimization() -> dict:
    """
    Loop through ALL users with active ad accounts, run optimization,
    and generate PENDING suggestions. Designed for the daily scheduler.
    """
    supabase = get_supabase()
    started = datetime.now(timezone.utc)

    accounts = (
        supabase.table("ad_accounts")
        .select("id, user_id, meta_account_id, access_token")
        .eq("is_active", True)
        .execute()
    ).data or []

    if not accounts:
        logger.info("HITL scheduler: no active accounts to evaluate")
        return {"evaluated": 0, "total_suggestions": 0}

    logger.info("HITL scheduler: evaluating %d active accounts", len(accounts))

    total_suggestions = 0
    errors = 0
    for account in accounts:
        try:
            suggestions = await run_optimization(account["user_id"])
            total_suggestions += len(suggestions)
        except Exception as e:
            logger.exception("HITL optimization failed for user %s: %s", account["user_id"], e)
            errors += 1

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    summary = {
        "evaluated": len(accounts),
        "total_suggestions": total_suggestions,
        "errors": errors,
        "elapsed_seconds": round(elapsed, 1),
    }
    logger.info(
        "HITL scheduler complete: %d accounts, %d suggestions, %d errors (%.1fs)",
        summary["evaluated"], summary["total_suggestions"],
        summary["errors"], summary["elapsed_seconds"],
    )
    return summary
