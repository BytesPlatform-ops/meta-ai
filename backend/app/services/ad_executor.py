"""
Ad Executor — Autonomous pipeline that runs when a paid ad is approved.

Flow:
  1. Load draft + user's ad account + preferences
  2. Generate campaign strategy (interests + geo via MCP)
  3. Stage Advantage+ OUTCOME_SALES campaign via MCP
  4. Update draft status to 'active' or 'failed'
  5. Log to campaign_logs audit trail

NOTE: Competitor research + angle analysis are handled at DRAFT GENERATION
time (content_generator.py), NOT here. The executor publishes the approved
draft exactly as the user approved it — no post-approval content mutation.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..db.supabase_client import get_supabase
from .mcp_client import mcp_client, MCPError
from .targeting_engine import generate_campaign_strategy, build_adset_payload, _extract_keywords, _parse_mcp_json
from .audience_sync import sync_audience_for_niche, query_niche_customers_count

logger = logging.getLogger(__name__)

# ── Budget mapping ────────────────────────────────────────────────────────────

BUDGET_MAP = {
    "conservative_$10": 10.0,  # legacy
    "moderate_$30": 30.0,      # legacy
    "aggressive_$50": 50.0,    # legacy
    "conservative": 10.0,
    "moderate": 30.0,
    "aggressive": 50.0,
}


def _calculate_bid_amount(product_price: float | None, objective: str) -> int:
    """
    Calculate COST_CAP bid amount in minor currency units (paisa/cents).
    - TRAFFIC/ENGAGEMENT: 2-5% of product price (use 3%)
    - SALES: 25-30% of product price (use 27%)
    Returns 0 if no price available (fallback to LOWEST_COST_WITHOUT_CAP).
    """
    if not product_price or product_price <= 0:
        return 0
    if objective == "OUTCOME_SALES":
        cpr = product_price * 0.27
    else:
        cpr = product_price * 0.03
    bid_minor = int(cpr * 100)
    return max(bid_minor, 100)  # floor at 1 unit of currency


# ── Organic post publishing ───────────────────────────────────────────────────

async def execute_organic_post(draft_id: str) -> dict:
    """
    Publish an approved organic draft to the user's Facebook Page.

    Flow:
      1. Load the draft and verify it's approved + organic
      2. Load the user's ad account (for the Meta access token)
      3. Fetch the user's Facebook Pages using the user access token
      4. Exchange the user token for a Page access token
      5. Publish via POST /{page-id}/feed
      6. Update draft status to 'active' or 'failed'
    """
    import httpx
    from ..core.config import get_settings

    settings = get_settings()
    META_BASE = f"https://graph.facebook.com/{settings.META_API_VERSION}"
    supabase = get_supabase()

    # ── 1. Load draft ────────────────────────────────────────────────────────
    draft_result = (
        supabase.table("content_drafts")
        .select("*")
        .eq("id", draft_id)
        .execute()
    )
    if not draft_result.data:
        return {"success": False, "error": "Draft not found"}

    draft = draft_result.data[0]

    if draft["status"] != "approved":
        return {"success": False, "error": f"Draft status is '{draft['status']}', expected 'approved'"}

    if draft["draft_type"] != "organic":
        return {"success": False, "error": "Only organic drafts use this executor"}

    # ── 2. Load ad account (for user access token) ───────────────────────────
    account_query = supabase.table("ad_accounts").select("*").eq("is_active", True)
    if draft.get("ad_account_id"):
        account_query = account_query.eq("id", draft["ad_account_id"])
    else:
        account_query = account_query.eq("user_id", draft["user_id"])

    account_result = account_query.limit(1).execute()

    if not account_result.data:
        supabase.table("content_drafts").update({
            "status": "failed",
            "error_message": "No active Meta ad account found",
        }).eq("id", draft_id).execute()
        return {"success": False, "error": "No active ad account"}

    account = account_result.data[0]
    user_access_token = account["access_token"]

    # ── 3. Mark as publishing ────────────────────────────────────────────────
    supabase.table("content_drafts").update({
        "status": "publishing",
    }).eq("id", draft_id).execute()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # ── 4. Fetch user's Facebook Pages ───────────────────────────────
            pages_resp = await client.get(
                f"{META_BASE}/me/accounts",
                params={
                    "fields": "id,name,access_token",
                    "access_token": user_access_token,
                },
            )
            pages_resp.raise_for_status()
            pages = pages_resp.json().get("data", [])

            if not pages:
                raise RuntimeError(
                    "No Facebook Pages found. The user must have admin access to "
                    "at least one Page to publish organic posts."
                )

            # Use the first Page (could be extended to let user choose)
            page = pages[0]
            page_id = page["id"]
            page_access_token = page["access_token"]
            page_name = page.get("name", page_id)

            # ── 5. Publish to Page feed ──────────────────────────────────────
            message_parts = []
            if draft.get("headline"):
                message_parts.append(draft["headline"])
            if draft.get("body_text"):
                message_parts.append(draft["body_text"])
            message = "\n\n".join(message_parts)

            # Attach link if available in user preferences
            prefs_result = (
                supabase.table("user_preferences")
                .select("website_url")
                .eq("user_id", draft["user_id"])
                .execute()
            )
            website_url = None
            if prefs_result.data:
                website_url = prefs_result.data[0].get("website_url")

            image_url = draft.get("image_url")
            has_public_image = image_url and image_url.startswith("http")

            if has_public_image:
                # Post as a photo — visible to everyone on the Page
                post_data = {
                    "url": image_url,
                    "caption": message + (f"\n\n{website_url}" if website_url else ""),
                    "access_token": page_access_token,
                    "published": "true",
                }
                publish_resp = await client.post(
                    f"{META_BASE}/{page_id}/photos",
                    data=post_data,
                )
            else:
                # Text-only post (with optional link)
                post_data = {
                    "message": message,
                    "access_token": page_access_token,
                    "published": "true",
                }
                if website_url:
                    post_data["link"] = website_url
                publish_resp = await client.post(
                    f"{META_BASE}/{page_id}/feed",
                    data=post_data,
                )

            publish_resp.raise_for_status()
            publish_data = publish_resp.json()
            post_id = publish_data.get("id", "")

    except Exception as e:
        logger.error(f"Organic post failed for draft {draft_id}: {e}")
        supabase.table("content_drafts").update({
            "status": "failed",
            "error_message": str(e),
        }).eq("id", draft_id).execute()

        # Audit log
        supabase.table("campaign_logs").insert({
            "user_id": draft["user_id"],
            "ad_account_id": account["id"],
            "action": "error",
            "payload": {"draft_id": draft_id, "type": "organic"},
            "status": "failed",
            "error_message": str(e),
            "ai_reasoning": f"Attempted to publish organic post from draft {draft_id}",
        }).execute()

        return {"success": False, "error": str(e)}

    # ── 6. Update draft → active ─────────────────────────────────────────────
    supabase.table("content_drafts").update({
        "status": "active",
        "meta_campaign_id": post_id,  # reuse field to store the Page post ID
        "published_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", draft_id).execute()

    # Audit log
    supabase.table("campaign_logs").insert({
        "user_id": draft["user_id"],
        "ad_account_id": account["id"],
        "action": "campaign_created",
        "meta_campaign_id": post_id,
        "payload": {
            "draft_id": draft_id,
            "type": "organic",
            "page_id": page_id,
            "page_name": page_name,
        },
        "result": publish_data,
        "status": "success",
        "ai_reasoning": f"Published organic post to Page '{page_name}' ({page_id})",
    }).execute()

    logger.info(f"Organic post published: draft={draft_id}, post_id={post_id}, page={page_name}")

    return {
        "success": True,
        "post_id": post_id,
        "page_id": page_id,
        "page_name": page_name,
    }


async def _build_client_profile(draft: dict, preferences: dict, supabase) -> dict:
    """
    Build a client_profile dict for the targeting engine from draft,
    preferences, and product data.

    CRITICAL: When a product is attached, the profile is built ENTIRELY
    from the product's own data (description, type, tags). The parent
    business description and global industry_niche are NOT passed to
    prevent context bleeding (e.g., "Digital Marketing" interests on a
    honey product).
    """
    product_description = ""
    product_type = ""
    product_niche = ""
    has_product = False

    if draft.get("product_id"):
        prod_result = (
            supabase.table("products")
            .select("description, product_type, name, tags")
            .eq("id", draft["product_id"])
            .execute()
        )
        if prod_result.data:
            prod = prod_result.data[0]
            product_description = prod.get("description") or ""
            product_type = prod.get("product_type") or ""
            # Derive niche from product tags/name, NOT from business preferences
            product_niche = prod.get("tags") or prod.get("name") or ""
            has_product = True

    # Fallback: use ad body text as product context
    if not product_description:
        product_description = draft.get("body_text", "")

    target_cities = preferences.get("target_cities", [])
    target_country = preferences.get("target_country", "PK")

    # Also check draft-level targeting overrides
    if draft.get("targeting") and isinstance(draft["targeting"], dict):
        draft_targeting = draft["targeting"]
        if draft_targeting.get("target_cities"):
            target_cities = draft_targeting["target_cities"]
        if draft_targeting.get("target_country"):
            target_country = draft_targeting["target_country"]

    return {
        "product_description": product_description,
        "target_cities": target_cities,
        "target_country": target_country,
        # When a product is attached: use product's own niche/type, NOT global business context
        # This prevents "Digital Marketing" interests bleeding into a "Honey" ad
        "industry_niche": product_niche if has_product else preferences.get("industry_niche", ""),
        "product_type": product_type,
        "business_description": "" if has_product else preferences.get("business_description", ""),
    }


def _resolve_ad_niche(draft: dict, client_profile: dict, supabase) -> str:
    """
    Determine the niche/category for this specific ad.
    Used by the audience router to scope customer data correctly.

    Priority: product category > industry_niche > fallback from ad text.
    """
    # 1. If draft has a product_id, use the product's type/category
    if draft.get("product_id"):
        try:
            prod = (
                supabase.table("products")
                .select("product_type, name")
                .eq("id", draft["product_id"])
                .maybe_single()
                .execute()
            )
            if prod.data:
                return prod.data.get("product_type") or prod.data.get("name", "")
        except Exception:
            pass

    # 2. Derive from headline keywords (e.g., "Chatbots" from "Boost Your Brand with Chatbots!")
    headline = draft.get("headline", "")
    if headline:
        noise_words = {"boost", "your", "brand", "with", "the", "a", "an", "for",
                       "and", "of", "to", "in", "our", "get", "best", "top", "new",
                       "how", "why", "now", "today", "free", "buy", "try", "more",
                       "discover", "unlock", "scale", "grow", "pure"}
        words = [w.strip("!?.,;:'\"") for w in headline.split()
                 if w.strip("!?.,;:'\"").lower() not in noise_words and len(w.strip("!?.,;:'\"")) > 2]
        if words:
            return words[0]

    # 3. Fallback to industry_niche from preferences
    return client_profile.get("industry_niche", "general")


async def execute_approved_ad(draft_id: str) -> dict:
    """
    Full autonomous execution pipeline for an approved paid ad draft.

    Returns dict with success status and meta IDs or error message.
    """
    supabase = get_supabase()

    # ── 1. Load draft ────────────────────────────────────────────────────────
    draft_result = (
        supabase.table("content_drafts")
        .select("*")
        .eq("id", draft_id)
        .execute()
    )
    if not draft_result.data:
        return {"success": False, "error": "Draft not found"}

    draft = draft_result.data[0]

    if draft["status"] != "approved":
        return {"success": False, "error": f"Draft status is '{draft['status']}', expected 'approved'"}

    if draft["draft_type"] != "paid":
        return {"success": False, "error": "Only paid drafts trigger MCP execution"}

    # ── 2. Load ad account + access token ────────────────────────────────────
    account_query = supabase.table("ad_accounts").select("*").eq("is_active", True)

    if draft.get("ad_account_id"):
        account_query = account_query.eq("id", draft["ad_account_id"])
    else:
        account_query = account_query.eq("user_id", draft["user_id"])

    account_result = account_query.limit(1).execute()

    if not account_result.data:
        supabase.table("content_drafts").update({
            "status": "failed",
            "error_message": "No active Meta ad account found",
        }).eq("id", draft_id).execute()
        return {"success": False, "error": "No active ad account"}

    account = account_result.data[0]
    access_token = account["access_token"]
    meta_account_id = account["meta_account_id"]
    pixel_id = None  # Resolved from product below (pixel-per-product architecture)
    facebook_page_id = account.get("facebook_page_id")
    instagram_actor_id = account.get("instagram_actor_id")

    # ── 3. Load user preferences ─────────────────────────────────────────────
    prefs_result = (
        supabase.table("user_preferences")
        .select("*")
        .eq("user_id", draft["user_id"])
        .execute()
    )
    preferences = prefs_result.data[0] if prefs_result.data else {}

    # ── 4. Mark as publishing ────────────────────────────────────────────────
    supabase.table("content_drafts").update({
        "status": "publishing",
    }).eq("id", draft_id).execute()

    # ── 5. Build client profile ─────────────────────────────────────────────
    client_profile = await _build_client_profile(draft, preferences, supabase)
    target_country = client_profile.get("target_country", "PK")

    # ── 6. SMART AUDIENCE ROUTING — Niche Check ─────────────────────────────
    # Determine the ad's niche from product or industry context
    ad_niche = _resolve_ad_niche(draft, client_profile, supabase)
    product_id = draft.get("product_id")
    audience_route = "cold"  # default: interest-based cold targeting
    niche_audience_ids = []

    # Check if we have past customer data for THIS SPECIFIC niche
    niche_customer_count = query_niche_customers_count(
        draft["user_id"], ad_niche, product_id,
    )
    if niche_customer_count >= 100:
        # DATA-RICH path: enough data to build a meaningful Custom Audience
        audience_route = "data_rich"
        logger.info(
            "ROUTING [data-rich] draft %s: %d customers for niche '%s' — will use LAL",
            draft_id, niche_customer_count, ad_niche,
        )
        try:
            audience_result = await sync_audience_for_niche(
                draft["user_id"], ad_niche, product_id,
            )
            if audience_result.get("success"):
                lal_id = audience_result.get("lookalike_audience_id")
                ca_id = audience_result.get("custom_audience_id")
                if lal_id:
                    niche_audience_ids.append({"id": lal_id})
                elif ca_id:
                    niche_audience_ids.append({"id": ca_id})
        except Exception as e:
            logger.warning("Audience sync failed for niche '%s', falling back to cold: %s", ad_niche, e)
            audience_route = "cold"
    else:
        logger.info(
            "ROUTING [cold] draft %s: only %d customers for niche '%s' — using interest targeting",
            draft_id, niche_customer_count, ad_niche,
        )

    # ── 7. Resolve targeting interests ────────────────────────────────────────
    # Prefer the already-validated interests from targeting_spec (what the user
    # saw on the draft card) so there is no mismatch between display and Meta.
    # Only fall back to regenerating via generate_campaign_strategy() when the
    # draft has no usable targeting_spec.
    _raw_spec = draft.get("targeting_spec")
    if isinstance(_raw_spec, str):
        try:
            _raw_spec = json.loads(_raw_spec)
        except Exception:
            _raw_spec = None

    _saved_interests = []
    if isinstance(_raw_spec, dict):
        _saved_interests = [
            i for i in (_raw_spec.get("validated_interests") or [])
            if not str(i.get("id", "")).startswith("ai_")  # skip fallback/synthetic IDs
        ]

    if _saved_interests:
        # Reuse the interests the user already approved on the draft card
        logger.info(
            "Draft %s: reusing %d saved interests from targeting_spec",
            draft_id, len(_saved_interests),
        )
        strategy = await generate_campaign_strategy(client_profile, access_token)
        targeting = {
            "age_min": strategy.get("age_min", 18),
            "age_max": strategy.get("age_max", 65),
            "geo_locations": strategy["geo_locations"],
        }
        # Override interests with the ones from targeting_spec
        saved_interests = _saved_interests
    else:
        # No usable saved interests — regenerate from scratch
        logger.info("Draft %s: no saved interests, regenerating via MCP", draft_id)
        strategy = await generate_campaign_strategy(client_profile, access_token)
        targeting = {
            "age_min": strategy.get("age_min", 18),
            "age_max": strategy.get("age_max", 65),
            "geo_locations": strategy["geo_locations"],
        }
        saved_interests = strategy.get("interests", [])

    # ── ROUTING DECISION: cold vs data-rich ──────────────────────────────────
    if audience_route == "data_rich" and niche_audience_ids:
        # DATA-RICH: use LAL/Custom Audience, EMPTY the interest targeting
        targeting["custom_audiences"] = niche_audience_ids
        # Do NOT add flexible_spec — let Advantage+ optimize from the LAL seed
        logger.info(
            "Draft %s: DATA-RICH mode — LAL audience %s, flexible_spec EMPTY",
            draft_id, niche_audience_ids,
        )
    else:
        # COLD START: use validated interests only, NO custom audiences
        if saved_interests:
            targeting["flexible_spec"] = [
                {"interests": [{"id": i["id"], "name": i["name"]} for i in saved_interests]}
            ]
        logger.info(
            "Draft %s: COLD mode — %d interest(s), no custom audiences",
            draft_id, len(saved_interests),
        )

    # NOTE: locales/languages intentionally omitted — restricting language
    # kills reach in regions like Pakistan. Left empty to target all languages.
    if strategy.get("persona_reasoning"):
        logger.info("Persona for draft %s: %s", draft_id, strategy["persona_reasoning"])

    # ── 8. Determine budget ──────────────────────────────────────────────────
    budget_currency = preferences.get("budget_currency", "USD")
    daily_budget = draft.get("proposed_budget")
    if not daily_budget:
        budget_level = preferences.get("ad_budget_level", "conservative")
        if budget_level == "custom" and preferences.get("custom_budget"):
            daily_budget = float(preferences["custom_budget"])
        else:
            daily_budget = BUDGET_MAP.get(budget_level, 10.0)

    # ── 9. Resolve product context (landing URL + image) ─────────────────────
    FALLBACK_IMAGE = "https://images.unsplash.com/photo-1558642452-9d2a7deb7f62?w=1080&q=80"  # honey/food placeholder

    link_url = preferences.get("website_url") or "https://example.com"
    image_url = draft.get("image_url")

    product_price = None
    if draft.get("product_id"):
        prod_result = (
            supabase.table("products")
            .select("landing_url, image_url, price, product_type, pixel_id")
            .eq("id", draft["product_id"])
            .execute()
        )
        if prod_result.data:
            product = prod_result.data[0]
            if product.get("landing_url"):
                link_url = product["landing_url"]
            if product.get("image_url") and not image_url:
                image_url = product["image_url"]
            product_price = product.get("price")
            if product.get("product_type"):
                client_profile["product_type"] = product["product_type"]
            # Pixel-per-product: each product/URL has its own pixel for conversion tracking
            if product.get("pixel_id"):
                pixel_id = product["pixel_id"]

    # Draft-level pixel overrides product pixel (user explicitly attached a pixel)
    if draft.get("pixel_id"):
        pixel_id = draft["pixel_id"]

    # Draft-level destination URL overrides everything (user chose where this ad goes)
    if draft.get("destination_url"):
        link_url = draft["destination_url"]

    # Detect media type from URL extension
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    media_ext = (image_url or "").rsplit(".", 1)[-1].lower() if image_url else ""
    is_video = f".{media_ext}" in VIDEO_EXTENSIONS

    # For video ads, resolve a separate thumbnail image (product image or fallback)
    # Meta requires image_hash or image_url in video_data for the thumbnail
    video_thumbnail = None
    if is_video:
        # Priority 1: Draft-level thumbnail (user uploaded)
        if draft.get("thumbnail_url"):
            video_thumbnail = draft["thumbnail_url"]
        # Priority 2: Product image
        elif draft.get("product_id"):
            thumb_result = (
                supabase.table("products")
                .select("image_url")
                .eq("id", draft["product_id"])
                .execute()
            )
            if thumb_result.data and thumb_result.data[0].get("image_url"):
                prod_img = thumb_result.data[0]["image_url"]
                # Only use if it's NOT the same video file
                prod_ext = prod_img.rsplit(".", 1)[-1].lower() if prod_img else ""
                if f".{prod_ext}" not in VIDEO_EXTENSIONS:
                    video_thumbnail = prod_img
        if not video_thumbnail:
            video_thumbnail = FALLBACK_IMAGE

    # Ensure we always have media — Meta ads without creative are useless
    if not image_url:
        image_url = FALLBACK_IMAGE
        is_video = False
        logger.info("Draft %s: no media found, using fallback placeholder", draft_id)

    # ── 10. Stage Advantage+ campaign via MCP ────────────────────────────────
    campaign_name = draft.get("headline") or f"AI Campaign — {draft_id[:8]}"

    # WhatsApp fallback: only when no pixel AND no website URL
    has_website = bool(link_url and link_url != "https://example.com")
    whatsapp_number = None
    if not pixel_id and not has_website:
        whatsapp_number = preferences.get("whatsapp_number")

    # CTA logic: use draft's CTA if set, otherwise smart default
    default_cta = "SHOP_NOW" if (pixel_id or has_website) else "WHATSAPP_MESSAGE"
    cta = draft.get("cta_type") or default_cta

    # Determine objective for CPR calculation
    objective = "OUTCOME_SALES" if pixel_id else "OUTCOME_TRAFFIC"

    # Profit-Protection: extract profit_margin from draft targeting OR product
    # Must read BEFORE strategy overwrites the targeting dict
    raw_targeting = draft.get("targeting")
    draft_targeting = raw_targeting or {}
    if isinstance(draft_targeting, str):
        try:
            draft_targeting = json.loads(draft_targeting)
        except (json.JSONDecodeError, TypeError):
            draft_targeting = {}
    if not isinstance(draft_targeting, dict):
        draft_targeting = {}

    # Source 1: draft targeting JSON
    profit_margin = draft_targeting.get("profit_margin")
    # Source 2: product table fallback
    if not profit_margin and draft.get("product_id"):
        pm_result = supabase.table("products").select("profit_margin").eq("id", draft["product_id"]).execute()
        if pm_result.data and pm_result.data[0].get("profit_margin"):
            profit_margin = pm_result.data[0]["profit_margin"]

    # Force convert to cents: margin * 0.7 * 100
    bid_amount = 0
    if profit_margin:
        try:
            pm_float = float(profit_margin)
            if pm_float > 0:
                bid_amount = int(pm_float * 0.7 * 100)
                bid_amount = max(bid_amount, 100)
        except (ValueError, TypeError):
            bid_amount = 0
    if bid_amount == 0:
        bid_amount = _calculate_bid_amount(product_price, objective)

    logger.info(
        "Draft %s: profit_margin=%s → bid_amount=%d (price=%s, obj=%s)",
        draft_id, profit_margin, bid_amount, product_price, objective,
    )

    stage_params = {
        "campaign_name": campaign_name,
        "daily_budget": daily_budget,
        "headline": draft.get("headline") or "",
        "body_text": draft["body_text"],
        "link_url": link_url,
        "image_url": video_thumbnail if is_video else image_url,
        "cta_type": cta,
        "targeting_json": json.dumps(targeting),
    }
    if strategy.get("objective_hint"):
        stage_params["objective_hint"] = strategy["objective_hint"]
    # Lock bid_strategy + bid_amount together — Meta requires both for Cost Cap
    if bid_amount > 0:
        stage_params["bid_amount"] = bid_amount
        stage_params["bid_strategy"] = "COST_CAP"
        logger.info("Draft %s: COST_CAP bid_amount=%d", draft_id, bid_amount)
    else:
        stage_params["bid_strategy"] = "LOWEST_COST_WITHOUT_CAP"
    if pixel_id:
        stage_params["pixel_id"] = pixel_id
        stage_params["tracking_specs"] = json.dumps([{
            "action.type": ["offsite_conversion"],
            "fb_pixel": [pixel_id],
        }])
    if is_video:
        stage_params["video_url"] = image_url  # image_url field holds any media URL
        logger.info("Draft %s: VIDEO detected (%s), will upload to Meta", draft_id, media_ext)
    if whatsapp_number:
        stage_params["whatsapp_number"] = whatsapp_number

    # Placement preference (from draft targeting override or user preferences)
    draft_placements = (draft.get("targeting") or {}).get("placements")
    ad_placements = draft_placements or preferences.get("ad_placements", "BOTH")
    stage_params["placements"] = ad_placements
    if facebook_page_id:
        stage_params["page_id"] = facebook_page_id
    if instagram_actor_id:
        stage_params["instagram_actor_id"] = instagram_actor_id

    try:
        result = await mcp_client.stage_campaign(
            meta_account_id,
            stage_params,
            access_token,
        )
    except MCPError as e:
        logger.error(f"MCP execution failed for draft {draft_id}: {e}")
        supabase.table("content_drafts").update({
            "status": "failed",
            "error_message": str(e),
        }).eq("id", draft_id).execute()

        # Audit log
        supabase.table("campaign_logs").insert({
            "user_id": draft["user_id"],
            "ad_account_id": account["id"],
            "action": "error",
            "payload": {"draft_id": draft_id, "targeting": targeting},
            "status": "failed",
            "error_message": str(e),
            "ai_reasoning": f"Attempted to stage Advantage+ campaign from draft {draft_id}",
        }).execute()

        return {"success": False, "error": str(e)}

    # ── 8. Parse MCP response ────────────────────────────────────────────────
    # The MCP tool returns a JSON string in the result content
    mcp_data = {}
    if isinstance(result, dict):
        content = result.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "")
            try:
                mcp_data = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                mcp_data = {"raw": text}
        else:
            mcp_data = result

    meta_campaign_id = mcp_data.get("campaign_id")
    meta_adset_id = mcp_data.get("adset_id")
    meta_ad_id = mcp_data.get("ad_id")

    # Check if MCP returned an error or incomplete funnel (campaign + adset + ad all required)
    creative_err = mcp_data.get("creative_error")
    if mcp_data.get("error") or not meta_campaign_id or (not meta_ad_id and creative_err):
        error_msg = mcp_data.get("error") or creative_err or "MCP returned no campaign_id"
        logger.error(f"Campaign staging failed for draft {draft_id}: {error_msg}")
        supabase.table("content_drafts").update({
            "status": "failed",
            "error_message": error_msg,
        }).eq("id", draft_id).execute()
        supabase.table("campaign_logs").insert({
            "user_id": draft["user_id"],
            "ad_account_id": account["id"],
            "action": "error",
            "payload": {"draft_id": draft_id, "targeting": targeting},
            "result": mcp_data,
            "status": "failed",
            "error_message": error_msg,
            "ai_reasoning": f"stage_advanced_campaign returned error at step: {mcp_data.get('step', 'unknown')}",
        }).execute()
        return {"success": False, "error": error_msg}

    # ── 9. Update draft → active ─────────────────────────────────────────────
    # Sync targeting_spec with the final interests actually sent to Meta
    _final_interests = []
    if targeting.get("flexible_spec"):
        _final_interests = targeting["flexible_spec"][0].get("interests", [])
    _final_spec = json.dumps({
        "target_country": client_profile.get("target_country", ""),
        "validated_interests": _final_interests,
        "suggested_keywords": [i["name"] for i in _final_interests],
    })
    supabase.table("content_drafts").update({
        "status": "active",
        "meta_campaign_id": meta_campaign_id,
        "meta_adset_id": meta_adset_id,
        "meta_ad_id": meta_ad_id,
        "targeting": targeting,
        "targeting_spec": _final_spec,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", draft_id).execute()

    # ── 10. Audit log ────────────────────────────────────────────────────────
    supabase.table("campaign_logs").insert({
        "user_id": draft["user_id"],
        "ad_account_id": account["id"],
        "action": "campaign_created",
        "meta_campaign_id": meta_campaign_id,
        "meta_adset_id": meta_adset_id,
        "meta_ad_id": meta_ad_id,
        "payload": {
            "draft_id": draft_id,
            "daily_budget": daily_budget,
            "targeting": targeting,
        },
        "result": mcp_data,
        "status": "success",
        "ai_reasoning": f"Auto-created from approved draft. Targeting: {len(targeting.get('flexible_spec', [{}])[0].get('interests', []))} interest(s), age {targeting.get('age_min')}-{targeting.get('age_max')}",
    }).execute()

    return {
        "success": True,
        "campaign_id": meta_campaign_id,
        "adset_id": meta_adset_id,
        "ad_id": meta_ad_id,
    }
