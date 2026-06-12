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
from .audience_sync import sync_audience_for_niche, query_niche_customers_count, _register_audience
from .special_ad_category_detector import detect_for_draft
from .sac_reconciler import schedule_reconciliation
from .waba_validator import validate_waba_assignment


async def _ensure_waba_assigned_for_publish(
    *,
    stage_params: dict,
    user_access_token: str,
    page_id: str,
    log_prefix: str = "",
) -> None:
    """Pre-publish guard for Click-to-WhatsApp ads.

    If the publish targets WhatsApp messaging, verify Meta recognises the
    requested phone number as a WABA assigned to the chosen Page. Raises
    ``ValueError`` with a clear, user-facing message when Meta has data and
    the number is not on the assigned list — the route handler converts
    this into HTTP 400 instead of letting Meta fail the ad-set creation
    with an opaque code.

    No-op for non-WhatsApp publishes. Permissive when the validator can't
    reach Meta or lacks scope (returns valid=None).
    """
    destination = (stage_params.get("destination_type_hint") or "").upper()
    apps_raw = stage_params.get("selected_messaging_apps") or "[]"
    try:
        apps = json.loads(apps_raw) if isinstance(apps_raw, str) else apps_raw
    except Exception:
        apps = []
    is_wa_publish = (
        destination == "WHATSAPP"
        or (destination == "MESSAGING" and "WHATSAPP" in {str(a).upper() for a in apps})
    )
    if not is_wa_publish:
        return

    wa_number = (stage_params.get("whatsapp_number") or "").strip()
    if not wa_number:
        raise ValueError(
            "WhatsApp destination selected but no whatsapp_number is set on the "
            "draft. Add a WhatsApp Business number in Settings and retry."
        )
    if not page_id:
        raise ValueError(
            "WhatsApp destination selected but the workspace has no Facebook "
            "Page connected. Pick a Page in Settings → Meta Connection and retry."
        )

    check = await validate_waba_assignment(
        page_id=page_id,
        page_access_token=user_access_token,
        user_access_token=user_access_token,
        required_phone_e164=wa_number,
    )
    if check.valid is False:
        # Hard rejection — block the publish with the actionable reason Meta
        # would have hidden behind subcode 100/2700 / silent re-routing.
        logger.warning(
            "%sWABA validation FAILED — phone=%s page=%s available=%s",
            log_prefix, wa_number, page_id, check.available_numbers,
        )
        raise ValueError(check.error_reason or "Number not assigned to Page as a WABA.")
    if check.valid is None:
        logger.info(
            "%sWABA validation skipped — could not reach Meta with sufficient "
            "scope (%s). Continuing with publish.",
            log_prefix, check.error_reason or "unknown",
        )
    else:
        logger.info("%sWABA %s confirmed on page %s", log_prefix, wa_number, page_id)


def _sac_list_for_draft(draft: dict) -> list[str]:
    """Derive the SAC category list to reconcile against, from a draft row.

    A draft's persisted ``special_ad_category`` is the source of truth. The
    legacy hiring flag falls back to EMPLOYMENT. Returns ``[]`` for non-SAC
    drafts so reconciliation is skipped (no silent strip risk).
    """
    cat = (draft or {}).get("special_ad_category")
    if cat:
        return [cat]
    if (draft or {}).get("is_employment_ad"):
        return ["EMPLOYMENT"]
    return []


# ── EU Digital Services Act (DSA) ad-transparency helpers ────────────────────
#
# Meta enforces DSA payor/beneficiary on every ad creative whose targeting
# reaches an EU/EEA country. Without these fields, ad creation fails with:
#   #100 / subcode 3858081 — "Enter the person or organisation being
#   promoted by an ad."
# We auto-detect EU/EEA in the targeting and derive the names from the
# workspace's business profile so the user doesn't have to enter anything.

_EU_EEA_COUNTRIES = frozenset({
    # EU member states
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI",
    "FR", "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT",
    "NL", "PL", "PT", "RO", "SE", "SI", "SK",
    # EEA non-EU (Iceland / Liechtenstein / Norway)
    "IS", "LI", "NO",
    # UK applies an equivalent regime under the OSA — Meta enforces the
    # same DSA fields when targeting GB.
    "GB",
})


def _targeting_includes_eu(targeting_obj: dict | None) -> bool:
    """True if any country in the targeting geo is EU/EEA/UK."""
    if not isinstance(targeting_obj, dict):
        return False
    geo = targeting_obj.get("geo_locations") or {}
    countries = list(geo.get("countries") or [])
    for c in (geo.get("cities") or []):
        if isinstance(c, dict) and c.get("country"):
            countries.append(c["country"])
    for r in (geo.get("regions") or []):
        if isinstance(r, dict) and r.get("country"):
            countries.append(r["country"])
    return any(
        isinstance(c, str) and c.upper() in _EU_EEA_COUNTRIES
        for c in countries
    )


def _resolve_dsa_fields(
    *,
    client_profile: dict | None = None,
    preferences: dict | None = None,
    workspace: dict | None = None,
) -> tuple[str, str]:
    """Derive (dsa_payor, dsa_beneficiary) from the workspace's business
    profile. Falls back through workspace → client_profile → preferences.
    Returns empty strings when nothing is set — the caller should treat that
    as a soft warning (Meta will reject EU ads without these)."""
    sources = (workspace or {}, client_profile or {}, preferences or {})
    for src in sources:
        name = (src.get("business_name") or "").strip()
        if name:
            # Same name for both — first-party advertising is the common case.
            # When we later add separate beneficiary support (agency model),
            # we'll branch here on a workspace.dsa_beneficiary override.
            return name, name
    return "", ""


def _attach_dsa_if_eu(
    stage_params: dict,
    targeting_obj: dict | None,
    *,
    client_profile: dict | None = None,
    preferences: dict | None = None,
    workspace: dict | None = None,
    log_prefix: str = "",
) -> None:
    """Mutates ``stage_params``: if targeting includes EU/EEA/UK, attaches
    ``dsa_payor`` + ``dsa_beneficiary`` derived from the business profile.
    Logs a warning when EU is targeted but no business_name is configured —
    Meta will reject such an ad with subcode 3858081."""
    if not _targeting_includes_eu(targeting_obj):
        return
    payor, beneficiary = _resolve_dsa_fields(
        client_profile=client_profile,
        preferences=preferences,
        workspace=workspace,
    )
    if payor:
        stage_params["dsa_payor"] = payor
        stage_params["dsa_beneficiary"] = beneficiary or payor
        logger.info(
            "%sDSA payor/beneficiary set: %s (EU/EEA targeting detected)",
            log_prefix, payor,
        )
    else:
        logger.warning(
            "%sEU/EEA targeting but no business_name found — Meta will likely "
            "reject this ad with #3858081. Set business_name on the workspace "
            "or user_preferences.", log_prefix,
        )

logger = logging.getLogger(__name__)


def _enrich_meta_error(raw_error: str) -> str:
    """Add user-friendly guidance to common Meta API errors."""
    err_lower = raw_error.lower()
    # Check most specific errors first
    if "1885183" in raw_error or "development mode" in err_lower:
        return (
            "Your Meta App is in Development Mode — Meta blocks ad creative creation in dev mode. "
            "Go to developers.facebook.com → Your App → App Review → switch to Live mode. "
            f"(Original: {raw_error})"
        )
    if "error 190" in err_lower or ("oauthexception" in err_lower and ("expired" in err_lower or "log in" in err_lower)):
        return f"Your Meta access token has expired. Please re-authenticate in Settings → Meta Connect. (Original: {raw_error})"
    return raw_error


def resolve_workspace_credentials(draft: dict, supabase=None) -> dict | None:
    """
    Resolve Meta credentials from the draft's workspace.

    Returns dict with: access_token, meta_account_id, facebook_page_id,
    instagram_actor_id, pixel_id, business_name, target_country, tracking_mode.
    Returns None if no workspace is linked (falls back to legacy ad_accounts flow).
    """
    if supabase is None:
        supabase = get_supabase()

    workspace_id = draft.get("workspace_id")
    if not workspace_id:
        return None

    ws_result = (
        supabase.table("workspaces")
        .select("*")
        .eq("id", workspace_id)
        .limit(1)
        .execute()
    )
    if not ws_result.data:
        return None

    ws = ws_result.data[0]

    # Must have at minimum an ad account ID to proceed
    if not ws.get("meta_ad_account_id"):
        return None

    # Resolve access token: workspace-level first, fallback to ad_accounts
    access_token = ws.get("meta_access_token")
    if not access_token:
        aa_result = (
            supabase.table("ad_accounts")
            .select("access_token")
            .eq("workspace_id", workspace_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not aa_result.data:
            # Final fallback: ad_accounts by user_id
            aa_result = (
                supabase.table("ad_accounts")
                .select("access_token")
                .eq("user_id", draft["user_id"])
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
        if aa_result.data:
            access_token = aa_result.data[0]["access_token"]

    if not access_token:
        return None

    facebook_page_id = ws.get("meta_page_id")
    instagram_actor_id = ws.get("meta_ig_actor_id")

    # Fallback: if workspace doesn't have page/IG IDs, pull from ad_accounts
    if not facebook_page_id or not instagram_actor_id:
        aa_result = (
            supabase.table("ad_accounts")
            .select("facebook_page_id, instagram_actor_id")
            .eq("meta_account_id", ws["meta_ad_account_id"])
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if aa_result.data:
            aa = aa_result.data[0]
            if not facebook_page_id:
                facebook_page_id = aa.get("facebook_page_id")
            if not instagram_actor_id:
                instagram_actor_id = aa.get("instagram_actor_id")

    return {
        "access_token": access_token,
        "meta_account_id": ws["meta_ad_account_id"],
        "facebook_page_id": facebook_page_id,
        "instagram_actor_id": instagram_actor_id,
        "pixel_id": ws.get("meta_pixel_id"),
        "business_name": ws.get("business_name"),
        "target_country": ws.get("target_country", "PK"),
        "tracking_mode": ws.get("tracking_mode", "whatsapp_cod"),
    }

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

    # ── 2. Load credentials (workspace-first, fallback to ad_accounts) ──────
    ws_creds = resolve_workspace_credentials(draft, supabase)
    if ws_creds:
        user_access_token = ws_creds["access_token"]
        account = {"id": draft.get("ad_account_id") or "workspace", "access_token": user_access_token}
    else:
        account_query = supabase.table("ad_accounts").select("*").eq("is_active", True)
        if draft.get("ad_account_id"):
            account_query = account_query.eq("id", draft["ad_account_id"])
        else:
            account_query = account_query.eq("user_id", draft["user_id"])
            if draft.get("workspace_id"):
                account_query = account_query.eq("workspace_id", draft["workspace_id"])

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
            .select("description, product_type, name, tags, target_cities, target_country")
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

    # Robust city normalizer — Supabase JSONB sometimes stores arrays as the
    # JSON string '"[]"' instead of the JSON array `[]`. The string form is
    # truthy in Python and would (incorrectly) trigger the city-resolution
    # branch downstream, collapsing multi-country geo to a single country.
    def _normalize_cities(raw) -> list:
        if raw is None:
            return []
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str):
            stripped = raw.strip()
            if not stripped or stripped in ("[]", '""'):
                return []
            try:
                parsed = json.loads(stripped)
                return parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, ValueError):
                # Not JSON — treat as a comma-separated city list ("Lahore, Karachi")
                return [c.strip() for c in stripped.split(",") if c.strip()]
        return []

    # Geo priority: preferences → product override → draft.targeting override → draft.target_country column (highest)
    target_cities = _normalize_cities(preferences.get("target_cities"))
    target_country = preferences.get("target_country", "PK")

    # Per-product geo overrides
    if has_product and prod_result.data:
        prod = prod_result.data[0]
        prod_cities = _normalize_cities(prod.get("target_cities"))
        if prod_cities:
            target_cities = prod_cities
        if prod.get("target_country"):
            target_country = prod["target_country"]

    # Draft-level overrides via the targeting JSON blob
    if draft.get("targeting") and isinstance(draft["targeting"], dict):
        draft_targeting = draft["targeting"]
        draft_cities = _normalize_cities(draft_targeting.get("target_cities"))
        if draft_cities:
            target_cities = draft_cities
        if draft_targeting.get("target_country"):
            target_country = draft_targeting["target_country"]

    # Draft-level overrides via the dedicated `target_country` column — this is
    # what the country picker on the draft form actually writes to. Highest
    # priority because it's the user's most explicit per-draft choice. Supports
    # comma-separated multi-country values like "US,GB".
    if draft.get("target_country"):
        target_country = draft["target_country"]

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


# ── Funnel constants ─────────────────────────────────────────────────────────
PROSPECTING_BUDGET_RATIO = 0.80  # 80% to cold traffic
RETARGETING_BUDGET_RATIO = 0.20  # 20% to warm traffic
PIXEL_EVENT_THRESHOLD = 100      # min pixel events for LAL
RETARGET_LOOKBACK_DAYS = 14      # website visitors window
EXCLUSION_LOOKBACK_DAYS = 180    # exclude converters for 6 months

# Destinations that don't support funnel splitting (no pixel = no retargeting)
_NO_FUNNEL_DESTINATIONS = {"WHATSAPP", "INSTAGRAM_DM", "INSTANT_FORM", "MESSAGING", "PHONE_CALL"}


def _parse_mcp_response(result: dict) -> dict:
    """Parse MCP tool result from FastMCP content format."""
    if isinstance(result, dict):
        content = result.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "")
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return {"raw": text}
    return result


async def _check_pixel_event_count(
    pixel_id: str, access_token: str, event_name: str = "CompleteRegistration",
) -> int:
    """
    Check how many times a specific pixel event has fired recently.
    Used to decide LAL eligibility (need 100+ events for a quality seed).
    """
    try:
        result = await mcp_client.get_pixel_events(pixel_id, access_token)
        data = _parse_mcp_response(result)
        events = data.get("events", [])
        for evt in events:
            if evt.get("event", "").lower() == event_name.lower():
                return int(evt.get("count_7d", 0))
    except Exception as e:
        logger.warning("Failed to check pixel events for %s: %s", pixel_id, e)
    return 0


async def _build_retargeting_audiences(
    meta_account_id: str,
    access_token: str,
    pixel_id: str,
    facebook_page_id: str | None,
    instagram_actor_id: str | None,
    conversion_event: str,
    business_name: str,
    *,
    user_id: str = "",
    workspace_id: str | None = None,
    product_id: str | None = None,
) -> dict:
    """
    Build retargeting + exclusion audiences for Campaign 2.

    Returns:
        {
            "retarget_audience_ids": [{"id": "..."}],   # warm traffic to target
            "exclusion_audience_ids": [{"id": "..."}],   # converters to exclude
            "source": "pixel" | "engagement" | "none",
        }
    """
    retarget_ids = []
    exclusion_ids = []
    source = "none"

    # Strategy A: Pixel-based Website Custom Audience (warm visitors)
    if pixel_id:
        try:
            # Retarget: people who visited site (PageView) in last 14 days
            rt_result = await mcp_client.create_website_custom_audience(
                meta_account_id, pixel_id,
                f"{business_name} - Website Visitors {RETARGET_LOOKBACK_DAYS}d",
                access_token,
                retention_days=RETARGET_LOOKBACK_DAYS,
                event_name="PageView",
            )
            rt_data = _parse_mcp_response(rt_result)
            if rt_data.get("audience_id"):
                retarget_ids.append({"id": rt_data["audience_id"]})
                source = "pixel"
                _register_audience(get_supabase(), user_id, workspace_id, product_id,
                                   rt_data["audience_id"],
                                   f"{business_name} - Website Visitors {RETARGET_LOOKBACK_DAYS}d",
                                   "RETARGETING", pixel_id=pixel_id)
                logger.info("Retarget audience created: %s (PageView %dd)",
                            rt_data["audience_id"], RETARGET_LOOKBACK_DAYS)
        except Exception as e:
            logger.warning("Website retarget audience failed: %s", e)

        try:
            # Exclusion: people who already converted (e.g., CompleteRegistration)
            ex_result = await mcp_client.create_exclusion_audience(
                meta_account_id, pixel_id,
                f"{business_name} - {conversion_event} Exclude {EXCLUSION_LOOKBACK_DAYS}d",
                access_token,
                event_name=conversion_event,
                retention_days=EXCLUSION_LOOKBACK_DAYS,
            )
            ex_data = _parse_mcp_response(ex_result)
            if ex_data.get("audience_id"):
                exclusion_ids.append({"id": ex_data["audience_id"]})
                _register_audience(get_supabase(), user_id, workspace_id, product_id,
                                   ex_data["audience_id"],
                                   f"{business_name} - {conversion_event} Exclude {EXCLUSION_LOOKBACK_DAYS}d",
                                   "EXCLUSION", pixel_id=pixel_id)
                logger.info("Exclusion audience created: %s (%s %dd)",
                            ex_data["audience_id"], conversion_event, EXCLUSION_LOOKBACK_DAYS)
        except Exception as e:
            logger.warning("Exclusion audience failed: %s", e)

    # Strategy B: If no pixel retarget audience, try Engagement CA (FB/IG engagers)
    if not retarget_ids and facebook_page_id:
        try:
            eng_result = await mcp_client.create_engagement_custom_audience(
                meta_account_id,
                f"{business_name} - Page Engagers 90d",
                facebook_page_id,
                access_token,
                retention_days=90,
                engagement_type="PAGE_ENGAGEMENT",
            )
            eng_data = _parse_mcp_response(eng_result)
            if eng_data.get("audience_id"):
                retarget_ids.append({"id": eng_data["audience_id"]})
                source = "engagement"
                _register_audience(get_supabase(), user_id, workspace_id, product_id,
                                   eng_data["audience_id"],
                                   f"{business_name} - Page Engagers 90d",
                                   "ENGAGEMENT")
                logger.info("Engagement retarget audience: %s (Page 90d)", eng_data["audience_id"])
        except Exception as e:
            logger.warning("Engagement audience failed: %s", e)

    # Also try IG engagement if we have an IG actor
    if not retarget_ids and instagram_actor_id:
        try:
            ig_result = await mcp_client.create_engagement_custom_audience(
                meta_account_id,
                f"{business_name} - IG Engagers 90d",
                instagram_actor_id,
                access_token,
                retention_days=90,
                engagement_type="IG_ENGAGEMENT",
            )
            ig_data = _parse_mcp_response(ig_result)
            if ig_data.get("audience_id"):
                retarget_ids.append({"id": ig_data["audience_id"]})
                source = "engagement"
                _register_audience(get_supabase(), user_id, workspace_id, product_id,
                                   ig_data["audience_id"],
                                   f"{business_name} - IG Engagers 90d",
                                   "ENGAGEMENT")
                logger.info("IG engagement retarget audience: %s", ig_data["audience_id"])
        except Exception as e:
            logger.warning("IG engagement audience failed: %s", e)

    return {
        "retarget_audience_ids": retarget_ids,
        "exclusion_audience_ids": exclusion_ids,
        "source": source,
    }


def _validate_audience_ownership(
    supabase,
    product_id: str | None,
    audience_ids: list[dict],
    label: str,
) -> list[dict]:
    """
    SAFETY LOCK: Only allow audiences that belong to the same product.

    Audiences without a registry entry (legacy) are allowed through.
    Audiences registered to a DIFFERENT product are BLOCKED.
    """
    if not product_id or not audience_ids:
        return audience_ids

    meta_ids = [a["id"] for a in audience_ids if a.get("id")]
    if not meta_ids:
        return audience_ids

    try:
        result = (
            supabase.table("meta_audiences")
            .select("meta_audience_id, product_id")
            .in_("meta_audience_id", meta_ids)
            .execute()
        )
        registry = {r["meta_audience_id"]: r.get("product_id") for r in (result.data or [])}
    except Exception as e:
        logger.warning("Audience ownership check failed, allowing all: %s", e)
        return audience_ids

    safe = []
    for a in audience_ids:
        aid = a.get("id")
        registered_product = registry.get(aid)
        if registered_product is None:
            # Not in registry (legacy audience) — allow through
            safe.append(a)
        elif registered_product == product_id:
            safe.append(a)
        else:
            logger.warning(
                "BLOCKED %s audience %s: belongs to product %s, campaign product is %s",
                label, aid, registered_product, product_id,
            )

    return safe


# ── Multi-Draft A/B Test Validation & Execution ──────────────────────────────

def validate_ab_drafts(drafts: list[dict]) -> str | None:
    """
    Validate that a set of drafts can be launched together as an A/B test.
    All drafts must share the same product_id, destination_type, and be paid+pending.
    Returns an error message string if invalid, or None if valid.
    """
    if len(drafts) < 2:
        return "A/B test requires at least 2 drafts"
    if len(drafts) > 10:
        return "A/B test supports a maximum of 10 drafts"

    # All must be paid and pending
    for d in drafts:
        if d.get("draft_type") != "paid":
            return f"Draft '{d.get('headline', d['id'][:8])}' is not a paid ad"
        if d.get("status") != "pending":
            return f"Draft '{d.get('headline', d['id'][:8])}' status is '{d['status']}', expected 'pending'"

    # All must share the same product_id (including None — all-None is valid)
    product_ids = {d.get("product_id") for d in drafts}
    if len(product_ids) > 1:
        return "All selected drafts must belong to the same product to run as an A/B test"

    # All must share the same destination_type
    destinations = {d.get("destination_type") or "WEBSITE" for d in drafts}
    if len(destinations) > 1:
        dest_list = ", ".join(sorted(destinations))
        return f"All selected drafts must have the same destination ({dest_list} found). Meta requires all ads in an Ad Set to share the same destination"

    return None  # valid


async def execute_ab_test(draft_ids: list[str]) -> dict:
    """
    Execute multiple drafts as an A/B test under a single Campaign + Ad Set.
    Each draft becomes a separate Ad (creative variant) within the shared Ad Set.

    Uses the FIRST draft as the "anchor" for targeting, budget, and campaign settings.
    All drafts get their media/copy turned into individual ads.

    Returns dict with success status and meta IDs.
    """
    supabase = get_supabase()

    # ── 1. Load all drafts ───────────────────────────────────────────────────
    drafts = []
    for did in draft_ids:
        result = supabase.table("content_drafts").select("*").eq("id", did).execute()
        if not result.data:
            return {"success": False, "error": f"Draft {did} not found"}
        drafts.append(result.data[0])

    # ── 2. Validate compatibility ────────────────────────────────────────────
    validation_error = validate_ab_drafts(drafts)
    if validation_error:
        return {"success": False, "error": validation_error}

    # ── 3. Mark all drafts as approved ───────────────────────────────────────
    for d in drafts:
        supabase.table("content_drafts").update({
            "status": "approved",
        }).eq("id", d["id"]).execute()

    anchor = drafts[0]  # First draft drives targeting, budget, destination
    logger.info("A/B test: %d drafts, anchor=%s, product=%s, destination=%s",
                len(drafts), anchor["id"][:8], anchor.get("product_id"), anchor.get("destination_type"))

    # ── 4. Resolve credentials (from anchor draft) ───────────────────────────
    ws_creds = resolve_workspace_credentials(anchor, supabase)
    if ws_creds:
        access_token = ws_creds["access_token"]
        meta_account_id = ws_creds["meta_account_id"]
        facebook_page_id = ws_creds["facebook_page_id"]
        instagram_actor_id = ws_creds["instagram_actor_id"]
        pixel_id = None
        account = {"id": anchor.get("ad_account_id") or anchor.get("workspace_id") or "workspace"}
    else:
        account_query = supabase.table("ad_accounts").select("*").eq("is_active", True)
        if anchor.get("workspace_id"):
            account_query = account_query.eq("workspace_id", anchor["workspace_id"])
        else:
            account_query = account_query.eq("user_id", anchor["user_id"])
        account_result = account_query.limit(1).execute()
        if not account_result.data:
            _fail_drafts(supabase, drafts, "No active ad account found")
            return {"success": False, "error": "No active ad account found"}
        account = account_result.data[0]
        access_token = account["access_token"]
        meta_account_id = account["meta_account_id"]
        facebook_page_id = account.get("facebook_page_id", "")
        instagram_actor_id = account.get("instagram_actor_id", "")

    if not meta_account_id.startswith("act_"):
        meta_account_id = f"act_{meta_account_id}"

    # ── 5. Load preferences (scoped to the draft's workspace) ───────────────
    # user_preferences has a UNIQUE(user_id, workspace_id) constraint — each
    # workspace gets its own prefs row. Filtering only by user_id returns all
    # workspaces' rows and picks one non-deterministically, leaking the wrong
    # workspace's website_url, business_name, etc., into ads from a different
    # workspace.
    _prefs_query = supabase.table("user_preferences").select("*").eq("user_id", anchor["user_id"])
    if anchor.get("workspace_id"):
        _prefs_query = _prefs_query.eq("workspace_id", anchor["workspace_id"])
    prefs_result = _prefs_query.execute()
    preferences = prefs_result.data[0] if prefs_result.data else {}

    # ── 6. Resolve pixel from product ────────────────────────────────────────
    product_id = anchor.get("product_id")
    if product_id:
        prod_result = supabase.table("products").select("pixel_id").eq("id", product_id).limit(1).execute()
        if prod_result.data and prod_result.data[0].get("pixel_id"):
            pixel_id = prod_result.data[0]["pixel_id"]

    # ── 7. Build client profile & generate targeting (from anchor) ───────────
    client_profile = await _build_client_profile(anchor, preferences, supabase)
    business_name = preferences.get("business_name", "AI Campaign")

    try:
        strategy = await generate_campaign_strategy(client_profile, access_token)
    except Exception as e:
        logger.error("A/B test targeting failed: %s", e)
        _fail_drafts(supabase, drafts, f"Targeting generation failed: {e}")
        return {"success": False, "error": f"Targeting failed: {e}"}

    # Build targeting dict.
    # geo_locations fallback: split comma-separated target_country ("US,GB") into
    # ["US", "GB"] so multi-country drafts ship with both countries even when the
    # strategy step skipped/failed to populate geo_locations.
    _fallback_country_raw = client_profile.get("target_country", "US")
    _fallback_countries = [c.strip() for c in _fallback_country_raw.split(",") if c.strip()] or ["US"]
    targeting: dict[str, Any] = {
        "age_min": strategy.get("age_min", 18),
        "age_max": strategy.get("age_max", 65),
        "geo_locations": strategy.get("geo_locations", {"countries": _fallback_countries}),
    }
    if strategy.get("interests"):
        targeting["flexible_spec"] = [
            {"interests": [{"id": i["id"], "name": i["name"]} for i in strategy["interests"]]}
        ]

    # ── 8. Budget — sum of all drafts' proposed budgets ──────────────────────
    BUDGET_MAP = {"conservative": 10.0, "moderate": 30.0, "aggressive": 50.0}
    total_budget = 0.0
    for d in drafts:
        b = d.get("proposed_budget")
        if b and float(b) > 0:
            total_budget += float(b)
        else:
            total_budget += BUDGET_MAP.get(preferences.get("ad_budget_level", "moderate"), 30.0)
    daily_budget = round(total_budget, 2)

    # ── 9. Build combined media_items from ALL drafts ────────────────────────
    # Each draft becomes one (or more) media items → one ad per draft
    combined_media: list[dict] = []
    draft_meta_map: list[dict] = []  # tracks which media belongs to which draft

    for d in drafts:
        items = d.get("media_items") or []
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except (json.JSONDecodeError, TypeError):
                items = []

        if not items:
            # Fallback: build from image_url
            img = d.get("image_url")
            if img:
                ext = img.rsplit(".", 1)[-1].lower() if "." in img else ""
                media_type = "video" if ext in {"mp4", "mov", "avi", "webm"} else "image"
                items = [{"type": media_type, "url": img, "thumbnail_url": d.get("thumbnail_url", "")}]
            else:
                _fail_drafts(supabase, drafts, "No image or video attached to one or more drafts. Please add creatives before running A/B test.")
                return {"success": False, "error": "No image or video attached to one or more drafts. Please add creatives before running A/B test."}

        # Override headline/body per-draft by embedding in media item metadata
        for item in items:
            combined_media.append({
                **item,
                "_headline": d.get("headline") or "",
                "_body_text": d.get("body_text") or "",
                "_cta_type": d.get("cta_type") or "LEARN_MORE",
                "_draft_id": d["id"],
            })
            draft_meta_map.append({"draft_id": d["id"], "media_index": len(combined_media) - 1})

    # ── 10. Destination & objective routing (from anchor) ────────────────────
    draft_destination = anchor.get("destination_type") or "WEBSITE"
    link_url = anchor.get("destination_url") or anchor.get("image_url", "")
    if not link_url or not link_url.startswith("http"):
        product_url = ""
        if product_id:
            p = supabase.table("products").select("landing_url").eq("id", product_id).limit(1).execute()
            if p.data:
                product_url = p.data[0].get("landing_url", "")
        link_url = product_url or preferences.get("website_url", "")

    whatsapp_number = anchor.get("whatsapp_number") or preferences.get("whatsapp_number", "")
    cta = anchor.get("cta_type") or "LEARN_MORE"

    # ── 11. Build stage_params ───────────────────────────────────────────────
    anchor_headline = anchor.get("headline") or f"AI A/B — {anchor['id'][:8]}"
    campaign_name = f"[A/B TEST] {anchor_headline}"

    stage_params: dict[str, Any] = {
        "campaign_name": campaign_name,
        "daily_budget": daily_budget,
        "headline": anchor.get("headline") or "",
        "body_text": anchor["body_text"],
        "link_url": link_url,
        "cta_type": cta,
        "targeting_json": json.dumps(targeting),
        "media_items_json": json.dumps(combined_media),
    }

    # First media for legacy params
    first_media = combined_media[0] if combined_media else {"type": "image", "url": ""}
    if first_media["type"] == "video":
        stage_params["video_url"] = first_media["url"]
        stage_params["image_url"] = first_media.get("thumbnail_url", "")
    else:
        stage_params["image_url"] = first_media["url"]

    if strategy.get("objective_hint"):
        stage_params["objective_hint"] = strategy["objective_hint"]
    if pixel_id:
        stage_params["pixel_id"] = pixel_id
        stage_params["tracking_specs"] = json.dumps([{
            "action.type": ["offsite_conversion"],
            "fb_pixel": [pixel_id],
        }])
        stage_params["conversion_event"] = anchor.get("conversion_event") or "PURCHASE"
    if whatsapp_number:
        stage_params["whatsapp_number"] = whatsapp_number

    draft_placements = (anchor.get("targeting") or {}).get("placements")
    stage_params["placements"] = draft_placements or preferences.get("ad_placements", "BOTH")
    if facebook_page_id:
        stage_params["page_id"] = facebook_page_id
    if instagram_actor_id:
        stage_params["instagram_actor_id"] = instagram_actor_id
    stage_params["destination_type_hint"] = draft_destination
    stage_params["lead_form_id"] = anchor.get("lead_form_id") or ""

    # ── Special Ad Category — prefer cached value from generation time ────
    # The detector usually runs at draft creation in content_generator, which
    # also biases the targeting search-terms LLM to pick SAC-safe interests.
    # Here we just consume the cached value. Falls back to a fresh detection
    # for legacy drafts created before SAC support shipped.
    _cached_sac_category = anchor.get("special_ad_category")
    if _cached_sac_category:
        stage_params["special_ad_categories"] = json.dumps([_cached_sac_category])
        stage_params["enable_advantage_audience"] = True
        logger.info("Anchor %s: SAC=%s (cached from generation)", anchor.get("id"), _cached_sac_category)
    else:
        try:
            _product_for_sac = {}
            if anchor.get("product_id"):
                _p = supabase.table("products").select(
                    "name, description, product_type, tags, target_country"
                ).eq("id", anchor["product_id"]).limit(1).execute()
                if _p.data:
                    _product_for_sac = _p.data[0]
            _sac = await detect_for_draft(
                draft=anchor,
                workspace=client_profile,
                product=_product_for_sac,
                preferences=preferences,
            )
            if _sac.should_auto_apply and _sac.category:
                stage_params["special_ad_categories"] = json.dumps([_sac.category])
                stage_params["enable_advantage_audience"] = True
                logger.info(
                    "Anchor %s: SAC=%s (confidence=%.2f, fresh detection at publish) — %s",
                    anchor.get("id"), _sac.category, _sac.confidence, _sac.reasoning,
                )
                # Persist for next time / UI display
                try:
                    supabase.table("content_drafts").update({
                        "special_ad_category": _sac.category,
                        "special_ad_category_confidence": round(_sac.confidence, 2),
                        "special_ad_category_reasoning": _sac.reasoning[:500],
                    }).eq("id", anchor.get("id")).execute()
                except Exception:
                    pass
            elif _sac.category:
                logger.info(
                    "Anchor %s: SAC suggestion=%s (confidence=%.2f, below auto-apply threshold)",
                    anchor.get("id"), _sac.category, _sac.confidence,
                )
        except Exception as _sac_err:
            logger.warning("SAC detection failed for anchor %s: %s", anchor.get("id"), _sac_err)

    selected_apps = anchor.get("selected_messaging_apps") or []
    if selected_apps:
        stage_params["selected_messaging_apps"] = json.dumps(selected_apps)
    stage_params["call_phone_number"] = anchor.get("call_phone_number") or ""

    # EU DSA payor/beneficiary — auto-set when targeting reaches EU/EEA/UK.
    # Without these, Meta rejects with subcode 3858081 ("Enter the person
    # or organisation being promoted by an ad").
    _attach_dsa_if_eu(
        stage_params, targeting,
        client_profile=client_profile, preferences=preferences,
        log_prefix=f"A/B anchor {anchor.get('id')}: ",
    )

    # WhatsApp WABA pre-publish validator — fails fast with a clear error
    # if the draft's whatsapp_number isn't assigned to the page on Meta's
    # side, instead of letting the MCP stage call fail opaquely.
    try:
        await _ensure_waba_assigned_for_publish(
            stage_params=stage_params,
            user_access_token=access_token,
            page_id=facebook_page_id,
            log_prefix=f"A/B anchor {anchor.get('id')}: ",
        )
    except ValueError as e:
        _fail_drafts(supabase, drafts, str(e))
        return {"success": False, "error": str(e)}

    # ── 12. Stage campaign via MCP ───────────────────────────────────────────
    try:
        result = await mcp_client.stage_campaign(
            meta_account_id, stage_params, access_token,
        )
    except MCPError as e:
        logger.error("A/B test MCP execution failed: %s", e)
        enriched_err = _enrich_meta_error(str(e))
        _fail_drafts(supabase, drafts, enriched_err)
        return {"success": False, "error": enriched_err}

    mcp_data = _parse_mcp_response(result)
    meta_campaign_id = mcp_data.get("campaign_id")
    meta_adset_id = mcp_data.get("adset_id")
    meta_ad_ids = mcp_data.get("ad_ids", [])
    meta_ad_id = mcp_data.get("ad_id") or (meta_ad_ids[0] if meta_ad_ids else None)

    if not meta_campaign_id or (not meta_ad_id and mcp_data.get("creative_error")):
        error_msg = mcp_data.get("error") or mcp_data.get("creative_error") or "MCP returned no campaign_id"
        error_msg = _enrich_meta_error(error_msg)
        _fail_drafts(supabase, drafts, error_msg)
        return {"success": False, "error": error_msg}

    # ── 13. Update all drafts → active ───────────────────────────────────────
    _final_interests = []
    if targeting.get("flexible_spec"):
        _final_interests = targeting["flexible_spec"][0].get("interests", [])

    for idx, d in enumerate(drafts):
        ad_id_for_draft = meta_ad_ids[idx] if idx < len(meta_ad_ids) else meta_ad_id
        supabase.table("content_drafts").update({
            "status": "active",
            "meta_campaign_id": meta_campaign_id,
            "meta_adset_id": meta_adset_id,
            "meta_ad_id": ad_id_for_draft,
            "targeting": targeting,
            "targeting_spec": json.dumps({
                "target_country": client_profile.get("target_country", ""),
                "validated_interests": _final_interests,
                "suggested_keywords": [i["name"] for i in _final_interests],
                "funnel_mode": False,
                "ab_test": True,
                "ab_draft_ids": draft_ids,
            }),
            "published_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", d["id"]).execute()

    logger.info("A/B test: %d drafts → campaign %s, adset %s, %d ads",
                len(drafts), meta_campaign_id, meta_adset_id, len(meta_ad_ids))

    # SAC reconciliation — A/B drafts share one ad set, so reconcile once
    # using the anchor draft. Each draft in the batch will see the same
    # actual_targeting + targeting_diff written to its row. Pass MCP's
    # final_targeting to keep diff accuracy (no false-positive blocklist).
    _sac_for_anchor = _sac_list_for_draft(anchor)
    if _sac_for_anchor and meta_adset_id:
        for _d in drafts:
            schedule_reconciliation(
                draft_id=_d["id"],
                ad_set_id=meta_adset_id,
                access_token=access_token,
                sac_categories=_sac_for_anchor,
                mcp_final_targeting=mcp_data.get("final_targeting"),
            )

    # ── 14. Audit log ────────────────────────────────────────────────────────
    supabase.table("campaign_logs").insert({
        "user_id": anchor["user_id"],
        "ad_account_id": account["id"],
        "action": "ab_test_created",
        "meta_campaign_id": meta_campaign_id,
        "meta_adset_id": meta_adset_id,
        "meta_ad_id": meta_ad_id,
        "payload": {
            "draft_ids": draft_ids,
            "draft_count": len(drafts),
            "daily_budget": daily_budget,
            "targeting": targeting,
        },
        "result": mcp_data,
        "status": "success",
        "ai_reasoning": (
            f"A/B test with {len(drafts)} creative variants. "
            f"Budget: ${daily_budget}/day. "
            f"Targeting: {len(_final_interests)} interest(s)"
        ),
    }).execute()

    return {
        "success": True,
        "ab_test": True,
        "draft_count": len(drafts),
        "campaign_id": meta_campaign_id,
        "adset_id": meta_adset_id,
        "ad_ids": meta_ad_ids,
    }


def _fail_drafts(supabase, drafts: list[dict], error_msg: str):
    """Mark all drafts in a batch as failed."""
    for d in drafts:
        supabase.table("content_drafts").update({
            "status": "failed",
            "error_message": error_msg,
        }).eq("id", d["id"]).execute()


async def execute_approved_ad(draft_id: str) -> dict:
    """
    Full autonomous execution pipeline for an approved paid ad draft.

    FUNNEL ARCHITECTURE (Senior Media Buyer Strategy):
    - Campaign 1: PROSPECTING (80% budget) — find new strangers
      • If 100+ pixel events → 1% LAL from seed data
      • If < 100 events (cold start) → broad AI interests
    - Campaign 2: RETARGETING (20% budget) — close the sale
      • Target: Website visitors (pixel PageView 14d) OR page engagers
      • Exclude: Already-converted users (pixel conversion event)

    Non-pixel destinations (WhatsApp, IG DM, etc.) skip the funnel and
    launch a single campaign as before.

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

    # ── 2. Load credentials (workspace-first, fallback to ad_accounts) ─────
    ws_creds = resolve_workspace_credentials(draft, supabase)
    if ws_creds:
        access_token = ws_creds["access_token"]
        meta_account_id = ws_creds["meta_account_id"]
        facebook_page_id = ws_creds["facebook_page_id"]
        instagram_actor_id = ws_creds["instagram_actor_id"]
        pixel_id = None  # Resolved from product below (pixel-per-product architecture)
        # Synthetic account dict for audit logging compatibility
        account = {"id": draft.get("ad_account_id") or draft.get("workspace_id") or "workspace"}
    else:
        # Legacy fallback: load from ad_accounts by user_id
        account_query = supabase.table("ad_accounts").select("*").eq("is_active", True)
        if draft.get("ad_account_id"):
            account_query = account_query.eq("id", draft["ad_account_id"])
        else:
            account_query = account_query.eq("user_id", draft["user_id"])
            if draft.get("workspace_id"):
                account_query = account_query.eq("workspace_id", draft["workspace_id"])
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
        pixel_id = None
        facebook_page_id = account.get("facebook_page_id")
        instagram_actor_id = account.get("instagram_actor_id")

    # ── 3. Load user preferences (overlay workspace business context) ────────
    # Scope preferences to the draft's workspace so cross-workspace data
    # (website_url, business_name, etc.) doesn't bleed into the ad.
    _prefs_q = supabase.table("user_preferences").select("*").eq("user_id", draft["user_id"])
    if draft.get("workspace_id"):
        _prefs_q = _prefs_q.eq("workspace_id", draft["workspace_id"])
    prefs_result = _prefs_q.execute()
    preferences = prefs_result.data[0] if prefs_result.data else {}

    # Workspace fields override user_preferences for per-business context
    if ws_creds:
        for field in ("business_name", "target_country"):
            if ws_creds.get(field):
                preferences[field] = ws_creds[field]

    # ── 4. Mark as publishing ────────────────────────────────────────────────
    supabase.table("content_drafts").update({
        "status": "publishing",
    }).eq("id", draft_id).execute()

    # ── 5. Build client profile ─────────────────────────────────────────────
    client_profile = await _build_client_profile(draft, preferences, supabase)
    target_country = client_profile.get("target_country", "PK")
    business_name = preferences.get("business_name", "AI Campaign")

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
    if niche_customer_count >= PIXEL_EVENT_THRESHOLD:
        # DATA-RICH path: enough data to build a meaningful Custom Audience
        audience_route = "data_rich"
        logger.info(
            "ROUTING [data-rich] draft %s: %d customers for niche '%s' — will use LAL",
            draft_id, niche_customer_count, ad_niche,
        )
        try:
            audience_result = await sync_audience_for_niche(
                draft["user_id"], ad_niche, product_id,
                workspace_id=draft.get("workspace_id"),
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
    _raw_spec = draft.get("targeting_spec")
    if isinstance(_raw_spec, str):
        try:
            _raw_spec = json.loads(_raw_spec)
        except Exception:
            _raw_spec = None

    _saved_interests = []
    _saved_behaviors = []
    _advantage_plus = False
    if isinstance(_raw_spec, dict):
        _saved_interests = [
            i for i in (_raw_spec.get("validated_interests") or [])
            if not str(i.get("id", "")).startswith("ai_")
        ]
        # Behavior segments (e.g. "Small business owners") — distinct Meta
        # targeting class from interests. Stored as validated_behaviors so the
        # drafts UI / strategy can persist owner-targeting hints alongside
        # interest hints. Both land in the same flexible_spec entry (OR logic),
        # kept broad so Advantage+ can expand.
        _saved_behaviors = [
            b for b in (_raw_spec.get("validated_behaviors") or [])
            if not str(b.get("id", "")).startswith("ai_")
        ]
        _advantage_plus = bool(_raw_spec.get("advantage_plus_expanded"))

    if _saved_interests or _saved_behaviors:
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
        saved_interests = _saved_interests
        saved_behaviors = _saved_behaviors
    else:
        logger.info("Draft %s: no saved interests, regenerating via MCP", draft_id)
        strategy = await generate_campaign_strategy(client_profile, access_token)
        targeting = {
            "age_min": strategy.get("age_min", 18),
            "age_max": strategy.get("age_max", 65),
            "geo_locations": strategy["geo_locations"],
        }
        saved_interests = strategy.get("interests", [])
        saved_behaviors = []

    # ── HEC COMPLIANCE: strip age/gender for employment ads ──────────────────
    if draft.get("is_employment_ad"):
        targeting.pop("age_min", None)
        targeting.pop("age_max", None)
        targeting.pop("genders", None)
        logger.info("Draft %s: employment ad — stripped age/gender from targeting (HEC)", draft_id)

    # ── PROSPECTING TARGETING: cold vs data-rich ─────────────────────────────
    prospecting_targeting = dict(targeting)  # copy base geo/age
    if audience_route == "data_rich" and niche_audience_ids:
        # SAFETY LOCK: only use audiences that belong to this product
        niche_audience_ids = _validate_audience_ownership(
            supabase, product_id, niche_audience_ids, "prospecting")
        prospecting_targeting["custom_audiences"] = niche_audience_ids
        logger.info("Draft %s: PROSPECTING DATA-RICH — LAL %s", draft_id, niche_audience_ids)
    else:
        if saved_interests or saved_behaviors:
            _spec_entry: dict = {}
            if saved_interests:
                _spec_entry["interests"] = [{"id": i["id"], "name": i["name"]} for i in saved_interests]
            if saved_behaviors:
                _spec_entry["behaviors"] = [{"id": b["id"], "name": b["name"]} for b in saved_behaviors]
            prospecting_targeting["flexible_spec"] = [_spec_entry]
        logger.info(
            "Draft %s: PROSPECTING COLD — %d interest(s), %d behavior(s)",
            draft_id, len(saved_interests), len(saved_behaviors),
        )

    if strategy.get("persona_reasoning"):
        logger.info("Persona for draft %s: %s", draft_id, strategy["persona_reasoning"])

    # ── 8. Determine budget ──────────────────────────────────────────────────
    daily_budget = draft.get("proposed_budget")
    if not daily_budget:
        budget_level = preferences.get("ad_budget_level", "conservative")
        if budget_level == "custom" and preferences.get("custom_budget"):
            daily_budget = float(preferences["custom_budget"])
        else:
            daily_budget = BUDGET_MAP.get(budget_level, 10.0)

    # ── 9. Resolve product context (landing URL + image) ─────────────────────
    NO_CREATIVE_ERROR = "No image or video attached. Please add a creative to your draft before publishing."

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
            if product.get("pixel_id"):
                pixel_id = product["pixel_id"]

    if draft.get("pixel_id"):
        pixel_id = draft["pixel_id"]
    if draft.get("destination_url"):
        link_url = draft["destination_url"]

    # ── Build media_items array for flexible creative testing ──────────────
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

    def _detect_type(url: str) -> str:
        ext = ("." + url.rsplit(".", 1)[-1].lower()) if url and "." in url else ""
        return "video" if ext in VIDEO_EXTENSIONS else "image"

    def _resolve_thumbnail(draft_thumb: str = None, product_id: str = None) -> str:
        if draft_thumb:
            return draft_thumb
        if product_id:
            thumb_result = (
                supabase.table("products")
                .select("image_url")
                .eq("id", product_id)
                .execute()
            )
            if thumb_result.data and thumb_result.data[0].get("image_url"):
                prod_img = thumb_result.data[0]["image_url"]
                if _detect_type(prod_img) != "video":
                    return prod_img
        return ""

    raw_media_items = draft.get("media_items")
    media_items = []
    if raw_media_items and isinstance(raw_media_items, list) and len(raw_media_items) > 0:
        for item in raw_media_items[:10]:
            url = item.get("url", "")
            if not url:
                continue
            mtype = item.get("type") or _detect_type(url)
            entry = {"type": mtype, "url": url}
            if mtype == "video":
                entry["thumbnail_url"] = item.get("thumbnail_url") or _resolve_thumbnail(
                    draft.get("thumbnail_url"), draft.get("product_id")
                )
            media_items.append(entry)

    if not media_items and image_url:
        mtype = _detect_type(image_url)
        entry = {"type": mtype, "url": image_url}
        if mtype == "video":
            entry["thumbnail_url"] = _resolve_thumbnail(
                draft.get("thumbnail_url"), draft.get("product_id")
            )
        media_items.append(entry)

    if not media_items:
        logger.error("Draft %s: no media found — blocking execution", draft_id)
        supabase.table("content_drafts").update({
            "status": "failed",
            "error_message": NO_CREATIVE_ERROR,
        }).eq("id", draft_id).execute()
        return {"success": False, "error": NO_CREATIVE_ERROR}

    logger.info("Draft %s: %d media item(s) — %s", draft_id, len(media_items),
                ", ".join(f"{m['type']}" for m in media_items))

    # ── 10. Destination routing ──────────────────────────────────────────────
    draft_destination = draft.get("destination_type") or "WEBSITE"
    has_website = bool(link_url and link_url != "https://example.com")
    whatsapp_number = None

    if draft_destination == "WHATSAPP":
        whatsapp_number = draft.get("whatsapp_number") or preferences.get("whatsapp_number")
        pixel_id = None
    elif draft_destination == "INSTAGRAM_DM":
        pixel_id = None
    elif draft_destination == "INSTANT_FORM":
        pixel_id = None
    elif draft_destination == "MESSAGING":
        pixel_id = None
        selected_apps = draft.get("selected_messaging_apps") or []
        if "WHATSAPP" in selected_apps:
            whatsapp_number = draft.get("whatsapp_number") or preferences.get("whatsapp_number")
    elif draft_destination == "PHONE_CALL":
        pixel_id = None
    elif not pixel_id and not has_website:
        whatsapp_number = preferences.get("whatsapp_number")

    # CTA logic
    if draft_destination == "WHATSAPP":
        default_cta = "WHATSAPP_MESSAGE"
    elif draft_destination == "INSTAGRAM_DM":
        default_cta = "MESSAGE_PAGE"
    elif draft_destination == "INSTANT_FORM":
        default_cta = "SUBSCRIBE"
    elif draft_destination == "MESSAGING":
        default_cta = "MESSAGE_PAGE"
    elif draft_destination == "PHONE_CALL":
        default_cta = "CALL_NOW"
    else:
        default_cta = "SHOP_NOW" if (pixel_id or has_website) else "WHATSAPP_MESSAGE"
    cta = draft.get("cta_type") or default_cta

    _VALID_MESSAGING_CTAS = {"MESSAGE_PAGE", "WHATSAPP_MESSAGE", "GET_IN_TOUCH",
                              "CHAT_WITH_US", "CHAT_NOW", "ASK_A_QUESTION", "START_A_CHAT",
                              "INSTAGRAM_MESSAGE", "CHAT_ON_WHATSAPP", "SEND_UPDATES"}
    if draft_destination in ("MESSAGING", "WHATSAPP", "INSTAGRAM_DM"):
        if cta not in _VALID_MESSAGING_CTAS:
            cta = default_cta

    # Objective
    _LEADS_EVENTS = {"LEAD", "COMPLETE_REGISTRATION", "CONTACT", "SCHEDULE"}
    draft_event = (draft.get("conversion_event") or "PURCHASE").upper()
    draft_objective_override = draft.get("campaign_objective")

    if draft_objective_override and draft_objective_override.startswith("OUTCOME_"):
        objective = draft_objective_override
    elif draft_destination == "INSTAGRAM_DM":
        objective = "OUTCOME_ENGAGEMENT"
    elif draft_destination == "INSTANT_FORM":
        objective = "OUTCOME_LEADS"
    elif draft_destination == "WHATSAPP":
        objective = "OUTCOME_ENGAGEMENT"
    elif draft_destination == "MESSAGING":
        objective = "OUTCOME_ENGAGEMENT"
    elif draft_destination == "PHONE_CALL":
        objective = "OUTCOME_LEADS"
    elif pixel_id:
        objective = "OUTCOME_LEADS" if draft_event in _LEADS_EVENTS else "OUTCOME_SALES"
    else:
        objective = "OUTCOME_TRAFFIC"

    # Profit-Protection: bid amount
    raw_targeting = draft.get("targeting")
    draft_targeting = raw_targeting or {}
    if isinstance(draft_targeting, str):
        try:
            draft_targeting = json.loads(draft_targeting)
        except (json.JSONDecodeError, TypeError):
            draft_targeting = {}
    if not isinstance(draft_targeting, dict):
        draft_targeting = {}

    profit_margin = draft_targeting.get("profit_margin")
    if not profit_margin and draft.get("product_id"):
        pm_result = supabase.table("products").select("profit_margin").eq("id", draft["product_id"]).execute()
        if pm_result.data and pm_result.data[0].get("profit_margin"):
            profit_margin = pm_result.data[0]["profit_margin"]

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

    # ── 11. Build shared stage_params ────────────────────────────────────────
    async def _build_base_stage_params(campaign_name: str, budget: float, targeting_dict: dict) -> dict:
        """Build the MCP stage_params common to both campaigns."""
        params = {
            "campaign_name": campaign_name,
            "daily_budget": budget,
            "headline": draft.get("headline") or "",
            "body_text": draft["body_text"],
            "link_url": link_url,
            "cta_type": cta,
            "targeting_json": json.dumps(targeting_dict),
            "media_items_json": json.dumps(media_items),
        }
        # Carousel: only meaningful with 2+ cards. Below that, fall back to a
        # normal single ad regardless of the flag.
        if draft.get("is_carousel") and len(media_items) >= 2:
            params["carousel"] = True
        first_media = media_items[0]
        if first_media["type"] == "video":
            params["video_url"] = first_media["url"]
            params["image_url"] = first_media.get("thumbnail_url", "")
        else:
            params["image_url"] = first_media["url"]

        if strategy.get("objective_hint"):
            params["objective_hint"] = strategy["objective_hint"]
        # Forward the final objective decision (from line ~1672-1689 above) to MCP
        # so the override flows through. Without this, MCP falls back to its own
        # destination-based default and the user's UI selection (e.g. LEADS for a
        # WhatsApp campaign) is silently overridden.
        if objective and objective.startswith("OUTCOME_"):
            params["objective_override"] = objective
        if bid_amount > 0:
            params["bid_amount"] = bid_amount
            params["bid_strategy"] = "COST_CAP"
        else:
            params["bid_strategy"] = "LOWEST_COST_WITHOUT_CAP"
        if pixel_id:
            params["pixel_id"] = pixel_id
            params["tracking_specs"] = json.dumps([{
                "action.type": ["offsite_conversion"],
                "fb_pixel": [pixel_id],
            }])
            conversion_event = draft.get("conversion_event") or "PURCHASE"
            params["conversion_event"] = conversion_event
        if whatsapp_number:
            params["whatsapp_number"] = whatsapp_number

        draft_placements = (draft.get("targeting") or {}).get("placements")
        ad_placements = draft_placements or preferences.get("ad_placements", "BOTH")
        params["placements"] = ad_placements
        if facebook_page_id:
            params["page_id"] = facebook_page_id
        if instagram_actor_id:
            params["instagram_actor_id"] = instagram_actor_id
        params["destination_type_hint"] = draft.get("destination_type") or ""
        params["lead_form_id"] = draft.get("lead_form_id") or ""
        selected_apps = draft.get("selected_messaging_apps") or []
        if selected_apps:
            params["selected_messaging_apps"] = json.dumps(selected_apps)
        params["call_phone_number"] = draft.get("call_phone_number") or ""

        # ── Special Ad Category — cached on draft from generation time ────
        # Detection happens in content_generator at draft creation. We just
        # consume the persisted value here; if absent (legacy drafts), fall
        # back to a fresh detection at publish time.
        cached_sac_category = draft.get("special_ad_category")
        if cached_sac_category:
            params["special_ad_categories"] = json.dumps([cached_sac_category])
            params["enable_advantage_audience"] = True
            logger.info("Draft %s: SAC=%s (cached from generation)", draft_id, cached_sac_category)
        elif draft.get("is_employment_ad"):
            params["special_ad_categories"] = json.dumps(["EMPLOYMENT"])
            params["enable_advantage_audience"] = True
        else:
            # Legacy fallback: detect at publish time and persist for future use.
            if not hasattr(_build_base_stage_params, "_sac_cache"):
                _build_base_stage_params._sac_cache = None  # type: ignore[attr-defined]
            sac_decision = _build_base_stage_params._sac_cache  # type: ignore[attr-defined]
            if sac_decision is None:
                try:
                    _product_for_sac = {}
                    if draft.get("product_id"):
                        _p = supabase.table("products").select(
                            "name, description, product_type, tags, target_country"
                        ).eq("id", draft["product_id"]).limit(1).execute()
                        if _p.data:
                            _product_for_sac = _p.data[0]
                    sac_decision = await detect_for_draft(
                        draft=draft,
                        workspace=client_profile,
                        product=_product_for_sac,
                        preferences=preferences,
                    )
                    _build_base_stage_params._sac_cache = sac_decision  # type: ignore[attr-defined]
                except Exception as _sac_err:
                    logger.warning("SAC detection failed for draft %s: %s", draft_id, _sac_err)
                    sac_decision = None

            if sac_decision and sac_decision.should_auto_apply and sac_decision.category:
                params["special_ad_categories"] = json.dumps([sac_decision.category])
                params["enable_advantage_audience"] = True
                logger.info(
                    "Draft %s: SAC=%s (confidence=%.2f, legacy fresh detection)",
                    draft_id, sac_decision.category, sac_decision.confidence,
                )
                try:
                    supabase.table("content_drafts").update({
                        "special_ad_category": sac_decision.category,
                        "special_ad_category_confidence": round(sac_decision.confidence, 2),
                        "special_ad_category_reasoning": sac_decision.reasoning[:500],
                    }).eq("id", draft_id).execute()
                except Exception:
                    pass

        # Advantage+ Audience expansion — sparse interest pool or employment ads
        if _advantage_plus or draft.get("is_employment_ad"):
            params["enable_advantage_audience"] = True
            logger.info("Draft %s: Advantage+ Audience expansion ON", draft_id)

        # EU DSA payor/beneficiary — auto-set when targeting reaches EU/EEA/UK.
        # Without these, Meta rejects the AdCreative with subcode 3858081
        # ("Enter the person or organisation being promoted by an ad").
        _attach_dsa_if_eu(
            params, targeting_dict,
            client_profile=client_profile, preferences=preferences,
            log_prefix=f"Draft {draft_id}: ",
        )

        return params

    # ── 12. FUNNEL DECISION — single campaign or 2-campaign ecosystem ────────
    # Only split into funnel when we have a pixel (website destination) AND
    # enough budget to make both campaigns viable (min $5/day per campaign)
    can_funnel = (
        pixel_id is not None
        and draft_destination not in _NO_FUNNEL_DESTINATIONS
        and daily_budget >= 5.0  # minimum viable for 2 campaigns
    )

    # Also check pixel health: do we have retargetable traffic?
    conversion_event = draft.get("conversion_event") or "PURCHASE"
    pixel_event_count = 0
    if can_funnel:
        pixel_event_count = await _check_pixel_event_count(
            pixel_id, access_token, event_name=conversion_event,
        )
        # Even if pixel events < 100 for LAL, we can still retarget PageView visitors
        # But if pixel has ZERO events, retargeting won't work — skip funnel
        all_events_count = await _check_pixel_event_count(pixel_id, access_token, "PageView")
        if all_events_count == 0 and pixel_event_count == 0:
            logger.info("Draft %s: pixel %s has 0 events — skipping funnel, single campaign", draft_id, pixel_id)
            can_funnel = False

    if can_funnel:
        logger.info(
            "🎯 FUNNEL MODE: draft %s — pixel %s has %d conversion events, %s PageView events",
            draft_id, pixel_id, pixel_event_count, all_events_count,
        )

    # ────────────────────────────────────────────────────────────────────────
    # PATH A: 2-CAMPAIGN FUNNEL (pixel + enough data)
    # ────────────────────────────────────────────────────────────────────────
    if can_funnel:
        prospecting_budget = round(daily_budget * PROSPECTING_BUDGET_RATIO, 2)
        retargeting_budget = round(daily_budget * RETARGETING_BUDGET_RATIO, 2)
        # Ensure min $2/day for retargeting
        if retargeting_budget < 2.0:
            retargeting_budget = 2.0
            prospecting_budget = round(daily_budget - retargeting_budget, 2)

        logger.info(
            "Budget split: $%.2f total → $%.2f prospecting (%.0f%%) + $%.2f retargeting (%.0f%%)",
            daily_budget, prospecting_budget, (prospecting_budget/daily_budget)*100,
            retargeting_budget, (retargeting_budget/daily_budget)*100,
        )

        # ── CAMPAIGN 1: PROSPECTING (cold traffic) ───────────────────────────
        # Smart audience: if pixel conversion events >= 100, build LAL from pixel
        # Otherwise, fall back to the interest/LAL targeting already built above
        if pixel_event_count >= PIXEL_EVENT_THRESHOLD and audience_route != "data_rich":
            # Pixel has enough conversion data — build a LAL from pixel events
            logger.info(
                "Draft %s: %d pixel events ≥ %d threshold — building pixel-based LAL",
                draft_id, pixel_event_count, PIXEL_EVENT_THRESHOLD,
            )
            try:
                # Create Custom Audience from pixel conversion events
                ca_result = await mcp_client.create_website_custom_audience(
                    meta_account_id, pixel_id,
                    f"{business_name} - {conversion_event} Seed",
                    access_token,
                    retention_days=30,
                    event_name=conversion_event,
                )
                ca_data = _parse_mcp_response(ca_result)
                seed_audience_id = ca_data.get("audience_id")

                if seed_audience_id:
                    _register_audience(supabase, draft["user_id"], draft.get("workspace_id"),
                                       product_id, seed_audience_id,
                                       f"{business_name} - {conversion_event} Seed",
                                       "SEED", pixel_id=pixel_id)
                    # Build 1% LAL from the seed
                    lal_result = await mcp_client.create_lookalike_audience(
                        meta_account_id, seed_audience_id,
                        target_country, 0.01, access_token,
                    )
                    lal_data = _parse_mcp_response(lal_result)
                    lal_id = lal_data.get("audience_id")
                    if lal_id:
                        _register_audience(supabase, draft["user_id"], draft.get("workspace_id"),
                                           product_id, lal_id,
                                           f"{business_name} - {conversion_event} 1% LAL",
                                           "LAL", origin_audience_id=seed_audience_id,
                                           pixel_id=pixel_id)
                        prospecting_targeting = dict(targeting)
                        prospecting_targeting["custom_audiences"] = [{"id": lal_id}]
                        # Remove interest targeting — LAL is better
                        prospecting_targeting.pop("flexible_spec", None)
                        logger.info("Draft %s: pixel LAL %s created for prospecting", draft_id, lal_id)
            except Exception as e:
                logger.warning("Pixel LAL creation failed, using existing targeting: %s", e)

        campaign_name_base = draft.get("headline") or f"AI Campaign — {draft_id[:8]}"

        # Stage Campaign 1: Prospecting
        prospecting_params = await _build_base_stage_params(
            f"[PROSPECTING] {campaign_name_base}",
            prospecting_budget,
            prospecting_targeting,
        )

        # ── CAMPAIGN 2: RETARGETING (warm traffic) ───────────────────────────
        retarget_data = await _build_retargeting_audiences(
            meta_account_id, access_token, pixel_id,
            facebook_page_id, instagram_actor_id,
            conversion_event, business_name,
            user_id=draft["user_id"],
            workspace_id=draft.get("workspace_id"),
            product_id=product_id,
        )

        retargeting_targeting = dict(targeting)  # base geo/age
        # Remove broad interests — retargeting uses custom audiences
        retargeting_targeting.pop("flexible_spec", None)

        # SAFETY LOCK: validate audience ownership before attaching
        safe_retarget = _validate_audience_ownership(
            supabase, product_id, retarget_data["retarget_audience_ids"], "retargeting")
        safe_exclusion = _validate_audience_ownership(
            supabase, product_id, retarget_data["exclusion_audience_ids"], "exclusion")
        if safe_retarget:
            retargeting_targeting["custom_audiences"] = safe_retarget
        if safe_exclusion:
            retargeting_targeting["excluded_custom_audiences"] = safe_exclusion

        retargeting_params = await _build_base_stage_params(
            f"[RETARGETING] {campaign_name_base}",
            retargeting_budget,
            retargeting_targeting,
        )

        # ── Stage both campaigns via MCP ─────────────────────────────────────
        prospecting_result = None
        retargeting_result = None
        prospecting_mcp = {}
        retargeting_mcp = {}

        # WhatsApp WABA pre-publish validator — runs once on prospecting
        # since both ad sets in the funnel share the same Page identity.
        try:
            await _ensure_waba_assigned_for_publish(
                stage_params=prospecting_params,
                user_access_token=access_token,
                page_id=facebook_page_id,
                log_prefix=f"Draft {draft_id} (funnel): ",
            )
        except ValueError as e:
            logger.warning("Draft %s: WABA validation blocked publish: %s", draft_id, e)
            supabase.table("content_drafts").update({
                "status": "failed", "error_message": str(e),
            }).eq("id", draft_id).execute()
            return {"success": False, "error": str(e)}

        try:
            prospecting_result = await mcp_client.stage_campaign(
                meta_account_id, prospecting_params, access_token,
            )
            prospecting_mcp = _parse_mcp_response(prospecting_result)
        except MCPError as e:
            logger.error("Prospecting campaign failed for draft %s: %s", draft_id, e)
            prospecting_mcp = {"error": str(e)}

        # Only launch retargeting if we have audiences AND prospecting succeeded
        if retarget_data["retarget_audience_ids"] and prospecting_mcp.get("campaign_id"):
            try:
                retargeting_result = await mcp_client.stage_campaign(
                    meta_account_id, retargeting_params, access_token,
                )
                retargeting_mcp = _parse_mcp_response(retargeting_result)
            except MCPError as e:
                logger.warning("Retargeting campaign failed (non-fatal): %s", e)
                retargeting_mcp = {"error": str(e)}
        elif not retarget_data["retarget_audience_ids"]:
            logger.info("Draft %s: no retarget audiences available — prospecting only", draft_id)

        # ── Parse results ────────────────────────────────────────────────────
        meta_campaign_id = prospecting_mcp.get("campaign_id")
        meta_adset_id = prospecting_mcp.get("adset_id")
        meta_ad_id = prospecting_mcp.get("ad_id")

        rt_campaign_id = retargeting_mcp.get("campaign_id")
        rt_adset_id = retargeting_mcp.get("adset_id")

        # Check if at least prospecting succeeded
        creative_err = prospecting_mcp.get("creative_error")
        if prospecting_mcp.get("error") or not meta_campaign_id or (not meta_ad_id and creative_err):
            error_msg = prospecting_mcp.get("error") or creative_err or "MCP returned no campaign_id"
            logger.error("Funnel staging failed for draft %s: %s", draft_id, error_msg)
            supabase.table("content_drafts").update({
                "status": "failed",
                "error_message": error_msg,
            }).eq("id", draft_id).execute()
            supabase.table("campaign_logs").insert({
                "user_id": draft["user_id"],
                "ad_account_id": account["id"],
                "action": "error",
                "payload": {"draft_id": draft_id, "funnel": True},
                "result": prospecting_mcp,
                "status": "failed",
                "error_message": error_msg,
                "ai_reasoning": f"Funnel prospecting campaign failed at step: {prospecting_mcp.get('step', 'unknown')}",
            }).execute()
            return {"success": False, "error": error_msg}

        # ── Update draft → active ────────────────────────────────────────────
        _final_interests = []
        if prospecting_targeting.get("flexible_spec"):
            _final_interests = prospecting_targeting["flexible_spec"][0].get("interests", [])
        _final_spec_obj = {
            "target_country": client_profile.get("target_country", ""),
            "validated_interests": _final_interests,
            "suggested_keywords": [i["name"] for i in _final_interests],
            "funnel_mode": True,
            "prospecting_campaign_id": meta_campaign_id,
            "retargeting_campaign_id": rt_campaign_id,
            "audience_route": audience_route,
            "retarget_source": retarget_data["source"],
        }
        if _advantage_plus or draft.get("is_employment_ad"):
            _final_spec_obj["advantage_plus_expanded"] = True
        _final_spec = json.dumps(_final_spec_obj)
        supabase.table("content_drafts").update({
            "status": "active",
            "meta_campaign_id": meta_campaign_id,
            "meta_adset_id": meta_adset_id,
            "meta_ad_id": meta_ad_id,
            "targeting": prospecting_targeting,
            "targeting_spec": _final_spec,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", draft_id).execute()

        ad_count = prospecting_mcp.get("ad_count", 1) + retargeting_mcp.get("ad_count", 0)
        logger.info(
            "🎯 FUNNEL CREATED: draft %s — prospecting=%s ($%.2f/d), retargeting=%s ($%.2f/d), %d total ads",
            draft_id, meta_campaign_id, prospecting_budget,
            rt_campaign_id or "skipped", retargeting_budget if rt_campaign_id else 0, ad_count,
        )

        # Audit log
        supabase.table("campaign_logs").insert({
            "user_id": draft["user_id"],
            "ad_account_id": account["id"],
            "action": "funnel_created",
            "meta_campaign_id": meta_campaign_id,
            "meta_adset_id": meta_adset_id,
            "meta_ad_id": meta_ad_id,
            "payload": {
                "draft_id": draft_id,
                "funnel_mode": True,
                "total_budget": daily_budget,
                "prospecting_budget": prospecting_budget,
                "retargeting_budget": retargeting_budget,
                "prospecting_targeting": prospecting_targeting,
                "retargeting_targeting": retargeting_targeting,
                "retarget_source": retarget_data["source"],
                "pixel_event_count": pixel_event_count,
                "audience_route": audience_route,
                "rt_campaign_id": rt_campaign_id,
                "rt_adset_id": rt_adset_id,
            },
            "result": {
                "prospecting": prospecting_mcp,
                "retargeting": retargeting_mcp,
            },
            "status": "success",
            "ai_reasoning": (
                f"2-Campaign Funnel: [PROSPECTING] ${prospecting_budget}/d "
                f"({'LAL' if niche_audience_ids or pixel_event_count >= PIXEL_EVENT_THRESHOLD else 'interests'}) + "
                f"[RETARGETING] ${retargeting_budget}/d ({retarget_data['source']} audiences, "
                f"excludes {conversion_event})"
            ),
        }).execute()

        # SAC reconciliation — reconcile both ad sets in the funnel. Each
        # call is independent and runs in its own background task. Pass
        # the MCP-confirmed final_targeting so MCP-side strips don't get
        # falsely attributed to Meta in the blocklist.
        _sac_for_draft = _sac_list_for_draft(draft)
        if _sac_for_draft:
            schedule_reconciliation(
                draft_id=draft_id,
                ad_set_id=meta_adset_id,
                access_token=access_token,
                sac_categories=_sac_for_draft,
                mcp_final_targeting=prospecting_mcp.get("final_targeting"),
            )
            if rt_adset_id:
                schedule_reconciliation(
                    draft_id=draft_id,
                    ad_set_id=rt_adset_id,
                    access_token=access_token,
                    sac_categories=_sac_for_draft,
                    mcp_final_targeting=retargeting_mcp.get("final_targeting"),
                )

        return {
            "success": True,
            "funnel_mode": True,
            "campaign_id": meta_campaign_id,
            "adset_id": meta_adset_id,
            "ad_id": meta_ad_id,
            "retargeting_campaign_id": rt_campaign_id,
            "retargeting_adset_id": rt_adset_id,
            "prospecting_budget": prospecting_budget,
            "retargeting_budget": retargeting_budget,
        }

    # ────────────────────────────────────────────────────────────────────────
    # PATH B: SINGLE CAMPAIGN (no pixel, messaging destinations, low budget)
    # ────────────────────────────────────────────────────────────────────────
    campaign_name = draft.get("headline") or f"AI Campaign — {draft_id[:8]}"
    stage_params = await _build_base_stage_params(campaign_name, daily_budget, prospecting_targeting)

    # WhatsApp WABA pre-publish validator — block fast if the number isn't
    # actually assigned on Meta side, instead of failing at MCP/Meta later
    # with an opaque code.
    try:
        await _ensure_waba_assigned_for_publish(
            stage_params=stage_params,
            user_access_token=access_token,
            page_id=facebook_page_id,
            log_prefix=f"Draft {draft_id}: ",
        )
    except ValueError as e:
        logger.warning("Draft %s: WABA validation blocked publish: %s", draft_id, e)
        supabase.table("content_drafts").update({
            "status": "failed", "error_message": str(e),
        }).eq("id", draft_id).execute()
        return {"success": False, "error": str(e)}

    try:
        result = await mcp_client.stage_campaign(
            meta_account_id, stage_params, access_token,
        )
    except MCPError as e:
        logger.error(f"MCP execution failed for draft {draft_id}: {e}")
        enriched_err = _enrich_meta_error(str(e))
        supabase.table("content_drafts").update({
            "status": "failed",
            "error_message": enriched_err,
        }).eq("id", draft_id).execute()
        supabase.table("campaign_logs").insert({
            "user_id": draft["user_id"],
            "ad_account_id": account["id"],
            "action": "error",
            "payload": {"draft_id": draft_id, "targeting": prospecting_targeting},
            "status": "failed",
            "error_message": enriched_err,
            "ai_reasoning": f"Attempted to stage Advantage+ campaign from draft {draft_id}",
        }).execute()
        return {"success": False, "error": enriched_err}

    # ── Parse MCP response ────────────────────────────────────────────────
    mcp_data = _parse_mcp_response(result)

    meta_campaign_id = mcp_data.get("campaign_id")
    meta_adset_id = mcp_data.get("adset_id")
    meta_ad_id = mcp_data.get("ad_id")
    meta_ad_ids = mcp_data.get("ad_ids", [meta_ad_id] if meta_ad_id else [])
    ad_count = mcp_data.get("ad_count", len(meta_ad_ids))

    creative_err = mcp_data.get("creative_error")
    if mcp_data.get("error") or not meta_campaign_id or (not meta_ad_id and creative_err):
        error_msg = mcp_data.get("error") or creative_err or "MCP returned no campaign_id"
        error_msg = _enrich_meta_error(error_msg)
        logger.error(f"Campaign staging failed for draft {draft_id}: {error_msg}")
        supabase.table("content_drafts").update({
            "status": "failed",
            "error_message": error_msg,
        }).eq("id", draft_id).execute()
        supabase.table("campaign_logs").insert({
            "user_id": draft["user_id"],
            "ad_account_id": account["id"],
            "action": "error",
            "payload": {"draft_id": draft_id, "targeting": prospecting_targeting},
            "result": mcp_data,
            "status": "failed",
            "error_message": error_msg,
            "ai_reasoning": f"stage_advanced_campaign returned error at step: {mcp_data.get('step', 'unknown')}",
        }).execute()
        return {"success": False, "error": error_msg}

    # ── Update draft → active ────────────────────────────────────────────
    _final_interests = []
    if prospecting_targeting.get("flexible_spec"):
        _final_interests = prospecting_targeting["flexible_spec"][0].get("interests", [])
    _final_spec_b = {
        "target_country": client_profile.get("target_country", ""),
        "validated_interests": _final_interests,
        "suggested_keywords": [i["name"] for i in _final_interests],
        "funnel_mode": False,
    }
    if _advantage_plus or draft.get("is_employment_ad"):
        _final_spec_b["advantage_plus_expanded"] = True
    _final_spec = json.dumps(_final_spec_b)
    supabase.table("content_drafts").update({
        "status": "active",
        "meta_campaign_id": meta_campaign_id,
        "meta_adset_id": meta_adset_id,
        "meta_ad_id": meta_ad_id,
        "targeting": prospecting_targeting,
        "targeting_spec": _final_spec,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", draft_id).execute()

    logger.info("Draft %s: created %d ad(s) under campaign %s (single mode)", draft_id, ad_count, meta_campaign_id)

    # Audit log
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
            "targeting": prospecting_targeting,
            "funnel_mode": False,
        },
        "result": mcp_data,
        "status": "success",
        "ai_reasoning": (
            f"Single campaign (no funnel). "
            f"Targeting: {len(_final_interests)} interest(s), "
            f"age {prospecting_targeting.get('age_min')}-{prospecting_targeting.get('age_max')}"
        ),
    }).execute()

    # SAC reconciliation — fire-and-forget. Waits 30s for Meta's silent strip
    # to settle, then diffs sent vs live targeting and learns the rejected
    # interest IDs into sac_blocked_interests so future drafts skip them.
    # Pass the MCP-confirmed final_targeting so the diff doesn't blame Meta
    # for interests our MCP-side nuclear-strip removed before sending.
    schedule_reconciliation(
        draft_id=draft_id,
        ad_set_id=meta_adset_id,
        access_token=access_token,
        sac_categories=_sac_list_for_draft(draft),
        mcp_final_targeting=mcp_data.get("final_targeting"),
    )

    return {
        "success": True,
        "funnel_mode": False,
        "campaign_id": meta_campaign_id,
        "adset_id": meta_adset_id,
        "ad_id": meta_ad_id,
    }
