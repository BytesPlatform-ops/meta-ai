"""
Audience management routes — niche-scoped Custom Audiences, Lookalike Audiences, and data sync.
"""
import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from ...api.deps import get_current_user_id, get_workspace_id
from ...core.config import get_settings
from ...services.audience_sync import sync_audience_for_niche, query_niche_customers_count
from ...db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meta", tags=["Audiences"])


class CustomerRecord(BaseModel):
    email: str | None = None
    phone: str | None = None
    niche: str | None = None
    product_id: str | None = None


class CustomerBulkUpload(BaseModel):
    customers: list[CustomerRecord]
    niche: str | None = None       # default niche for all records
    product_id: str | None = None  # default product for all records


@router.post("/customers")
async def add_customers(
    body: CustomerBulkUpload,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Add niche-tagged customer records (email/phone) for audience targeting."""
    supabase = get_supabase()

    records = []
    for c in body.customers:
        if c.email or c.phone:
            records.append({
                "user_id": user_id,
                "email": c.email,
                "phone": c.phone,
                "niche": c.niche or body.niche,
                "product_id": c.product_id or body.product_id,
            })

    if not records:
        raise HTTPException(status_code=400, detail="No valid customer records (need email or phone)")

    try:
        result = supabase.table("customers").insert(records).execute()
        return {"inserted": len(result.data), "total_records": len(records)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to insert customers: {e}")


@router.post("/sync-audiences")
async def sync_audiences_endpoint(
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
    niche: str = Query(..., description="Niche/product category to sync (e.g., 'Chatbots', 'Honey')"),
    product_id: str | None = Query(None, description="Optional product ID for exact matching"),
):
    """
    Sync niche-scoped customer data to Meta Custom Audiences + generate 1% LAL.
    Only customers tagged with this niche are included — prevents cross-niche contamination.
    """
    result = await sync_audience_for_niche(user_id, niche, product_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.get("/audience-check")
async def check_audience_data(
    niche: str = Query(..., description="Niche to check customer data for"),
    product_id: str | None = Query(None),
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """
    Check how many customers exist for a niche — used to preview routing decision.
    Returns count and which route (cold vs data-rich) the AI would take.
    """
    count = query_niche_customers_count(user_id, niche, product_id)
    route = "data_rich" if count >= 100 else "cold"
    return {
        "niche": niche,
        "customer_count": count,
        "route": route,
        "explanation": (
            f"DATA-RICH: {count} customers found — will use Custom Audience + 1% LAL, no interest targeting"
            if route == "data_rich"
            else f"COLD START: only {count} customers — will use API-validated interest targeting (need 100+ for LAL)"
        ),
    }


@router.get("/audience-stats")
async def audience_stats(
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """
    Return combined audience stats from BOTH data sources:
    1. Database customers (CSV/webhook uploads) — per-niche breakdown
    2. Meta Pixel events (CompleteRegistration, Purchase, etc.) — from live pixel

    The frontend uses this to show a unified view so the page never looks empty
    when the user has pixel data but no CSV uploads.
    """
    from ...services.mcp_client import mcp_client

    supabase = get_supabase()

    # ── Source 1: Database customers (existing) ──────────────────────────────
    db_niches: list[dict] = []
    total_db_customers = 0
    try:
        result = supabase.table("customers").select("niche").eq("user_id", user_id).execute()
        counts: dict[str, int] = {}
        for row in (result.data or []):
            n = row.get("niche") or "Uncategorized"
            counts[n] = counts.get(n, 0) + 1
        db_niches = [
            {"niche": n, "count": c, "lal_ready": c >= 100}
            for n, c in sorted(counts.items(), key=lambda x: -x[1])
        ]
        total_db_customers = sum(c for c in counts.values())
    except Exception:
        pass

    # ── Source 2: Meta Pixel events + attributed results ─────────────────────
    pixel_events: list[dict] = []
    total_pixel_events = 0
    pixel_id = None
    pixel_lal_ready = False
    attributed_results: dict = {}  # from campaign insights (all-time)

    try:
        # Resolve pixel + access token from ALL available sources
        # Priority: workspace → ad_accounts → products → content_drafts → Meta API
        access_token = None
        ad_account_id = None

        # Source 1: Workspace
        if workspace_id:
            ws_result = (
                supabase.table("workspaces")
                .select("meta_pixel_id, meta_ad_account_id, meta_access_token")
                .eq("id", workspace_id)
                .limit(1)
                .execute()
            )
            if ws_result.data:
                ws = ws_result.data[0]
                pixel_id = ws.get("meta_pixel_id")
                ad_account_id = ws.get("meta_ad_account_id")
                access_token = ws.get("meta_access_token")

        # Source 2: Ad accounts (always check — workspace may not have token)
        aa_query = (
            supabase.table("ad_accounts")
            .select("access_token, meta_account_id, pixel_id")
            .eq("user_id", user_id)
            .eq("is_active", True)
        )
        if workspace_id:
            aa_query = aa_query.eq("workspace_id", workspace_id)
        aa_result = aa_query.limit(1).execute()
        if aa_result.data:
            aa = aa_result.data[0]
            access_token = access_token or aa["access_token"]
            ad_account_id = ad_account_id or aa["meta_account_id"]
            if not pixel_id:
                pixel_id = aa.get("pixel_id")

        # Source 3: Products table (pixel-per-product architecture)
        if not pixel_id:
            prod_query = supabase.table("products").select("pixel_id").eq("user_id", user_id)
            if workspace_id:
                prod_query = prod_query.eq("workspace_id", workspace_id)
            prod_result = prod_query.not_.is_("pixel_id", "null").limit(1).execute()
            if prod_result.data:
                pixel_id = prod_result.data[0].get("pixel_id")

        # Source 4: Content drafts — pixel may only be attached to individual drafts
        if not pixel_id:
            draft_result = (
                supabase.table("content_drafts")
                .select("pixel_id")
                .eq("user_id", user_id)
                .not_.is_("pixel_id", "null")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if draft_result.data:
                pixel_id = draft_result.data[0].get("pixel_id")

        # Source 5: Ask Meta directly — fetch pixels from the ad account
        if not pixel_id and access_token and ad_account_id:
            try:
                pixels_result = await mcp_client.fetch_pixels(ad_account_id, access_token)
                pixels_data = pixels_result
                if isinstance(pixels_result, dict):
                    content = pixels_result.get("content", [])
                    if content and isinstance(content, list):
                        import json as _json
                        text = content[0].get("text", "{}")
                        try:
                            pixels_data = _json.loads(text)
                        except Exception:
                            pixels_data = pixels_result
                pixels_list = pixels_data.get("pixels", [])
                if pixels_list:
                    # Pick the first active pixel
                    pixel_id = pixels_list[0].get("id")
                    logger.info("Resolved pixel %s from Meta API for ad account %s", pixel_id, ad_account_id)
            except Exception as e:
                logger.warning("Failed to fetch pixels from Meta: %s", e)

        # Fetch pixel events if we have everything (last 30 days)
        if pixel_id and access_token:
            events_result = await mcp_client.get_pixel_events(pixel_id, access_token, days=30)
            # Parse MCP response
            events_data = events_result
            if isinstance(events_result, dict):
                content = events_result.get("content", [])
                if content and isinstance(content, list):
                    import json
                    text = content[0].get("text", "{}")
                    try:
                        events_data = json.loads(text)
                    except Exception:
                        events_data = events_result

            raw_events = events_data.get("events", [])
            # Key conversion events we care about
            _CONVERSION_EVENTS = {
                "CompleteRegistration", "Purchase", "Lead", "Subscribe",
                "ViewContent", "AddToCart", "InitiateCheckout", "PageView",
            }
            for evt in raw_events:
                event_name = evt.get("event", "")
                count = int(evt.get("count", 0) or evt.get("count_7d", 0))
                if count > 0:
                    is_conversion = event_name in _CONVERSION_EVENTS
                    pixel_events.append({
                        "event": event_name,
                        "count": count,
                        "is_conversion": is_conversion,
                        "lal_ready": count >= 100 and is_conversion,
                    })
                    total_pixel_events += count

            # Sort: conversion events first, then by count
            pixel_events.sort(key=lambda e: (-e["is_conversion"], -e["count"]))
            pixel_lal_ready = any(e["lal_ready"] for e in pixel_events)

        # ── Fetch attributed results from campaign insights (all-time) ──────
        if access_token and ad_account_id:
            try:
                dash_result = await mcp_client.get_dashboard_metrics(
                    ad_account_id, access_token, date_preset="maximum",
                )
                dash_data = dash_result
                if isinstance(dash_result, dict):
                    content = dash_result.get("content", [])
                    if content and isinstance(content, list):
                        import json as _json2
                        text = content[0].get("text", "{}")
                        try:
                            dash_data = _json2.loads(text)
                        except Exception:
                            dash_data = dash_result

                # Extract from total_account_metrics or workspace_page_metrics
                metrics = dash_data.get("workspace_page_metrics") or dash_data.get("total_account_metrics") or {}
                rb = metrics.get("results_breakdown", {})
                attributed_results = {
                    "registrations": int(rb.get("registrations", 0)),
                    "purchases": int(rb.get("purchases", 0)),
                    "leads": int(rb.get("leads", 0)),
                    "total_results": int(metrics.get("results", 0)),
                    "result_type": metrics.get("result_type", "none"),
                }
            except Exception as e:
                logger.warning("Failed to fetch attributed results: %s", e)

    except Exception as e:
        logger.warning("Failed to fetch pixel events for audience stats: %s", e)

    # ── Combined LAL readiness ───────────────────────────────────────────────
    db_lal_ready_count = len([n for n in db_niches if n["lal_ready"]])
    any_lal_ready = pixel_lal_ready or db_lal_ready_count > 0

    return {
        # Database source
        "niches": db_niches,
        "total_db_customers": total_db_customers,
        "db_lal_ready_count": db_lal_ready_count,
        # Pixel source (last 30 days)
        "pixel_id": pixel_id,
        "pixel_events": pixel_events,
        "total_pixel_events": total_pixel_events,
        "pixel_lal_ready": pixel_lal_ready,
        "pixel_days": 30,
        # Ad-attributed results (all-time campaign insights)
        "attributed_results": attributed_results,
        # Combined
        "any_lal_ready": any_lal_ready,
    }


# ── Webhook: Auto-Ingestion (The Fuel Line) ─────────────────────────────────

class WebhookCustomerPayload(BaseModel):
    user_id: str
    niche: str
    email: str | None = None
    phone: str | None = None
    product_id: str | None = None
    source: str | None = "webhook"


def _verify_webhook_secret(x_webhook_secret: str = Header(...)):
    """Validate the shared secret sent by Zapier / Make / Shopify."""
    settings = get_settings()
    if not settings.WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="WEBHOOK_SECRET not configured on server")
    if not hmac.compare_digest(x_webhook_secret, settings.WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


@router.post("/webhooks/customer-sync", tags=["Webhooks"])
async def webhook_customer_sync(
    body: WebhookCustomerPayload,
    _secret: None = Depends(_verify_webhook_secret),
):
    """
    Secure webhook for automated customer ingestion.

    External tools (Zapier, Make, Shopify webhooks) call this whenever a
    purchase or lead happens. The record lands in the `customers` table
    and feeds the LAL pipeline automatically.

    Requires `X-Webhook-Secret` header matching the server's WEBHOOK_SECRET.
    Handles duplicates gracefully via upsert (unique index on user+email+phone+niche).
    """
    if not body.email and not body.phone:
        raise HTTPException(status_code=400, detail="At least one of email or phone is required")

    supabase = get_supabase()

    record = {
        "user_id": body.user_id,
        "email": body.email,
        "phone": body.phone,
        "niche": body.niche,
        "product_id": body.product_id,
        "source": body.source or "webhook",
    }

    try:
        result = (
            supabase.table("customers")
            .upsert(record, on_conflict="user_id,COALESCE(email, ''),COALESCE(phone, ''),COALESCE(niche, '')")
            .execute()
        )
    except Exception:
        # Supabase Python client may not support expression-based on_conflict.
        # Fall back to plain insert — the unique index will reject true duplicates.
        try:
            result = supabase.table("customers").insert(record).execute()
        except Exception as dup_err:
            err_str = str(dup_err)
            if "duplicate" in err_str.lower() or "unique" in err_str.lower() or "23505" in err_str:
                logger.info("Duplicate customer skipped: %s / %s / %s", body.email, body.phone, body.niche)
                return {"status": "duplicate", "message": "Customer already exists for this niche"}
            raise HTTPException(status_code=500, detail=f"Failed to insert customer: {dup_err}")

    logger.info("Webhook ingested customer for user %s, niche '%s' (source: %s)", body.user_id, body.niche, body.source)

    # Return current count so the caller knows how close to LAL threshold (100)
    count = query_niche_customers_count(body.user_id, body.niche, body.product_id)

    return {
        "status": "ingested",
        "niche": body.niche,
        "total_customers_in_niche": count,
        "lal_ready": count >= 100,
        "message": f"{'LAL ready! 100+ customers.' if count >= 100 else f'{100 - count} more needed for LAL activation.'}",
    }


# ── Product-Filtered Audience Registry ─────────────────────────────────────


@router.get("/audiences")
async def list_audiences(
    product_id: str | None = Query(None, description="Filter to audiences owned by this product"),
    audience_type: str | None = Query(None, description="Filter by type: SEED, LAL, RETARGETING, EXCLUSION, ENGAGEMENT"),
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """
    List registered Meta audiences, optionally filtered by product.

    When product_id is provided, ONLY audiences belonging to that product are returned.
    This prevents cross-product audience contamination in the UI.
    """
    supabase = get_supabase()
    query = (
        supabase.table("meta_audiences")
        .select("id, meta_audience_id, name, audience_type, product_id, origin_audience_id, pixel_id, created_at")
        .eq("workspace_id", workspace_id)
        .order("created_at", desc=True)
    )

    if product_id:
        query = query.eq("product_id", product_id)
    if audience_type:
        query = query.eq("audience_type", audience_type)

    result = query.limit(200).execute()
    return {"audiences": result.data or [], "total": len(result.data or [])}


# ── Geo City Search (autocomplete) ──────────────────────────────────────────

@router.get("/geo-search")
async def geo_city_search(
    q: str = Query(..., min_length=2, description="City name search query"),
    country: str = Query("", description="ISO country code to filter"),
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Search Meta's geo-location database for cities (autocomplete).
    Returns validated city entries with Meta geo keys."""
    from ...services.mcp_client import mcp_client

    supabase = get_supabase()
    # Get access token from workspace's ad account
    aa = supabase.table("ad_accounts").select("access_token").eq("workspace_id", workspace_id).limit(1).execute()
    if not aa.data:
        raise HTTPException(400, "No Meta account connected")
    access_token = aa.data[0]["access_token"]

    cities = await mcp_client.search_geo_cities(q, country, access_token)
    return {"cities": cities}
