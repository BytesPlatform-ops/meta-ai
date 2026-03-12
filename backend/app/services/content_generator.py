"""
AI Content Generator — Uses OpenAI to generate ad drafts based on user preferences.

Generates both organic and paid content drafts, storing them in content_drafts
for user approval via the Drafts & Approvals dashboard.
"""
import json
import logging
import re

import httpx
from openai import AsyncOpenAI

from ..core.config import get_settings
from ..db.supabase_client import get_supabase
from .mcp_client import mcp_client, MCPError
from .targeting_engine import generate_campaign_strategy, _extract_keywords, _parse_mcp_json
from .angle_analyzer import analyze_market_gaps

logger = logging.getLogger(__name__)
settings = get_settings()

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# ── Bug Fix #4: Dynamic budget calculation ────────────────────────────────────
# Maps budget_level to a multiplier applied against the product's ticket size.
# Formula: daily_budget = max(floor, ticket_price × multiplier)
# This ensures high-ticket items get adequate budget to exit Meta's learning phase.
BUDGET_MULTIPLIERS = {
    "conservative": {"multiplier": 0.05, "floor": 5.0, "cap": 50.0},
    "moderate": {"multiplier": 0.10, "floor": 10.0, "cap": 150.0},
    "aggressive": {"multiplier": 0.20, "floor": 20.0, "cap": 500.0},
}
# Legacy key compat (old DB values like "conservative_$10")
_LEGACY_LEVEL_MAP = {
    "conservative_$10": "conservative",
    "moderate_$30": "moderate",
    "aggressive_$50": "aggressive",
}


def _calculate_daily_budget(budget_level: str, ticket_price: float | None = None) -> float:
    """
    Compute a smart daily budget based on the user's budget preference and
    the product's ticket price.  Replaces the old flat $10/$30/$50 map.
    """
    level = _LEGACY_LEVEL_MAP.get(budget_level, budget_level)
    params = BUDGET_MULTIPLIERS.get(level, BUDGET_MULTIPLIERS["moderate"])
    if ticket_price and ticket_price > 0:
        computed = ticket_price * params["multiplier"]
        return round(min(max(computed, params["floor"]), params["cap"]), 2)
    return params["floor"]


# ── Bug Fix #2: CTA resolution logic ─────────────────────────────────────────
# High-ticket / B2B / services → LEARN_MORE, CONTACT_US, GET_QUOTE
# Low-ticket / physical e-commerce → SHOP_NOW
_B2B_SERVICE_TYPES = {"saas", "service", "digital", "consulting", "agency"}
_HIGH_TICKET_THRESHOLD = 100.0  # USD — above this, never use SHOP_NOW

_CTA_FOR_HIGH_TICKET = ("LEARN_MORE", "CONTACT_US", "GET_QUOTE")
_CTA_FOR_ECOMMERCE = ("SHOP_NOW", "GET_OFFER", "LEARN_MORE")
_CTA_FOR_WHATSAPP = ("WHATSAPP_MESSAGE",)


def _resolve_cta(
    ai_suggested_cta: str,
    product_type: str | None = None,
    ticket_price: float | None = None,
    has_website: bool = True,
) -> str:
    """
    Override the AI's CTA suggestion when it conflicts with the product's
    category or price tier.  Returns a valid Meta CTA enum value.
    """
    suggested = (ai_suggested_cta or "LEARN_MORE").upper().strip()

    # WhatsApp flow — no website, no pixel
    if not has_website:
        return "WHATSAPP_MESSAGE"

    is_b2b = (product_type or "").lower() in _B2B_SERVICE_TYPES
    is_high_ticket = (ticket_price or 0) >= _HIGH_TICKET_THRESHOLD

    if is_b2b or is_high_ticket:
        # Block e-commerce CTAs for B2B / high-ticket
        if suggested in ("SHOP_NOW", "GET_OFFER", "BUY_NOW"):
            return "LEARN_MORE"
        if suggested in _CTA_FOR_HIGH_TICKET:
            return suggested
        return "LEARN_MORE"

    # Low-ticket / physical → allow SHOP_NOW
    if suggested in _CTA_FOR_ECOMMERCE or suggested in _CTA_FOR_HIGH_TICKET:
        return suggested
    return "SHOP_NOW"


# ── Bug Fix #1: Post-processing for formatting glitches ──────────────────────
_BANNED_BUZZWORDS = {
    "revolutionize", "revolutionizing", "revolutionized",
    "unleash", "unleashing", "unleashed",
    "transform", "transforming", "transformative",
    "game-changing", "game-changer", "gamechanging",
    "cutting-edge", "cutting edge",
    "synergy", "synergize",
    "disrupt", "disruptive", "disrupting",
    "supercharge", "supercharging", "supercharged",
    "skyrocket", "skyrocketing",
    "unlock", "unlocking",
    "empower", "empowering", "empowered",
    "leverage", "leveraging",
    "paradigm", "paradigm shift",
    "next-level", "next level",
    "elevate", "elevating",
}

# Regex: punctuation mark (. ! ?) followed directly by a letter (no space)
_MISSING_SPACE_RE = re.compile(r"([.!?])([A-Za-z])")


def _sanitize_ad_text(text: str) -> str:
    """Fix formatting glitches and strip banned AI buzzwords from ad copy."""
    if not text:
        return text

    # Fix missing space after punctuation
    text = _MISSING_SPACE_RE.sub(r"\1 \2", text)

    # Strip banned buzzwords (case-insensitive, whole-word)
    for word in _BANNED_BUZZWORDS:
        pattern = re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)
        text = pattern.sub("", text)

    # Clean up double spaces / leading spaces left by removals
    text = re.sub(r"  +", " ", text).strip()

    return text


# ── Bug Fix #3: Geo-targeting hallucination filter ────────────────────────────
_GEO_NAMES = {
    "united states", "united kingdom", "pakistan", "india", "canada",
    "australia", "germany", "france", "turkey", "malaysia", "nigeria",
    "kenya", "bangladesh", "saudi arabia", "uae", "dubai", "abu dhabi",
    "new york", "los angeles", "chicago", "houston", "london", "manchester",
    "karachi", "lahore", "islamabad", "mumbai", "delhi", "bangalore",
    "toronto", "vancouver", "sydney", "melbourne", "berlin", "paris",
    "istanbul", "riyadh", "jeddah", "dhaka", "lagos", "nairobi",
    "seoul", "tokyo", "beijing", "shanghai", "bangkok", "singapore",
    "hong kong", "taipei", "osaka", "san francisco", "seattle", "miami",
    "boston", "dallas", "phoenix", "denver", "atlanta", "philadelphia",
}


def _filter_geo_hallucinations(interests: list[str]) -> list[str]:
    """Remove any city/country names the AI hallucinated into interest keywords."""
    return [kw for kw in interests if kw.lower().strip() not in _GEO_NAMES]

def _format_variants(variants: list[dict]) -> str:
    """Format product variants for the LLM prompt."""
    lines = ", ".join(
        f"{v.get('variant_name', '?')} {v.get('price', '?')} {v.get('currency', '')}"
        for v in variants
    )
    return f"Pricing tiers: {lines}"


TONE_DESCRIPTIONS = {
    "professional": "Clean, authoritative, trust-building. Use data and credibility.",
    "humorous": "Witty, relatable, scroll-stopping. Use clever hooks and personality.",
    "educational": "Informative, value-driven. Teach something useful, then soft-sell.",
    "promotional": "Direct offers, urgency, strong CTAs. Drive immediate action.",
}


def _postgrest_headers() -> dict:
    return {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _postgrest_url(table: str) -> str:
    return f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1/{table}"


async def generate_drafts(
    user_id: str,
    count: int = 3,
    product_id: str | None = None,
    ab_test: bool = False,
    user_guidance: str | None = None,
    conversion_event: str | None = None,
) -> list[dict]:
    """
    Generate `count` content drafts for a user based on their preferences.
    Optionally focuses on a specific product and/or generates A/B variants.
    Returns list of created draft records.
    """
    supabase = get_supabase()

    # Load preferences
    prefs_result = (
        supabase.table("user_preferences")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )
    if not prefs_result.data:
        raise ValueError("User has not completed strategy setup")
    prefs = prefs_result.data[0]

    # Load ad account (for paid drafts)
    account_result = (
        supabase.table("ad_accounts")
        .select("id, meta_account_id, account_name, access_token, pixel_id")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    ad_account = account_result.data[0] if account_result.data else None

    # Load specific product or all products for context
    focused_product = None
    if product_id:
        prod_result = (
            supabase.table("products")
            .select("*")
            .eq("id", product_id)
            .eq("user_id", user_id)
            .execute()
        )
        if prod_result.data:
            focused_product = prod_result.data[0]

    products_result = (
        supabase.table("products")
        .select("name, description, landing_url, price, currency, target_audience")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(5)
        .execute()
    )
    products = products_result.data or []

    # ── FEEDBACK LOOP: Load historical performance + market research ──────
    # Step 1: Load latest completed audit from DB
    audit = None
    try:
        audit_result = (
            supabase.table("account_audits")
            .select("winning_ads, losing_ads, ai_strategy_report, audience_demographics, tone_recommendation")
            .eq("user_id", user_id)
            .eq("status", "completed")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        audit = audit_result.data[0] if audit_result.data else None
    except Exception as e:
        logger.warning(f"Failed to load audit data: {e}")

    # Step 2: Get live performance insights from Meta API via MCP
    performance_insights = None
    if ad_account and ad_account.get("access_token"):
        try:
            performance_insights = await mcp_client.call_tool(
                "get_performance_insights",
                {"ad_account_id": ad_account["meta_account_id"]},
                ad_account["access_token"],
            )
        except Exception as e:
            logger.warning(f"Failed to get performance insights: {e}")

    # Resolve target country: product-level override > user preferences > default
    target_country = "US"
    if focused_product and focused_product.get("target_country"):
        target_country = focused_product["target_country"]
    elif prefs.get("target_country"):
        target_country = prefs["target_country"]

    # Step 3: Research niche trends via MCP (web search)
    niche = prefs.get("industry_niche") or ""
    market_research = None
    if niche:
        try:
            market_research = await mcp_client.call_tool(
                "research_niche_trends",
                {"niche": niche, "country": target_country},
                "",  # no access_token needed
            )
        except Exception as e:
            logger.warning(f"Failed to get market research: {e}")

    # Step 5: Build performance + market context for prompt injection
    performance_context = ""
    if audit:
        try:
            winners = json.loads(audit["winning_ads"]) if isinstance(audit.get("winning_ads"), str) else (audit.get("winning_ads") or [])
            losers = json.loads(audit["losing_ads"]) if isinstance(audit.get("losing_ads"), str) else (audit.get("losing_ads") or [])
            performance_context = f"""

## HISTORICAL PERFORMANCE DATA (from account audit)
Top performing ads (ROAS >= 2.0x): {json.dumps(winners[:5])}
Underperforming ads (ROAS < 1.5x): {json.dumps(losers[:3])}
AI Strategy Notes: {(audit.get('ai_strategy_report') or '')[:500]}

CRITICAL: Model new ads after the WINNING patterns above. Avoid the patterns seen in losing ads."""
        except Exception as e:
            logger.warning(f"Failed to parse audit data: {e}")

    if performance_insights and not performance_insights.get("error"):
        performance_context += f"""

## CREATIVE PATTERN ANALYSIS (live from Meta API)
{json.dumps(performance_insights, indent=2)}
Use these exact patterns: replicate winning headline styles, body lengths, and CTA types."""

    market_context = ""
    if market_research and not market_research.get("error"):
        market_context = f"""

## CURRENT MARKET RESEARCH ({niche} industry)
{json.dumps(market_research, indent=2)}
Incorporate these current trends and angles into the ad copy."""

    tone = prefs["content_tone"]
    tone_desc = TONE_DESCRIPTIONS.get(tone, TONE_DESCRIPTIONS["professional"])
    budget_level = prefs["ad_budget_level"]

    # Bug Fix #4: Dynamic budget based on ticket size + budget preference
    ticket_price = None
    if focused_product:
        ticket_price = focused_product.get("price")
        if ticket_price is not None:
            ticket_price = float(ticket_price)
    elif products:
        # Average price across catalog as proxy
        prices = [float(p["price"]) for p in products if p.get("price")]
        ticket_price = sum(prices) / len(prices) if prices else None

    if budget_level == "custom" and prefs.get("custom_budget"):
        daily_budget = float(prefs["custom_budget"])
    else:
        daily_budget = _calculate_daily_budget(budget_level, ticket_price)

    # Business context
    biz_name = prefs.get("business_name") or "the business"
    biz_desc = prefs.get("business_description") or ""
    target_aud = prefs.get("target_audience") or ""
    website = prefs.get("website_url") or ""
    website_intel = prefs.get("website_intel") or {}

    # ── PRE-GENERATION: Competitor research via MCP (Ad Library) ──────────
    # Moved from ad_executor.py — competitor intelligence must inform the
    # initial draft, NOT mutate it post-approval.
    competitor_context = ""
    access_token_for_research = ad_account.get("access_token", "") if ad_account else ""
    if access_token_for_research:
        try:
            comp_source = ""
            if focused_product:
                comp_source = focused_product.get("description") or focused_product.get("name", "")
            elif biz_desc:
                comp_source = biz_desc
            elif niche:
                comp_source = niche

            if comp_source:
                comp_keywords = _extract_keywords(comp_source)[:5]
                logger.info("Competitor research: keywords=%s, country=%s", comp_keywords, target_country)

                competitor_result = await mcp_client.fetch_competitor_ads(
                    comp_keywords, target_country, access_token_for_research,
                )
                competitor_ads = _parse_mcp_json(competitor_result)

                if isinstance(competitor_ads, list) and competitor_ads:
                    gap_analysis = await analyze_market_gaps(competitor_ads)
                    diff_strategy = gap_analysis.get("differentiation_strategy", "")
                    rec_angles = gap_analysis.get("recommended_angles", [])
                    avoid = gap_analysis.get("avoid_patterns", [])

                    competitor_context = f"""

## COMPETITOR INTELLIGENCE ({len(competitor_ads)} ads analyzed)
Differentiation Strategy: {diff_strategy}
Recommended Angles: {', '.join(rec_angles) if rec_angles else 'N/A'}
Patterns to AVOID (saturated): {', '.join(avoid) if avoid else 'N/A'}

CRITICAL: Use the differentiation strategy above to write ads that stand out
from competitors. Do NOT copy the saturated patterns listed in "avoid"."""

                    logger.info(
                        "Competitor analysis complete: %d ads → strategy: %s",
                        len(competitor_ads), diff_strategy[:100] if diff_strategy else "none",
                    )
                else:
                    logger.info("No competitor ads found for keywords=%s", comp_keywords)
        except (MCPError, Exception) as e:
            logger.warning("Competitor research failed (non-fatal, drafts will generate without it): %s", e)

    # Load variants for focused product
    product_variants = []
    if focused_product:
        try:
            variants_result = (
                supabase.table("product_variants")
                .select("variant_name, price, currency")
                .eq("product_id", focused_product["id"])
                .eq("is_active", True)
                .order("sort_order")
                .execute()
            )
            product_variants = variants_result.data or []
        except Exception as e:
            logger.warning(f"Failed to load variants: {e}")

    # Product-specific context
    product_context = ""
    if focused_product:
        p = focused_product
        ptype = p.get("product_type", "physical")
        type_hints = {
            "saas": "This is a SaaS product. Emphasize subscription value, recurring benefits, and ROI.",
            "digital": "This is a digital product. Highlight instant delivery, digital access, and convenience.",
            "service": "This is a service. Focus on expertise, results, and easy booking.",
        }
        type_hint = type_hints.get(ptype, "")

        variant_lines = ""
        if product_variants:
            vlist = ", ".join(f"{v['variant_name']} ${v['price']} {v['currency']}" for v in product_variants)
            variant_lines = f"\n- Pricing tiers: {vlist}"

        image_hint = ""
        if p.get("image_url"):
            image_hint = """
- Product Image: PROVIDED — a product image will be attached to all ads.
  Write ad copy that COMPLEMENTS the visual: reference what the product looks like,
  its colors, packaging, or form factor. Use phrases like "as you can see",
  "look at this", or "pictured here" to tie copy to the creative image.
  Make the text and image feel like one cohesive ad, not separate pieces."""

        product_context = f"""

FOCUSED PRODUCT — ALL ads must be specifically about this product:
- Name: {p['name']}
- Type: {ptype}
- Description: {p.get('description') or 'N/A'}
- USPs/Target Audience: {p.get('target_audience') or target_aud or 'General'}
- Price: ${p.get('price') or 'N/A'} {p.get('currency', 'USD')}{variant_lines}
- Landing URL: {p.get('landing_url') or website or 'Not provided'}{image_hint}
{type_hint}

Every headline and body MUST reference this specific product.{' Mention available pricing tiers/plans where relevant.' if product_variants else ''}"""
    elif products:
        product_lines = [
            f"- {p['name']}: {p.get('description', 'N/A')} (${p.get('price', 'N/A')})"
            for p in products
        ]
        product_context = f"\n\nProduct catalog:\n" + "\n".join(product_lines)

    # Niche context
    niche_context = ""
    if niche:
        niche_context = f"""

Industry/Niche: {niche}
IMPORTANT: Incorporate current trends, language, and best practices specific to the {niche} industry. Reference niche-specific pain points and desires."""

    # A/B testing instructions
    ab_instructions = ""
    if ab_test:
        ab_instructions = """

A/B TESTING MODE: For each ad, provide TWO variants:
- "headline_a" and "headline_b": two different headline approaches
- "body_text_a" and "body_text_b": two different body copy approaches
The "headline" field should be headline_a and "body_text" should be body_text_a (primary).
Also include "ab_variants": {"headline_a": "...", "headline_b": "...", "body_text_a": "...", "body_text_b": "..."}"""

    # Pixel vs WhatsApp strategy rule
    pixel_strategy = ""
    has_pixel = (ad_account and ad_account.get("pixel_id")) or (focused_product and focused_product.get("pixel_id"))
    if has_pixel:
        pixel_strategy = """

CONVERSION STRATEGY: This client has a Meta Pixel installed on their website.
- Generate ad copy that drives traffic to the WEBSITE for purchases.
- Use CTAs like "SHOP_NOW" or "LEARN_MORE" pointing to the landing page.
- Focus on product benefits, pricing, and website credibility.
{f'- CONVERSION EVENT: Optimize for "{conversion_event}" — tailor CTA and copy to drive this specific action.' if conversion_event else ''}"""
    elif website:
        pixel_strategy = f"""

CONVERSION STRATEGY: This client has a website but no Meta Pixel.
- Generate ad copy that drives traffic to the WEBSITE: {website}
- Use CTAs like "SHOP_NOW" or "LEARN_MORE" pointing to the website.
- Focus on product benefits, pricing, and easy ordering via the site."""
    else:
        whatsapp_num = prefs.get("whatsapp_number", "")
        pixel_strategy = f"""

CONVERSION STRATEGY: This client does NOT have a website or Pixel. Use WhatsApp/COD strategy.
- Generate ad copy heavily focused on "Send us a WhatsApp message to order" or "Message us on WhatsApp".
- Use CTA type "WHATSAPP_MESSAGE" for all paid ads.
- Emphasize Cash on Delivery (COD), easy ordering via chat, and personal service.
- Include phrases like "Order via WhatsApp", "Pay on delivery", "DM to order now".
{f'- WhatsApp number: {whatsapp_num}' if whatsapp_num else ''}
- Do NOT reference any website or online checkout process."""

    # Geo-cultural context for prompt injection
    COUNTRY_NAMES = {
        "PK": "Pakistan", "US": "United States", "GB": "United Kingdom",
        "AE": "UAE", "SA": "Saudi Arabia", "IN": "India", "CA": "Canada",
        "AU": "Australia", "DE": "Germany", "FR": "France", "TR": "Turkey",
        "MY": "Malaysia", "NG": "Nigeria", "KE": "Kenya", "BD": "Bangladesh",
    }
    country_name = COUNTRY_NAMES.get(target_country, target_country)
    geo_cultural_context = f"""

TARGET MARKET: {country_name} ({target_country})
Write ad copy that resonates with {country_name} consumers. Use culturally appropriate
language, references, and value propositions. Do NOT use US-centric references
(like "Whole Foods", "Trader Joe's", American holidays) unless targeting the US."""

    if target_country in {"PK", "SA", "AE", "BD", "MY", "TR"}:
        geo_cultural_context += f"""
CULTURAL SENSITIVITY ({country_name}): This is a conservative/Islamic market.
- Do NOT reference alcohol, pork, gambling, or culturally inappropriate content.
- Emphasize family values, natural/pure/halal qualities, and trusted local commerce.
- Use WhatsApp/COD references if applicable — these markets prefer chat-based ordering."""

    # ── User creative guidance (optional) ──────────────────────────────
    guidance_block = ""
    if user_guidance and user_guidance.strip():
        guidance_block = f"""
## USER CREATIVE DIRECTION (HIGH PRIORITY)
The user has provided the following creative direction:
"{user_guidance.strip()}"

You MUST follow this angle, tone, or targeting request as the core creative direction.
Take their idea — whether vague or specific — and expand it into high-converting,
professional Meta Ad copy. All generated ads should reflect this guidance while still
following the structural and quality rules below.
"""

    # ── Shared prompt rules (Bug Fix #1: tone + formatting) ─────────────
    copy_quality_rules = """
COPY QUALITY RULES (MANDATORY — violation = instant reject):
1. FORMATTING: Always place a space after every period, exclamation mark, and question mark.
   WRONG: "Great taste!Order now"  CORRECT: "Great taste! Order now"
2. BANNED WORDS — Do NOT use any of these cliche AI marketing words:
   Revolutionize, Unleash, Transform, Game-changing, Cutting-edge, Synergy,
   Disrupt, Supercharge, Skyrocket, Unlock, Empower, Leverage, Paradigm,
   Next-level, Elevate. If you catch yourself writing any of these, rewrite
   the sentence using plain, conversational language.
3. TONE: Write like a smart friend recommending something — not a corporate press release.
   Use short sentences. Be specific. Avoid vague superlatives like "amazing" or "incredible".
4. HEADLINES: Must be punchy, curiosity-driven, or benefit-focused. No clickbait.

HASHTAG STRATEGY (2026 — SEO-DRIVEN, NO SPAM):
- Include EXACTLY 3-5 hashtags at the end of body_text, separated by spaces.
- Each hashtag must be a HIGH-INTENT, niche-specific SEO signal — NOT generic filler.
- Think: what would your ideal customer SEARCH for on Instagram/Reels?
- GOOD examples: #B2BSoftware #SaaSFounder #GrowthMarketing #OrganicSkincare #PakistaniHoney
- BAD examples (NEVER USE): #love #business #tech #instagood #viral #trending #explore #fyp
- Hashtags must match the product's ACTUAL niche and the target country's trends.
- Zero tolerance for generic/spam hashtags. Quality over quantity — every hashtag must earn its place.
"""

    # ── Shared geo-targeting enforcement (Bug Fix #3) ────────────────────
    geo_targeting_rules = f"""
GEO-TARGETING RULES (MANDATORY):
- The target market is {country_name} ({target_country}) ONLY.
- Do NOT include cities, states, or countries as interest keywords.
- Do NOT mix geographic locations from different countries.
- suggested_interests must contain ONLY topical interests (hobbies, behaviors, product categories).
- NEVER put geographic names like "Seoul", "New York", "United States" in suggested_interests.
"""

    # Build prompt — product-focused vs business-general
    if focused_product:
        # PRODUCT MODE: ads are 100% about the product, not the parent business
        p = focused_product
        product_name = p["name"]
        product_landing = p.get("landing_url") or website or "Not provided"
        product_audience = p.get("target_audience") or target_aud or "General audience"

        system_prompt = f"""You are an expert Meta Ads copywriter.

You are writing ads for a SPECIFIC PRODUCT — every ad must be entirely about this product:
- Product Name: {product_name}
- Description: {p.get('description') or 'N/A'}
- Price: {p.get('price') or 'N/A'} {p.get('currency', 'USD')}
- Target Audience: {product_audience}
- Landing URL: {product_landing}
- Brand/Seller: {biz_name}

{_format_variants(product_variants) if product_variants else ""}
{"Product Image: PROVIDED — write copy that complements the visual. Reference what the product looks like." if p.get("image_url") else ""}

Tone: {tone} — {tone_desc}
Daily budget: ${daily_budget}/day (calculated from product price and budget preference)
{geo_cultural_context}{pixel_strategy}{performance_context}{market_context}{competitor_context}{ab_instructions}

{guidance_block}{copy_quality_rules}
{geo_targeting_rules}

CRITICAL RULES:
- Every headline and body text MUST be about "{product_name}" — the product, its benefits, its price, its features.
- You may mention "{biz_name}" as the seller/brand, but the PRODUCT is the star, not the business services.
- Do NOT write about the seller's other services (web dev, SEO, app dev, etc.) — ONLY about this product.
- Reference the product's actual description and USPs above.
- For PAID ads, also suggest 3-5 broad, high-intent Meta Ad interest keywords (liquidity over micro-targeting) for {country_name}.

Generate {count} ad content pieces. Return a JSON array of {count} objects. Each object must have:
- "draft_type": "paid" (default ALL drafts to "paid" — user can toggle to "organic" later)
- "headline": short punchy headline (max 40 chars) about {product_name}
- "body_text": primary ad copy (2-4 sentences) about {product_name}
- "cta_type": one of "LEARN_MORE", "SHOP_NOW", "SIGN_UP", "CONTACT_US", "GET_OFFER", "GET_QUOTE", "CONTACT_US"
- "ai_reasoning": 1 sentence explaining why this ad will perform well
- "proposed_budget": daily budget in dollars (use {daily_budget})
- "suggested_interests": (PAID only) array of 3-5 BROAD, high-intent interest keywords (give Meta's algorithm liquidity) for {country_name} market — NO geographic names
{'"ab_variants": object with headline_a, headline_b, body_text_a, body_text_b' if ab_test else ''}

Return ONLY the JSON array, no markdown formatting."""
    else:
        # BUSINESS MODE: general business ads using all context
        system_prompt = f"""You are an expert Meta Ads copywriter for "{biz_name}".

Business: {biz_desc}
Target audience: {target_aud or "General audience"}
Website: {website or "Not provided"}
{f"""Website Intelligence (scraped from their site):
{json.dumps(website_intel, indent=2)}
Use this data to write ads that reference their ACTUAL products/services.""" if website_intel and not website_intel.get("error") else ""}
Tone: {tone} — {tone_desc}
Daily budget: ${daily_budget}/day (calculated from product price and budget preference)
{product_context}{niche_context}{geo_cultural_context}{pixel_strategy}{performance_context}{market_context}{competitor_context}{ab_instructions}

{guidance_block}{copy_quality_rules}
{geo_targeting_rules}

IMPORTANT: Every ad must be specifically about this business — reference their actual products, services, or value proposition. Do NOT write generic ads.
For PAID ads, also suggest 3-5 broad, high-intent Meta Ad interest keywords (liquidity over micro-targeting) for {country_name}.

Generate {count} ad content pieces. Return a JSON array of {count} objects. Each object must have:
- "draft_type": "paid" (default ALL drafts to "paid" — user can toggle to "organic" later)
- "headline": short punchy headline (max 40 chars)
- "body_text": primary ad copy (2-4 sentences, compelling)
- "cta_type": one of "LEARN_MORE", "SHOP_NOW", "SIGN_UP", "CONTACT_US", "GET_OFFER", "GET_QUOTE", "CONTACT_US"
- "ai_reasoning": 1 sentence explaining why this ad will perform well
- "proposed_budget": daily budget in dollars (use {daily_budget})
- "suggested_interests": (PAID only) array of 3-5 BROAD, high-intent interest keywords (give Meta's algorithm liquidity) for {country_name} market — NO geographic names
{'"ab_variants": object with headline_a, headline_b, body_text_a, body_text_b' if ab_test else ''}

The ads MUST mention "{biz_name}" by name and reference specific products/services from the business description. If a website URL is provided, use it as the landing page reference.

Return ONLY the JSON array, no markdown formatting."""

    try:
        response = await client.chat.completions.create(
            model=settings.CREATIVE_WRITING_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Generate {count} high-converting ad drafts now."},
            ],
            max_completion_tokens=2000,
        )

        content = response.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            content = content.rsplit("```", 1)[0]
        drafts_data = json.loads(content)

    except json.JSONDecodeError as e:
        logger.error(f"OpenAI returned invalid JSON: {e}")
        raise ValueError("AI generated invalid content format")
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        raise ValueError(f"AI content generation failed: {e}")

    # ── GEO-CULTURAL VALIDATION LOOP ──────────────────────────────────────
    # For paid drafts: collect AI-suggested interest keywords, validate them
    # against Meta's API via the MCP search_meta_interests tool, and store
    # the validated Meta Interest IDs in targeting_spec.
    access_token = ad_account.get("access_token", "") if ad_account else ""
    validated_interests_cache: list[dict] | None = None  # cache across drafts

    async def _validate_and_cache_interests(suggested_keywords: list[str]) -> list[dict]:
        nonlocal validated_interests_cache
        if validated_interests_cache is not None:
            return validated_interests_cache
        if not suggested_keywords:
            logger.warning("No suggested_keywords provided — skipping interest validation")
            validated_interests_cache = []
            return []
        if not access_token:
            logger.warning("No access_token — skipping MCP interest validation, using AI raw keywords as fallback")
            validated_interests_cache = []
            return []
        try:
            validated = await mcp_client.search_interests(
                suggested_keywords, target_country, access_token
            )
            validated_interests_cache = validated if isinstance(validated, list) else []
            if not validated_interests_cache:
                logger.warning(
                    "MCP search_meta_interests returned empty for keywords=%s country=%s — AI keywords will be used as fallback",
                    suggested_keywords, target_country,
                )
            else:
                logger.info(
                    "Geo-cultural interests validated: country=%s, keywords=%s, found=%d",
                    target_country, suggested_keywords, len(validated_interests_cache),
                )
            return validated_interests_cache
        except Exception as e:
            logger.warning("search_meta_interests failed: %s — AI keywords will be used as fallback", e)
            validated_interests_cache = []
            return []

    # ── Determine CTA context for post-processing (Bug Fix #2) ─────────
    product_type_for_cta = None
    ticket_price_for_cta = ticket_price
    has_website_for_cta = bool(website) or bool(focused_product and focused_product.get("landing_url"))
    if focused_product:
        product_type_for_cta = focused_product.get("product_type")
    elif products:
        # Infer from first product or leave None (defaults to e-commerce)
        product_type_for_cta = None

    # Insert drafts into database via httpx (avoids supabase-py insert bug)
    created = []
    for draft in drafts_data:
        # Bug Fix #1: Sanitize ad copy — fix spacing, strip banned buzzwords
        headline = _sanitize_ad_text(draft.get("headline") or "")
        body_text = _sanitize_ad_text(draft.get("body_text", ""))

        # Bug Fix #2: Override CTA based on product type + ticket price
        ai_cta = draft.get("cta_type", "LEARN_MORE")
        resolved_cta = _resolve_cta(
            ai_cta,
            product_type=product_type_for_cta,
            ticket_price=ticket_price_for_cta,
            has_website=has_website_for_cta,
        )

        # Bug Fix #3: Filter geo hallucinations from suggested interests
        suggested_interests = draft.get("suggested_interests", [])
        if suggested_interests:
            suggested_interests = _filter_geo_hallucinations(suggested_interests)

        record = {
            "user_id": user_id,
            "draft_type": draft.get("draft_type", "paid"),
            "status": "pending",
            "headline": headline,
            "body_text": body_text,
            "cta_type": resolved_cta,
            "ai_reasoning": draft.get("ai_reasoning"),
            "proposed_budget": daily_budget if draft.get("draft_type", "paid") == "paid" else None,
            "target_country": target_country,
        }
        if ad_account and draft.get("draft_type", "paid") == "paid":
            record["ad_account_id"] = ad_account["id"]

        # Product-specific fields
        if focused_product:
            record["product_id"] = focused_product["id"]
            if focused_product.get("image_url"):
                record["image_url"] = focused_product["image_url"]
            if focused_product.get("pixel_id"):
                record["pixel_id"] = focused_product["pixel_id"]
                record["conversion_event"] = conversion_event or "PURCHASE"
            if focused_product.get("profit_margin"):
                record.setdefault("targeting", {})
                if isinstance(record["targeting"], str):
                    record["targeting"] = json.loads(record["targeting"])
                record["targeting"]["profit_margin"] = float(focused_product["profit_margin"])

        # A/B variants
        if ab_test and draft.get("ab_variants"):
            record["ab_variants"] = json.dumps(draft["ab_variants"])

        # Geo-cultural targeting validation for paid ads
        if record["draft_type"] == "paid":
            suggested = suggested_interests  # already geo-filtered above (Bug Fix #3)
            validated_interests = await _validate_and_cache_interests(suggested)

            # Always save targeting_spec — use validated interests if available,
            # otherwise fall back to AI's raw keywords as pseudo-interests so the
            # frontend always has something to display.
            if validated_interests:
                record["targeting_spec"] = json.dumps({
                    "target_country": target_country,
                    "validated_interests": validated_interests,
                    "suggested_keywords": suggested,
                })
            elif suggested:
                # Fallback: convert raw AI keywords into the same shape the
                # frontend expects ({id, name}) so cards render correctly.
                fallback_interests = [
                    {"id": f"ai_{i}", "name": kw}
                    for i, kw in enumerate(suggested[:5])
                ]
                record["targeting_spec"] = json.dumps({
                    "target_country": target_country,
                    "validated_interests": fallback_interests,
                    "suggested_keywords": suggested,
                    "validation_status": "fallback",
                })
                logger.info(
                    "Using AI fallback interests for draft: %s",
                    [kw for kw in suggested[:5]],
                )
            else:
                # No interests at all — still save country so UI isn't blank
                record["targeting_spec"] = json.dumps({
                    "target_country": target_country,
                    "validated_interests": [],
                    "suggested_keywords": [],
                })

        resp = httpx.post(
            _postgrest_url("content_drafts"),
            headers=_postgrest_headers(),
            json=record,
            timeout=10,
        )
        if resp.status_code in (200, 201) and resp.json():
            created.append(resp.json()[0])

    return created
