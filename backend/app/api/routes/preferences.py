"""
User Preferences routes.

GET  /api/v1/preferences       → get current user's preferences
PUT  /api/v1/preferences       → create or update preferences (wizard submit)
"""
import json
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
import httpx as _httpx

from ...api.deps import get_current_user_id
from ...db.supabase_client import get_supabase
from ...core.config import get_settings
from ...services.mcp_client import mcp_client, MCPError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/preferences", tags=["User Preferences"])


class PreferencesPayload(BaseModel):
    business_name: str = ""
    business_description: str = ""
    target_audience: str = ""
    website_url: str = ""
    posting_frequency: str   # daily | 3x_weekly | weekends_only | manual_only
    content_tone: str        # professional | humorous | educational | promotional
    ad_budget_level: str     # conservative | moderate | aggressive | custom
    budget_currency: str = "USD"
    custom_budget: float | None = None  # user-defined daily budget when ad_budget_level=custom
    approval_required: bool = True
    target_country: str = "PK"  # ISO country code
    industry_niche: str | None = None
    whatsapp_number: str | None = None
    ad_placements: str = "BOTH"  # BOTH | FACEBOOK_ONLY | INSTAGRAM_ONLY


VALID_FREQUENCIES = {"daily", "3x_weekly", "weekends_only", "manual_only"}
VALID_TONES = {"professional", "humorous", "educational", "promotional"}
VALID_BUDGETS = {"conservative_$10", "moderate_$30", "aggressive_$50", "conservative", "moderate", "aggressive", "custom"}


@router.get("")
async def get_preferences(user_id: str = Depends(get_current_user_id)):
    """Returns the user's preferences, or null if not yet configured."""
    supabase = get_supabase()
    result = (
        supabase.table("user_preferences")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )
    return result.data[0] if result.data else None


def _extract_mcp_content(result: dict) -> str:
    """Extract text from MCP JSON-RPC response (handles both raw dict and FastMCP content wrapper)."""
    # Direct dict with raw_content (JSON tool return)
    if isinstance(result, dict) and "raw_content" in result:
        return result["raw_content"]
    # FastMCP content wrapper: {"content": [{"text": "..."}]}
    content = result.get("content", []) if isinstance(result, dict) else []
    if content and isinstance(content, list):
        text = content[0].get("text", "") if isinstance(content[0], dict) else str(content[0])
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "raw_content" in parsed:
                return parsed["raw_content"]
            return text
        except (json.JSONDecodeError, TypeError):
            return text
    # Fallback: try json.dumps of the whole thing
    return json.dumps(result) if result else ""


async def _scrape_and_store(user_id: str, website_url: str):
    """Background task: scrape website via MCP, structure with OpenAI, save to DB."""
    import traceback as _tb
    try:
        await _scrape_and_store_inner(user_id, website_url)
    except Exception:
        logger.error("_scrape_and_store CRASHED:\n%s", _tb.format_exc())


async def _scrape_and_store_inner(user_id: str, website_url: str):
    """Scrape one or more URLs (comma-separated) via MCP, structure with OpenAI, save to DB."""
    from openai import AsyncOpenAI
    settings = get_settings()
    openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    # website_url can be a single URL or comma-separated list
    urls = [u.strip() for u in website_url.split(",") if u.strip()]
    primary_url = urls[0] if urls else website_url

    # Scrape all URLs in a single MCP call (MCP tool handles batching)
    all_content = ""
    try:
        raw = await mcp_client.scrape_website(website_url)  # pass full comma-separated string
        raw_result = _extract_mcp_content(raw)

        # The result may be JSON with a "pages" array or just raw content
        try:
            parsed = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
            if isinstance(parsed, dict) and "pages" in parsed:
                page_contents = []
                for page in parsed["pages"]:
                    content = page.get("raw_content", "")
                    if content:
                        page_contents.append(f"=== Page: {page.get('url', 'unknown')} ===\n{content}")
                all_content = "\n\n".join(page_contents) if page_contents else raw_result
            else:
                all_content = parsed.get("raw_content", raw_result) if isinstance(parsed, dict) else raw_result
        except (json.JSONDecodeError, TypeError):
            all_content = raw_result

        if not all_content or len(all_content) < 50:
            logger.warning("Website scrape returned no/little content for %s (got %d chars)", primary_url, len(all_content))
            supabase = get_supabase()
            supabase.table("user_preferences").update({
                "website_intel": {"error": "Could not extract content from website", "url": primary_url, "urls_scraped": urls},
                "website_scraped_at": datetime.now(timezone.utc).isoformat(),
            }).eq("user_id", user_id).execute()
            return

        # Truncate combined content for LLM context
        content_for_llm = all_content[:12000] if len(urls) > 1 else all_content[:6000]

        multi_page_note = f"\nThis content was scraped from {len(urls)} pages: {', '.join(urls)}\nMake sure to capture ALL products/services across all pages." if len(urls) > 1 else ""

        resp = await openai_client.chat.completions.create(
            model=settings.CHEAP_FAST_MODEL,
            messages=[
                {"role": "system", "content": "Extract structured business intelligence from this website content. Return ONLY valid JSON."},
                {"role": "user", "content": f"""Analyze this website content and extract:{multi_page_note}\n\n{content_for_llm}\n\nReturn JSON:\n{{\n  "business_type": "e-commerce | service | saas | portfolio | other",\n  "products_or_services": [{{"name": "...", "description": "...", "price": "...", "product_type": "physical | digital | saas | service", "source_url": "the page URL where this product was found"}}],\n  "value_propositions": ["..."],\n  "target_audience_signals": ["..."],\n  "brand_tone": "professional | casual | luxury | friendly | technical",\n  "key_offerings_summary": "2-3 sentence summary of what this business sells/does",\n  "urls_scraped": {json.dumps(urls)}\n}}"""},
            ],
            max_completion_tokens=2000,
        )
        text = resp.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        intel = json.loads(text)
    except Exception as e:
        logger.error("Website intel extraction failed for %s: %s", primary_url, e)
        intel = {"error": str(e), "raw_snippet": all_content[:500] if all_content else ""}

    supabase = get_supabase()

    # Save intel to preferences
    try:
        supabase.table("user_preferences").update({
            "website_intel": intel,
            "website_scraped_at": datetime.now(timezone.utc).isoformat(),
        }).eq("user_id", user_id).execute()
    except Exception as e:
        logger.error("Failed to save website_intel: %s", e)

    # Auto-create products from scraped data
    products = intel.get("products_or_services", [])
    logger.info("Scrape done for %s — intel keys: %s, products found: %d", user_id, list(intel.keys()), len(products) if isinstance(products, list) else 0)
    if products and isinstance(products, list):
        for p in products[:20]:  # cap at 20
            name = p.get("name", "").strip()
            if not name:
                continue
            # Use source_url (per-product page) if available, otherwise primary URL
            product_landing = p.get("source_url") or primary_url
            # If product exists (even soft-deleted), reactivate & update type + URL
            existing = supabase.table("products").select("id, is_active").eq("user_id", user_id).eq("name", name).limit(1).execute()
            if existing.data:
                raw_ptype = (p.get("product_type") or "").lower().strip()
                update: dict = {"is_active": True, "landing_url": product_landing}
                if raw_ptype in ("physical", "digital", "saas", "service"):
                    update["product_type"] = raw_ptype
                supabase.table("products").update(update).eq("id", existing.data[0]["id"]).execute()
                logger.info("Reactivated product '%s' for user %s", name, user_id)
                continue
            price_str = str(p.get("price", "0")).replace(",", "").replace("$", "").replace("PKR", "").replace("Rs", "").strip()
            try:
                price = float(price_str) if price_str else 0
            except ValueError:
                price = 0
            # Use per-product type from LLM, fallback to business_type
            raw_ptype = (p.get("product_type") or "").lower().strip()
            if raw_ptype in ("physical", "digital", "saas", "service"):
                ptype = raw_ptype
            else:
                btype = (intel.get("business_type") or "").lower()
                ptype = "saas" if "saas" in btype else "service" if "service" in btype or "portfolio" in btype else "physical" if "e-commerce" in btype else "digital"
            try:
                supabase.table("products").insert({
                    "user_id": user_id,
                    "name": name,
                    "description": p.get("description", ""),
                    "price": price,
                    "currency": "PKR",
                    "landing_url": product_landing,
                    "product_type": ptype,
                    "is_active": True,
                }).execute()
                logger.info("Auto-created product '%s' for user %s (landing: %s)", name, user_id, product_landing)
            except Exception as e:
                logger.warning("Failed to auto-create product '%s': %s", name, e)


@router.put("")
async def upsert_preferences(
    payload: PreferencesPayload,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
):
    """Create or update user preferences (wizard submit)."""
    # Validate enums
    if payload.posting_frequency not in VALID_FREQUENCIES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid posting_frequency")
    if payload.content_tone not in VALID_TONES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid content_tone")
    if payload.ad_budget_level not in VALID_BUDGETS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid ad_budget_level")

    supabase = get_supabase()
    data = {
        "user_id": user_id,
        "business_name": payload.business_name,
        "business_description": payload.business_description,
        "target_audience": payload.target_audience,
        "website_url": payload.website_url,
        "posting_frequency": payload.posting_frequency,
        "content_tone": payload.content_tone,
        "ad_budget_level": payload.ad_budget_level,
        "budget_currency": payload.budget_currency,
        "custom_budget": payload.custom_budget,
        "approval_required": payload.approval_required,
        "industry_niche": payload.industry_niche,
        "whatsapp_number": payload.whatsapp_number,
        "target_country": payload.target_country,
        "setup_completed_at": datetime.now(timezone.utc).isoformat(),
    }

    # Upsert via direct httpx POST (supabase-py upsert fails with empty APIError)
    settings = get_settings()
    base = settings.SUPABASE_URL.rstrip("/")
    key = settings.SUPABASE_SERVICE_ROLE_KEY
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation,resolution=merge-duplicates",
    }
    resp = _httpx.post(
        f"{base}/rest/v1/user_preferences?on_conflict=user_id",
        headers=headers,
        json=data,
        timeout=10,
    )
    logger.info("Upsert prefs status=%s body=%s", resp.status_code, resp.text[:500])
    saved = resp.json()[0] if resp.status_code in (200, 201) and resp.json() else data

    # Trigger website scraping if URL provided and not recently scraped
    if payload.website_url and payload.website_url.startswith("http"):
        existing_intel = saved.get("website_intel")
        existing_url_scraped = saved.get("website_scraped_at")
        # Scrape if never scraped or URL likely changed (no easy diff, just re-scrape)
        if not existing_intel or not existing_url_scraped:
            background_tasks.add_task(_scrape_and_store, user_id, payload.website_url)

    return saved


class ScrapeWebsitePayload(BaseModel):
    urls: list[str] | None = None  # optional extra URLs to scrape alongside the main one


@router.post("/scrape-website")
async def trigger_website_scrape(
    payload: ScrapeWebsitePayload | None = None,
    user_id: str = Depends(get_current_user_id),
):
    """Force re-scrape of the user's website URL(s).

    Optionally pass {"urls": ["https://site.com/products", ...]} to scrape
    additional pages alongside the main website URL.
    """
    supabase = get_supabase()
    result = supabase.table("user_preferences").select("website_url").eq("user_id", user_id).execute()
    main_url = result.data[0].get("website_url") if result.data else None

    extra_urls = payload.urls if payload and payload.urls else []
    # Combine main URL with any extra URLs
    all_urls = []
    if main_url:
        all_urls.append(main_url)
    for u in extra_urls:
        u = u.strip()
        if u and u.startswith("http") and u not in all_urls:
            all_urls.append(u)

    if not all_urls:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No website URL configured and no URLs provided")

    combined = ", ".join(all_urls)
    await _scrape_and_store(user_id, combined)
    return {"status": "done", "message": f"Analyzed {len(all_urls)} page(s)", "urls_scraped": all_urls}
