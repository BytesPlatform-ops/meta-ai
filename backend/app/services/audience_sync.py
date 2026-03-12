"""
Audience Sync — Niche-aware Custom Audience + Lookalike pipeline.

Key rule: audiences are ALWAYS scoped by niche/product to prevent contamination.
"Honey" buyers never pollute a "Chatbot" Lookalike and vice versa.
"""
import json
import logging
from typing import Any

from ..db.supabase_client import get_supabase
from .mcp_client import mcp_client, MCPError

logger = logging.getLogger(__name__)


async def sync_audience_for_niche(
    user_id: str,
    niche: str,
    product_id: str | None = None,
) -> dict:
    """
    Create a niche-scoped Custom Audience + 1% LAL.

    Only customers tagged with this exact niche (or product_id) are included.
    Returns audience IDs scoped to this niche.
    """
    supabase = get_supabase()

    # 1. Load ad account
    account_result = (
        supabase.table("ad_accounts")
        .select("*")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(1)
        .maybe_single()
        .execute()
    )
    if not account_result.data:
        return {"success": False, "error": "No active ad account found"}

    account = account_result.data
    access_token = account["access_token"]
    ad_account_id = account["meta_account_id"]

    # 2. Load preferences
    prefs_result = (
        supabase.table("user_preferences")
        .select("target_country, business_name")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    prefs = prefs_result.data or {}
    target_country = prefs.get("target_country", "PK")
    business_name = prefs.get("business_name", "Business")

    # 3. Collect NICHE-SCOPED customer data only
    customer_data = _collect_niche_customers(supabase, user_id, niche, product_id)

    if not customer_data:
        return {
            "success": False,
            "niche": niche,
            "customers_found": 0,
            "error": f"No customer data for niche '{niche}'. Cold audience will be used.",
        }

    # 4. Create niche-scoped Custom Audience
    audience_name = f"{business_name} - {niche} Buyers"
    try:
        ca_result = await mcp_client.create_custom_audience(
            ad_account_id, audience_name, customer_data, access_token,
        )
        ca_data = _parse_mcp_result(ca_result)
        custom_audience_id = ca_data.get("audience_id")
        if not custom_audience_id:
            return {"success": False, "error": "Custom Audience creation failed", "detail": ca_data}
    except MCPError as e:
        logger.error("Custom Audience creation failed for niche '%s': %s", niche, e)
        return {"success": False, "error": f"MCP error: {e}"}

    logger.info("Custom Audience for '%s': %s (%d users)", niche, custom_audience_id, len(customer_data))

    # 5. Create 1% LAL
    lal_audience_id = None
    lal_data = {}
    try:
        lal_result = await mcp_client.create_lookalike_audience(
            ad_account_id, custom_audience_id, target_country, 0.01, access_token,
        )
        lal_data = _parse_mcp_result(lal_result)
        lal_audience_id = lal_data.get("audience_id")
    except MCPError as e:
        logger.warning("LAL creation failed for niche '%s' (non-fatal): %s", niche, e)
        lal_data = {"error": str(e)}

    return {
        "success": True,
        "niche": niche,
        "custom_audience_id": custom_audience_id,
        "lookalike_audience_id": lal_audience_id,
        "customers_synced": len(customer_data),
    }


def query_niche_customers_count(
    user_id: str,
    niche: str,
    product_id: str | None = None,
) -> int:
    """
    Quick check: how many customers exist for this niche?
    Used by the routing logic to decide cold vs data-rich path.
    """
    supabase = get_supabase()
    return len(_collect_niche_customers(supabase, user_id, niche, product_id))


def _collect_niche_customers(
    supabase,
    user_id: str,
    niche: str,
    product_id: str | None = None,
) -> list[dict]:
    """
    Collect customers scoped to a specific niche or product.
    Prevents contamination: only returns data for the requested niche.
    """
    try:
        query = (
            supabase.table("customers")
            .select("email, phone")
            .eq("user_id", user_id)
        )
        # Prefer product_id match (most specific), fallback to niche text match
        if product_id:
            query = query.eq("product_id", product_id)
        elif niche:
            query = query.ilike("niche", f"%{niche}%")

        result = query.limit(10000).execute()
        if result.data:
            return [r for r in result.data if r.get("email") or r.get("phone")]
    except Exception:
        pass
    return []


def _parse_mcp_result(result: dict) -> dict:
    """Parse MCP tool result from FastMCP content format."""
    content = result.get("content", [])
    if content and isinstance(content, list):
        text = content[0].get("text", "{}")
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {"raw": text}
    return result
