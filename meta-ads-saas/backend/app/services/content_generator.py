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
from .special_ad_category_detector import (
    detect_special_ad_category,
    DraftContext as _SACDraftContext,
    CATEGORY_CATALOG as _SAC_CATALOG,
)

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

_CTA_FOR_HIGH_TICKET = ("LEARN_MORE", "CONTACT_US", "GET_QUOTE", "SIGN_UP")
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
    destination_type: str | None = None,
    whatsapp_number: str | None = None,
    selected_messaging_apps: list[str] | None = None,
    call_phone_number: str | None = None,
    hiring_data: dict | None = None,
    job_id: str | None = None,
    workspace_id: str | None = None,
) -> list[dict]:
    """
    Generate `count` content drafts for a user based on their preferences.
    Optionally focuses on a specific product and/or generates A/B variants.
    When hiring_data is provided, generates employment ads with HEC-compliant creative filtering.
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

    # Load workspace business context (overrides user_preferences for per-business fields)
    ws_context = {}
    if workspace_id:
        ws_result = (
            supabase.table("workspaces")
            .select("business_name, business_description, target_audience, website_url, "
                    "target_country, industry_niche, website_intel, website_scraped_at")
            .eq("id", workspace_id)
            .limit(1)
            .execute()
        )
        if ws_result.data:
            ws_context = {k: v for k, v in ws_result.data[0].items() if v is not None}
            # Overlay workspace fields onto prefs so downstream code picks them up
            for field in ("business_name", "business_description", "target_audience",
                          "website_url", "target_country", "industry_niche",
                          "website_intel", "website_scraped_at"):
                if ws_context.get(field):
                    prefs[field] = ws_context[field]

    # Load ad account (for paid drafts) — workspace-first, fallback to user_id
    if workspace_id:
        account_result = (
            supabase.table("ad_accounts")
            .select("id, meta_account_id, account_name, access_token, pixel_id")
            .eq("workspace_id", workspace_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
    else:
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
    _owner_filter = ("workspace_id", workspace_id) if workspace_id else ("user_id", user_id)
    focused_product = None
    if product_id:
        prod_result = (
            supabase.table("products")
            .select("*")
            .eq("id", product_id)
            .eq(*_owner_filter)
            .execute()
        )
        if prod_result.data:
            focused_product = prod_result.data[0]

    products_result = (
        supabase.table("products")
        .select("name, description, landing_url, price, currency, target_audience")
        .eq(*_owner_filter)
        .eq("is_active", True)
        .limit(5)
        .execute()
    )
    products = products_result.data or []

    # ── FEEDBACK LOOP: Load historical performance + market research ──────
    # Step 1: Load latest completed audit from DB
    audit = None
    try:
        _audit_q = (
            supabase.table("account_audits")
            .select("winning_ads, losing_ads, ai_strategy_report, audience_demographics, tone_recommendation")
            .eq(*_owner_filter)
            .eq("status", "completed")
            .order("created_at", desc=True)
            .limit(1)
        )
        audit_result = _audit_q.execute()
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

    # Step 2b: Fetch past ad creatives with full copy + performance
    past_ad_creatives = None
    if ad_account and ad_account.get("access_token"):
        try:
            past_ad_creatives = await mcp_client.get_ad_creatives_with_performance(
                ad_account["meta_account_id"], ad_account["access_token"], date_preset="last_30d",
            )
        except Exception as e:
            logger.warning(f"Failed to get ad creatives: {e}")

    # Step 2c: Fetch recent page posts (organic content with engagement)
    past_page_posts = None
    if ad_account and ad_account.get("access_token"):
        try:
            import httpx as _httpx
            from ..core.config import get_settings as _gs
            _settings = _gs()
            _base = f"https://graph.facebook.com/{_settings.META_API_VERSION}"
            # Get page_id from workspace
            _page_id = None
            if workspace_id:
                _ws_pg = supabase.table("workspaces").select("meta_page_id").eq("id", workspace_id).limit(1).maybe_single().execute()
                _page_id = _ws_pg.data.get("meta_page_id") if _ws_pg.data else None
            if _page_id:
                # Get page access token from /me/accounts
                async with _httpx.AsyncClient(timeout=10.0) as _c:
                    _pages_resp = await _c.get(f"{_base}/me/accounts", params={
                        "fields": "id,access_token", "access_token": ad_account["access_token"],
                    })
                    _pages_data = _pages_resp.json().get("data", [])
                    _page_token = next((p["access_token"] for p in _pages_data if p["id"] == _page_id), None)
                if _page_token:
                    past_page_posts = await mcp_client.get_page_posts(_page_id, _page_token)
        except Exception as e:
            logger.warning(f"Failed to get page posts for content gen: {e}")

    # Resolve target country: product-level override > user preferences > default
    target_country = "US"
    target_cities: list[dict] = []
    if focused_product and focused_product.get("target_country"):
        target_country = focused_product["target_country"]
    elif prefs.get("target_country"):
        target_country = prefs["target_country"]
    # Resolve target cities: product-level override > user preferences
    if focused_product and focused_product.get("target_cities") and isinstance(focused_product["target_cities"], list):
        target_cities = focused_product["target_cities"]
    elif prefs.get("target_cities") and isinstance(prefs["target_cities"], list):
        target_cities = prefs["target_cities"]

    # Hiring ads: override target_country from job data (takes priority over prefs)
    if hiring_data and hiring_data.get("target_country"):
        target_country = hiring_data["target_country"]
        logger.info("Hiring ad: overriding target_country to %s from job data", target_country)

    # Resolve country_name early (needed by hiring targeting pipeline + geo context)
    COUNTRY_NAMES_EARLY = {
        "PK": "Pakistan", "US": "United States", "GB": "United Kingdom",
        "AE": "UAE", "SA": "Saudi Arabia", "IN": "India", "CA": "Canada",
        "AU": "Australia", "DE": "Germany", "FR": "France", "TR": "Turkey",
        "MY": "Malaysia", "NG": "Nigeria", "KE": "Kenya", "BD": "Bangladesh",
    }
    country_name = COUNTRY_NAMES_EARLY.get(target_country, target_country)

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

    # Inject past ad creatives (full copy + performance) so AI avoids repetition and learns from winners
    if past_ad_creatives:
        # Parse MCP response — may be content[0].text JSON or direct dict
        _raw_creatives = past_ad_creatives
        if isinstance(_raw_creatives, dict) and "content" in _raw_creatives:
            try:
                _text = _raw_creatives["content"][0]["text"]
                _raw_creatives = json.loads(_text) if isinstance(_text, str) else _text
            except (KeyError, IndexError, json.JSONDecodeError):
                pass
        ads_list = _raw_creatives if isinstance(_raw_creatives, list) else _raw_creatives.get("ads", []) if isinstance(_raw_creatives, dict) else []
        if ads_list:
            # Sort by results desc, take top performers and worst
            sorted_ads = sorted(ads_list, key=lambda a: a.get("results", 0), reverse=True)
            top_ads = [
                {"name": a.get("ad_name", ""), "headline": a.get("headline", ""), "body": a.get("body_text", "")[:200],
                 "cta": a.get("cta_type", ""), "results": a.get("results", 0), "ctr": a.get("ctr", 0),
                 "cost_per_result": a.get("cost_per_result")}
                for a in sorted_ads[:5] if a.get("body_text")
            ]
            worst_ads = [
                {"name": a.get("ad_name", ""), "headline": a.get("headline", ""), "body": a.get("body_text", "")[:150],
                 "cta": a.get("cta_type", "")}
                for a in sorted_ads[-3:] if a.get("body_text") and a.get("results", 0) == 0
            ]
            if top_ads or worst_ads:
                performance_context += f"""

## PAST AD COPY (your actual ads with performance)
Best performing ad copy: {json.dumps(top_ads)}
{f"Worst performing ad copy (0 results): {json.dumps(worst_ads)}" if worst_ads else ""}

RULES:
- Do NOT repeat these headlines or body text — write FRESH angles
- Study WHY the top ads worked (hooks, structure, CTA) and create new variations
- Avoid the tone/angle of the worst performers"""

    # Inject recent organic page posts so AI understands brand voice and avoids repeating content
    if past_page_posts:
        posts_list = past_page_posts.get("posts", []) if isinstance(past_page_posts, dict) else []
        if posts_list:
            # Take top 5 by engagement, include message + metrics
            sorted_posts = sorted(posts_list, key=lambda p: (p.get("reactions", 0) + p.get("shares", 0)), reverse=True)
            top_posts = [
                {"text": p.get("message", "")[:200], "likes": p.get("likes", 0),
                 "reactions": p.get("reactions", 0), "shares": p.get("shares", 0), "comments": p.get("comments", 0)}
                for p in sorted_posts[:5] if p.get("message")
            ]
            if top_posts:
                performance_context += f"""

## RECENT ORGANIC POSTS (from your Facebook Page)
{json.dumps(top_posts)}

Use these posts to understand:
- The brand's natural voice and style
- Topics that get engagement (high reactions/shares = resonating)
- Do NOT copy these posts — use them as tone/voice reference only
- Write ad copy that's consistent with this brand voice but optimized for paid performance"""

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

    # ── HYBRID TARGETING: LLM search terms → Meta API grounding ──────────────
    # LLM generates broad search terms describing the buyer's identity,
    # then we search Meta's interest API to find real targetable interests,
    # and filter out any that match the product's own industry.
    pre_validated_interests: list[dict] = []
    print(f"[TARGETING-DEBUG] access_token_for_research={bool(access_token_for_research)}, niche={repr(niche)}, biz_desc={repr(biz_desc[:50] if biz_desc else '')}, target_aud={repr(target_aud[:50] if target_aud else '')}", flush=True)
    # ── HIRING ADS: Dedicated candidate-persona targeting pipeline ──────────
    # The normal pipeline analyzes the BUSINESS to find BUYERS.
    # For hiring, we need to analyze the JOB ROLE to find CANDIDATES.
    # This is a separate 2-stage pipeline: LLM persona → Meta API validation.
    if hiring_data and access_token_for_research:
        hd_targeting = hiring_data
        _hiring_skills = ', '.join(hd_targeting.get('skills', [])) if hd_targeting.get('skills') else 'see job requirements'
        _hiring_prompt = f"""You are an Elite Behavioral Analyst and Meta Ads Headhunter.

TASK: Generate search terms to find HIGH-QUALITY, PASSIVE candidates for this role:
- Job Title: {hd_targeting['job_title']}
- Seniority: {hd_targeting.get('experience_level', 'mid')}
- Skills: {_hiring_skills}
- Country: {country_name} ({target_country})
{f"- Requirements: {hd_targeting.get('requirements', '')[:200]}" if hd_targeting.get('requirements') else ""}

Think step by step about WHO this candidate is in their daily professional life in {country_name}.

Output strict JSON:
{{
  "step_1_candidate_identity": "Describe this candidate's daily professional life in {country_name}. What tools do they open every morning? What do they read? What companies do they admire? Be specific to {country_name}'s market.",
  "step_2_forbidden_terms": ["terms that would attract WRONG people — job seekers, employers, unrelated industries"],
  "step_3_search_terms": ["term1", "term2", ... up to 15 terms],
  "step_4_reasoning": "Why these terms will find passive, high-quality candidates"
}}

CRITICAL RULES:

step_2_forbidden_terms: ALWAYS include these generic job-seeking terms:
"job hunting", "career development", "indeed", "resume", "interview", "employment",
"job search", "glassdoor", "freelancing", "recruitment"
Plus any terms that would attract the WRONG type of professional.

step_3_search_terms: Generate 12-15 search terms using these 3 pillars:

PILLAR 1 — TOOLS & ACTIVITIES (What do they DO daily?):
Target the specific activities, tools, software, or methodologies this person uses.
Think: what does this person's WORK DAY look like?
- For a cold caller: "cold calling", "telemarketing", "outbound sales", "CRM software"
- For a developer: "React.js", "Docker", "GitHub", "agile software development"
- For a nurse: "patient care", "electronic health record", "clinical nursing"
- For an HR manager: "human resource management", "talent acquisition", "employee engagement"
Keep terms SHORT (1-3 words). Meta's search works best with simple terms.

PILLAR 2 — INDUSTRY ECOSYSTEM (What do they FOLLOW/READ?):
Professional associations, certifications, industry publications, conferences.
- For sales: "Sales management", "B2B marketing"
- For tech: "Stack Overflow", "GitHub", "TechCrunch"
- For medical: "American Medical Association", "nursing"
- For {country_name}: use LOCAL bodies — PEC, PMDC, ICAP, SHRM, IEEE, etc.

PILLAR 3 — ASPIRATIONAL BRANDS (Who do they ADMIRE?):
Large companies or brands in this field that professionals follow on social media.
- For consulting: "McKinsey & Company", "Deloitte"
- For tech: "Google", "Microsoft"
- For sales tools: "HubSpot", "Salesforce"
Pick brands that are RELEVANT in {country_name}, not just globally famous.

IMPORTANT — TARGET THE ROLE, NOT THE PRODUCT:
If the job is "Sales Agent selling web design services", target SALES interests
(cold calling, CRM, telemarketing) — NOT design interests (Figma, Photoshop).
The product they sell is irrelevant for targeting. Target who the CANDIDATE is.

SENIORITY CALIBRATION:
- Entry level: target activities and broad tools ("cold calling", "customer service", "data entry")
- Mid level: target specific tools and methodologies ("HubSpot", "agile", "project management")
- Senior/Lead: target industry thought leadership and associations ("Harvard Business Review", "McKinsey")

MIX: Include 5-7 activity/tool terms, 3-4 ecosystem terms, 2-3 aspirational brands."""

        try:
            from openai import AsyncOpenAI as _AO_Hiring
            _oai_h = _AO_Hiring(api_key=get_settings().OPENAI_API_KEY)
            _s_h = get_settings()
            _resp_h = await _oai_h.chat.completions.create(
                model=_s_h.CREATIVE_WRITING_MODEL,
                messages=[
                    {"role": "system", "content": _hiring_prompt},
                    {"role": "user", "content": f"Generate targeting search terms for: {hd_targeting['job_title']} ({hd_targeting.get('experience_level', 'mid')} level) in {country_name}. Think deeply about who this person IS, not what they'll sell."},
                ],
                max_completion_tokens=800,
                response_format={"type": "json_object"},
            )
            _h_text = (_resp_h.choices[0].message.content or "").strip()
            if _h_text.startswith("```"):
                _h_text = _h_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            if not _h_text.startswith("{") and "{" in _h_text:
                _h_text = _h_text[_h_text.index("{"):_h_text.rindex("}") + 1]
            _h_parsed = json.loads(_h_text)

            _h_search_terms = _h_parsed.get("step_3_search_terms") or []
            _h_forbidden = _h_parsed.get("step_2_forbidden_terms") or []
            _h_forbidden = [str(t).strip().lower() for t in _h_forbidden if str(t).strip()]
            # Always ban these regardless of LLM output
            _h_forbidden.extend(["job hunting", "indeed", "resume", "career development", "glassdoor", "job search", "interview", "freelancing", "employment", "recruitment"])
            _h_forbidden = list(set(_h_forbidden))

            import unicodedata
            clean_h_terms = []
            for kw in _h_search_terms[:15]:
                kw = unicodedata.normalize("NFKC", str(kw).strip()).replace("\u2011", "-").replace("\u2013", "-")
                if len(kw) >= 2:
                    clean_h_terms.append(kw)

            logger.info("[HIRING-TARGETING] Candidate persona: %s", _h_parsed.get("step_1_candidate_identity", "")[:200])
            logger.info("[HIRING-TARGETING] Search terms (%d): %s", len(clean_h_terms), clean_h_terms)
            logger.info("[HIRING-TARGETING] Forbidden: %s", _h_forbidden[:10])

            if clean_h_terms:
                # Stage 2: Search Meta's interest API with candidate-focused terms
                from .targeting_engine import _filter_forbidden, _filter_sac_blocklist
                _h_raw_interests = await mcp_client.search_interests(
                    clean_h_terms, target_country, access_token_for_research,
                )
                _h_raw_interests = _h_raw_interests if isinstance(_h_raw_interests, list) else []
                # Filter forbidden terms (job-seeking garbage)
                _h_filtered = _filter_forbidden(_h_raw_interests, _h_forbidden)
                # Hiring ads run under EMPLOYMENT SAC — drop blocklisted interests.
                _h_filtered = _filter_sac_blocklist(_h_filtered, ["EMPLOYMENT"])
                logger.info("[HIRING-TARGETING] Meta API search: %d raw → %d after forbidden filter", len(_h_raw_interests), len(_h_filtered))

                # Stage 2b: ENRICHMENT — feed found interests as seeds to discover related ones
                if _h_filtered:
                    _seed_names = [i["name"] for i in _h_filtered[:5]]
                    try:
                        _h_suggestions = await mcp_client.suggest_related_interests(
                            _seed_names, access_token_for_research, limit=40,
                        )
                        _h_suggestions = _filter_forbidden(_h_suggestions, _h_forbidden)
                        _h_suggestions = _filter_sac_blocklist(_h_suggestions, ["EMPLOYMENT"])
                        # Merge: deduplicate by ID
                        _seen_ids = {i["id"] for i in _h_filtered}
                        for s in _h_suggestions:
                            if s["id"] not in _seen_ids:
                                _seen_ids.add(s["id"])
                                _h_filtered.append(s)
                        logger.info("[HIRING-TARGETING] Enrichment: %d seeds → %d new suggestions, pool now %d",
                                    len(_seed_names), len(_h_suggestions), len(_h_filtered))
                    except Exception as e:
                        logger.warning("[HIRING-TARGETING] Enrichment failed (non-fatal): %s", e)

                if _h_filtered:
                    # Stage 3: Sniper selection — pick best 5 from ENRICHED pool
                    from .targeting_engine import _sniper_selection
                    _role_context = f"Hiring a {hd_targeting['job_title']} ({hd_targeting.get('experience_level', 'mid')} level). Skills: {_hiring_skills}. Target: passive candidates who are GOOD at this job, not job seekers."
                    pre_validated_interests = await _sniper_selection(
                        _h_filtered, _role_context, "", country_name, _h_forbidden,
                    )
                    logger.info("[HIRING-TARGETING] Sniper selected %d interests: %s",
                                len(pre_validated_interests), [i.get("name") for i in pre_validated_interests])
                else:
                    logger.warning("[HIRING-TARGETING] No interests survived Meta validation + forbidden filter")
        except Exception as e:
            import traceback
            logger.warning("[HIRING-TARGETING] Pipeline failed (non-fatal): %s\n%s", e, traceback.format_exc())

    elif hiring_data:
        logger.info("Hiring ad: no access_token for research — LLM prompt will suggest interests")
    elif access_token_for_research:
        # Build targeting context — always include business name + audience + niche
        _targeting_context_parts = []
        print(f"[TARGETING-CONTEXT] focused_product={bool(focused_product)}, user_guidance={repr(user_guidance[:50] if user_guidance else None)}", flush=True)
        if focused_product:
            # Product-focused: use ONLY the product context, not the business niche
            # This prevents "Digital Marketing Agency" from contaminating honey targeting
            _targeting_context_parts.append(f"Product: {focused_product.get('name', '')} — {focused_product.get('description', '')}")
            _prod_type = focused_product.get("product_type", "")
            if _prod_type:
                _targeting_context_parts.append(f"Product type: {_prod_type}")
        elif user_guidance and user_guidance.strip():
            # Ad-hoc draft with creative direction — use the guidance as primary context
            # so targeting matches the ad topic, not the business profile
            _targeting_context_parts.append(f"Product/Service being advertised: {user_guidance.strip()}")
        else:
            _targeting_context_parts.append(f"Business: {biz_name} — {biz_desc}")
            if niche:
                _targeting_context_parts.append(f"Industry/niche: {niche}")
        # Only include target_audience from preferences if NOT product-focused
        # Product-focused targeting should derive the audience from the product itself
        if not focused_product and target_aud:
            _targeting_context_parts.append(f"Target audience: {target_aud}")
        elif focused_product and focused_product.get("target_audience"):
            _targeting_context_parts.append(f"Target audience: {focused_product['target_audience']}")

        if _targeting_context_parts:
            _targeting_prompt = "\n".join(_targeting_context_parts)
            print(f"[TARGETING-PROMPT] {_targeting_prompt[:200]}", flush=True)

            # ── SAC detection (run once per generation, before targeting prompt) ──
            # Detects whether this batch of drafts must run under a Meta Special
            # Ad Category. The result is cached on `_sac_decision` and:
            #   1. Used to bias the search-terms LLM prompt (no brand names under SAC)
            #   2. Saved on each draft record so ad_executor doesn't re-detect at publish
            #   3. Surfaced in the UI so the user knows what restrictions apply
            _sac_decision = None
            try:
                _sac_decision = await detect_special_ad_category(_SACDraftContext(
                    headline=None,  # drafts not yet generated
                    body_text=user_guidance.strip() if (user_guidance and user_guidance.strip()) else None,
                    product_name=focused_product.get("name") if focused_product else None,
                    product_description=focused_product.get("description") if focused_product else None,
                    product_type=focused_product.get("product_type") if focused_product else None,
                    industry_niche=niche,
                    business_name=biz_name,
                    business_description=biz_desc,
                    website_url=prefs.get("website_url") if prefs else None,
                    target_country=target_country,
                    is_explicit_hiring=bool(hiring_data),
                ))
                if _sac_decision.category:
                    logger.info(
                        "[SAC] Detected category=%s confidence=%.2f auto_apply=%s — %s",
                        _sac_decision.category, _sac_decision.confidence,
                        _sac_decision.should_auto_apply, _sac_decision.reasoning,
                    )
            except Exception as _e:
                logger.warning("[SAC] Detection failed at generation time: %s", _e)
                _sac_decision = None

            # ── Build SAC-aware system prompt suffix ──────────────────────
            # When running under SAC, Meta strips brand-name and instrument-specific
            # interests (Robinhood, TradingView, Coinbase, Options strategies, etc.).
            # We tell the LLM upfront so it generates broad lifestyle search terms
            # instead of brand names that will get rejected at publish time.
            _sac_prompt_suffix = ""
            # Bias the targeting LLM away from brand names whenever a SAC is
            # even *plausibly* detected (≥0.5 confidence). The bias is non-binding
            # — it just shifts toward broader interests. Worst case if we're
            # wrong: slightly less brand-precision. Best case if we're right:
            # we save the campaign from Meta auto-rejection.
            if _sac_decision and _sac_decision.category and _sac_decision.confidence >= 0.5:
                _sac_label = next(
                    (c["label"] for c in _SAC_CATALOG if c["code"] == _sac_decision.category),
                    _sac_decision.category,
                )
                _sac_prompt_suffix = (
                    f"\n\n## CRITICAL: This ad runs under Meta Special Ad Category"
                    f' "{_sac_label}".\n'
                    f"Meta automatically STRIPS the following from your search-term suggestions:\n"
                    f"  • Brand-name interests (specific companies, exchanges, platforms, publications)\n"
                    f"  • Instrument-specific interests (specific products, instruments, methodologies)\n"
                    f"  • Income / wealth / education-for-finance demographics\n"
                    f"DO NOT suggest brand names, competitor product names, news outlet names, "
                    f"specific platforms, specific instruments, or specific methodologies. "
                    f"DO suggest broad lifestyle / behavior / interest categories that describe "
                    f"WHO the buyer is, not WHAT TOOLS they use. Examples of the right kind of "
                    f"abstraction: \"Day trading\", \"Investing\", \"Personal finance\", "
                    f"\"Stock market\", \"Online trading\" — broad audience pools that survive "
                    f"under Meta's category restrictions."
                )

            try:
                from .targeting_engine import _SEARCH_TERMS_SYSTEM_PROMPT, _filter_forbidden, _filter_sac_blocklist, _sniper_selection
                from openai import AsyncOpenAI as _AO
                _oai = _AO(api_key=get_settings().OPENAI_API_KEY)
                _s = get_settings()
                _resp = await _oai.chat.completions.create(
                    model=_s.CREATIVE_WRITING_MODEL,
                    messages=[
                        {"role": "system", "content": _SEARCH_TERMS_SYSTEM_PROMPT + f"\nTarget market: {target_country}." + _sac_prompt_suffix},
                        {"role": "user", "content": f"""Context:
{_targeting_prompt}

First decide B2B or B2C. Then describe the buyer AS THEY EXIST IN {target_country}. Then list forbidden industry terms. Then output 15-20 search terms that describe the buyer's world in {target_country} — NOT the product's industry."""},
                    ],
                    max_completion_tokens=800,
                    response_format={"type": "json_object"},
                )
                _choice = _resp.choices[0]
                _text = (_choice.message.content or "").strip()
                if not _text:
                    for attr in ("reasoning_content", "output", "refusal"):
                        val = getattr(_choice.message, attr, None)
                        if val:
                            _text = val.strip()
                            break
                if not _text:
                    _raw_msg = _choice.message.model_dump() if hasattr(_choice.message, "model_dump") else {}
                    for k, v in _raw_msg.items():
                        if isinstance(v, str) and len(v) > 10 and "{" in v:
                            _text = v.strip()
                            break
                print(f"[TARGETING] Hybrid response ({len(_text)} chars): {_text[:300]}", flush=True)
                if not _text:
                    raise ValueError("LLM returned empty content for targeting")
                if _text.startswith("```"):
                    _text = _text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                if not _text.startswith("{") and "{" in _text:
                    _text = _text[_text.index("{"):_text.rindex("}") + 1]
                _parsed = json.loads(_text)

                # Extract search terms and forbidden terms
                _search_terms = _parsed.get("step_4_search_terms") or _parsed.get("search_terms") or []
                _forbidden_raw = _parsed.get("step_3_forbidden_terms") or []
                if isinstance(_forbidden_raw, str):
                    _forbidden_terms = [t.strip().lower() for t in _forbidden_raw.split(",") if t.strip()]
                else:
                    _forbidden_terms = [str(t).strip().lower() for t in _forbidden_raw if str(t).strip()]

                import unicodedata
                clean_search_terms = []
                for kw in _search_terms[:20]:
                    kw = unicodedata.normalize("NFKC", str(kw).strip()).replace("\u2011", "-").replace("\u2013", "-")
                    if len(kw) >= 2:
                        clean_search_terms.append(kw)
                print(f"[TARGETING] Search terms ({len(clean_search_terms)}): {clean_search_terms}, Forbidden: {_forbidden_terms}", flush=True)

                if clean_search_terms:
                    # Step 2: Search Meta's interest API with all 15-20 terms
                    _raw_interests = await mcp_client.search_interests(
                        clean_search_terms, target_country, access_token_for_research,
                    )
                    _raw_interests = _raw_interests if isinstance(_raw_interests, list) else []
                    # Step 3: Filter out forbidden industry terms
                    _filtered = _filter_forbidden(_raw_interests, _forbidden_terms)
                    # Step 3a: SAC blocklist — drop interests Meta has previously
                    # rejected for this Special Ad Category (learned from past
                    # publishes via sac_reconciler). No-op for non-SAC drafts.
                    _sac_cat_list = (
                        [_sac_decision.category]
                        if _sac_decision and _sac_decision.category
                        else []
                    )
                    _filtered = _filter_sac_blocklist(_filtered, _sac_cat_list)
                    print(f"[TARGETING] Pool: {len(_raw_interests)} raw → {len(_filtered)} after forbidden filter", flush=True)

                    # Step 3b: ENRICHMENT — use found interests as seeds for suggestions
                    if _filtered:
                        try:
                            _seed_names = [i["name"] for i in _filtered[:5]]
                            _suggestions = await mcp_client.suggest_related_interests(
                                _seed_names, access_token_for_research, limit=40,
                            )
                            _suggestions = _filter_forbidden(_suggestions, _forbidden_terms)
                            _suggestions = _filter_sac_blocklist(_suggestions, _sac_cat_list)
                            _seen_ids = {i["id"] for i in _filtered}
                            for s in _suggestions:
                                if s["id"] not in _seen_ids:
                                    _seen_ids.add(s["id"])
                                    _filtered.append(s)
                            print(f"[TARGETING] Enrichment: {len(_seed_names)} seeds → {len(_suggestions)} suggestions, pool now {len(_filtered)}", flush=True)
                        except Exception as e:
                            logger.warning("Targeting enrichment failed (non-fatal): %s", e)

                    # Step 4: SNIPER SELECTION — Elite LLM picks best 5 from ENRICHED pool
                    pre_validated_interests = await _sniper_selection(
                        _filtered, _targeting_prompt, biz_desc or "", target_country, _forbidden_terms,
                    )
                    print(f"[TARGETING] Sniper selected: {[i.get('name') for i in pre_validated_interests]}", flush=True)
            except Exception as e:
                import traceback
                logger.warning("Targeting research failed (non-fatal): %s\n%s", e, traceback.format_exc())

    # ── ADVANTAGE+ FALLBACK: sparse interest pool detection ──────────────
    # If Meta API returned fewer than 3 valid interests, don't pad with garbage.
    # Accept the sparse pool and flag for Advantage+ Audience expansion.
    advantage_plus_expanded = False
    if pre_validated_interests and len(pre_validated_interests) < 3:
        advantage_plus_expanded = True
        logger.info(
            "[ADVANTAGE+] Sparse interest pool (%d < 3) — flagging for Advantage+ expansion: %s",
            len(pre_validated_interests), [i.get("name") for i in pre_validated_interests],
        )
    # Employment ads: only force Advantage+ if enrichment still couldn't fill the pool
    if hiring_data and len(pre_validated_interests) < 3:
        advantage_plus_expanded = True

    # Build targeting context for the LLM prompt
    targeting_pool_context = ""
    if pre_validated_interests:
        interest_names = [i["name"] for i in pre_validated_interests]
        targeting_pool_context = f"""

## PRE-VALIDATED TARGETING INTERESTS (from Meta API — these are REAL targetable interests)
Available interests: {json.dumps(interest_names)}

IMPORTANT: For "suggested_interests", you MUST pick 3-5 from this list above.
Do NOT invent your own interest keywords. Each draft should pick a DIFFERENT subset to test different audience segments."""

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
    # Build city-aware context
    city_names = [c["name"] if isinstance(c, dict) else c for c in target_cities] if target_cities else []
    city_label = ", ".join(city_names) if city_names else ""

    geo_cultural_context = f"""

TARGET MARKET: {country_name} ({target_country}){f' — specifically: {city_label}' if city_label else ''}
Write ad copy that resonates with {country_name} consumers. Use culturally appropriate
language, references, and value propositions. Do NOT use US-centric references
(like "Whole Foods", "Trader Joe's", American holidays) unless targeting the US."""

    if city_names:
        geo_cultural_context += f"""
CITY-SPECIFIC TARGETING: Ads will run ONLY in {city_label}.
- Reference local landmarks, culture, or city-specific pain points where relevant.
- Use language and references that feel native to these cities (e.g. local slang, neighborhoods, events).
- If the product has local delivery/service, emphasize availability in these specific cities.
- Do NOT reference cities outside the target list."""

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

    # ── HIRING ADS MODE ──────────────────────────────────────────────────
    if hiring_data:
        hd = hiring_data
        # Override target country from job data
        if hd.get("target_country"):
            target_country = hd["target_country"]
            country_name = COUNTRY_NAMES.get(target_country, target_country)
            # Rebuild geo context with job's country
            job_location = hd.get("location", "")
            geo_cultural_context = f"""

TARGET MARKET: {country_name} ({target_country}){f' — specifically: {job_location}' if job_location else ''}
Write ad copy that resonates with {country_name} job seekers. Use culturally appropriate
language, salary references in {hd.get('salary_currency', 'PKR') if hd.get('salary_currency') else target_country} and local job market context."""

            if target_country in {"PK", "SA", "AE", "BD", "MY", "TR"}:
                geo_cultural_context += f"""
CULTURAL SENSITIVITY ({country_name}): This is a conservative/Islamic market.
- Use respectful, professional language appropriate for the local culture.
- Emphasize stability, family-friendly benefits, and growth opportunities."""

        # Build hiring targeting context from pre-validated interests (if pipeline ran)
        hiring_targeting_context = ""
        if pre_validated_interests:
            _h_interest_names = [i["name"] for i in pre_validated_interests]
            hiring_targeting_context = f"""

## PRE-VALIDATED TARGETING INTERESTS (from Meta API — real targetable interests)
Available interests: {json.dumps(_h_interest_names)}
For "suggested_interests", pick 3-5 from this list. Do NOT invent your own."""

        system_prompt = f"""You are an expert Meta Recruitment Ads copywriter specializing in HEC-compliant employment advertising.

COMPANY: {hd.get('company_name') or biz_name}
{f"About: {biz_desc}" if biz_desc else ""}
{f"Website: {website}" if website else ""}

JOB DETAILS:
- Job Title: {hd['job_title']}
- Target Candidate Profile: {hd['target_candidate_profile']}
- Salary & Perks: {hd['salary_and_perks']}
{f"- Work Mode: {hd.get('work_mode', 'onsite')}" if hd.get('work_mode') else ""}
{f"- Employment Type: {hd.get('employment_type', 'full_time')}" if hd.get('employment_type') else ""}
{f"- Location: {hd.get('location', '')}" if hd.get('location') else ""}
{f"- Experience Level: {hd.get('experience_level', '')}" if hd.get('experience_level') else ""}
{f"- Education: {hd.get('education_level', '')}" if hd.get('education_level') else ""}
{f"- Required Skills: {', '.join(hd.get('skills', []))}" if hd.get('skills') else ""}
{f"- Requirements: {hd.get('requirements', '')}" if hd.get('requirements') else ""}
{f"- Responsibilities: {hd.get('responsibilities', '')}" if hd.get('responsibilities') else ""}

Tone: {tone} — {tone_desc}
{geo_cultural_context}
{hiring_targeting_context}

{guidance_block}

══════════════════════════════════════════════════
STEP 1 — RESEARCH ANALYSIS (output this in ai_reasoning)
══════════════════════════════════════════════════
Analyze what makes a top-performing Meta Recruitment Ad in 2024-2026. Consider:
- Transparency about salary and expectations (candidates hate vague "competitive salary")
- Clear hooks that grab attention in the first sentence
- Company culture signals that build trust
- Readability — short paragraphs, bullet points, easy scanning on mobile
- Social proof: team size, growth trajectory, notable clients

══════════════════════════════════════════════════
STEP 2 — CREATIVE FILTERING (CRITICAL — HEC COMPLIANCE)
══════════════════════════════════════════════════
Meta BANS all demographic targeting (age, gender, zip code) for Employment ads.
Your FIRST SENTENCE (the Hook) must act as the targeting mechanism.
It MUST call out the specific target candidate profile: "{hd['target_candidate_profile']}"
so that unqualified people naturally scroll past.

Examples of good creative filters:
- "O/A Level grads who can hold a conversation in English — we're hiring."
- "Designers who think Figma is a lifestyle, not just a tool."
- "Sales professionals who've closed $50K+ deals — your next chapter starts here."

The hook IS your targeting. Get it right.

══════════════════════════════════════════════════
STEP 3 — GENERATE 3 DISTINCT ANGLES
══════════════════════════════════════════════════

ANGLE 1 — "The Culture & Perks Angle":
Focus on WHY this is a great place to work. Lead with salary transparency ({hd['salary_and_perks']}),
benefits, team vibe, work-life balance. Make the reader think "I want to work THERE."

ANGLE 2 — "The Direct & Transparent Angle":
No fluff. Bullet-point the exact requirements and responsibilities.
Clear, scannable, professional. For candidates who want to self-qualify fast.

ANGLE 3 — "The Career Growth Angle":
Focus on learning, mentorship, stepping-stone opportunities, and where this role leads.
Appeal to ambitious candidates who think long-term about their career trajectory.

{copy_quality_rules}

IMPORTANT RULES FOR EMPLOYMENT ADS:
- NEVER mention age, gender, race, religion, or any protected class in the ad copy.
- ALWAYS include the salary/perks transparently — this is your competitive advantage.
- Keep body_text between 3-6 sentences. Mobile-first formatting.
- Use "Apply Now" or "Send your CV" style CTAs — not "Shop Now".

Generate exactly 3 ad drafts (one per angle). Return a JSON array of 3 objects:
- "draft_type": "paid"
- "headline": short punchy headline (max 40 chars) about the role
- "body_text": the full ad copy with the creative-filtering hook as the first sentence
- "cta_type": MUST be "APPLY_NOW" or "LEARN_MORE" or "SIGN_UP" — NEVER use "SHOP_NOW" for hiring ads
- "ai_reasoning": Your Step 1 research analysis + why this specific angle will work
- "proposed_budget": {daily_budget}
- "suggested_interests": array of 5 interests targeting the CANDIDATE's professional identity (tools they use, activities they do, associations they follow). Target who the CANDIDATE is — NOT the industry they'll work in. NEVER suggest job-seeking terms like "Indeed", "Resume", "Job hunting". Example for a cold caller: ["Cold calling", "Telemarketing", "CRM software", "HubSpot", "B2B marketing"]. Example for a developer: ["React.js", "GitHub", "Docker", "Stack Overflow", "Agile software development"].

Return ONLY the JSON array, no markdown formatting."""

        # Force count to 3 for hiring (one per angle)
        count = 3

    # Build prompt — product-focused vs business-general
    elif focused_product:
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
{geo_cultural_context}{pixel_strategy}{performance_context}{market_context}{competitor_context}{targeting_pool_context}{ab_instructions}

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
- "suggested_interests": (PAID only) array of 3-5 interests — pick from the PRE-VALIDATED TARGETING INTERESTS list above if available. Each draft MUST pick a DIFFERENT subset. If no pre-validated list is provided, suggest 5-7 SPECIFIC interest keywords. NO geographic names.
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
{product_context}{niche_context}{geo_cultural_context}{pixel_strategy}{performance_context}{market_context}{competitor_context}{targeting_pool_context}{ab_instructions}

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
- "suggested_interests": (PAID only) array of 3-5 interests — pick from the PRE-VALIDATED TARGETING INTERESTS list above if available. Each draft MUST pick a DIFFERENT subset. If no pre-validated list is provided, suggest 5-7 SPECIFIC interest keywords. NO geographic names.
{'"ab_variants": object with headline_a, headline_b, body_text_a, body_text_b' if ab_test else ''}

The ads MUST mention "{biz_name}" by name and reference specific products/services from the business description. If a website URL is provided, use it as the landing page reference.

Return ONLY the JSON array, no markdown formatting."""

    # Robust content-gen with retries + model fallback. Reasoning-class models
    # (gpt-5.x, o1) sometimes return None or empty content with the actual output
    # in `reasoning_content`. Older models can also occasionally emit `[]`. We:
    #  1. Pull from message.content; fall back to reasoning_content / refusal slots
    #  2. Force JSON-mode response_format to reduce empty/markdown returns
    #  3. Retry once on empty / empty-array with a stronger explicit instruction
    #  4. If still empty, fall back to a simpler model so the user still gets drafts
    drafts_data = []
    _last_err: str | None = None

    async def _try_gen(model: str, system: str, attempt_label: str) -> list:
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": (
                        f"Generate exactly {count} high-converting ad drafts now. "
                        f"Output ONLY a JSON array of {count} draft objects, no markdown, "
                        f"no commentary. Empty arrays are not acceptable — you must "
                        f"produce {count} fully-fleshed-out drafts."
                    )},
                ],
                max_completion_tokens=4000,
                response_format={"type": "json_object"},
            )
            choice = resp.choices[0]
            text = (choice.message.content or "").strip()
            if not text:
                # Some reasoning models surface output via alternate fields
                for attr in ("reasoning_content", "output", "refusal"):
                    val = getattr(choice.message, attr, None)
                    if isinstance(val, str) and val.strip():
                        text = val.strip()
                        break
            if not text:
                logger.warning("[DRAFT-GEN] %s: empty content from %s", attempt_label, model)
                return []
            # Strip markdown if any leaked through despite json_object mode
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            # JSON-mode forces an object — accept either {drafts: [...]} or {"items": [...]}
            # or a top-level array (some models still emit one).
            if text.startswith("["):
                parsed = json.loads(text)
            else:
                parsed_obj = json.loads(text)
                if isinstance(parsed_obj, list):
                    parsed = parsed_obj
                else:
                    # Find the first list in the object's values
                    parsed = next(
                        (v for v in parsed_obj.values() if isinstance(v, list)),
                        [],
                    )
            if not isinstance(parsed, list):
                logger.warning("[DRAFT-GEN] %s: non-list response from %s: %r", attempt_label, model, text[:200])
                return []
            logger.info("[DRAFT-GEN] %s: %s returned %d drafts", attempt_label, model, len(parsed))
            return parsed
        except json.JSONDecodeError as je:
            logger.warning("[DRAFT-GEN] %s: invalid JSON from %s: %s", attempt_label, model, je)
            return []
        except Exception as ex:
            nonlocal _last_err
            _last_err = str(ex)
            logger.warning("[DRAFT-GEN] %s: %s call failed: %s", attempt_label, model, ex)
            return []

    # Attempt 1: primary model, original prompt
    drafts_data = await _try_gen(settings.CREATIVE_WRITING_MODEL, system_prompt, "primary")

    # Attempt 2: retry with a more forceful instruction
    if not drafts_data:
        forceful_system = (
            system_prompt
            + "\n\nCRITICAL: You must return a non-empty JSON array of exactly "
            + str(count)
            + " ad drafts. Returning an empty array, null, or a single object instead of an array is a hard failure. "
            + "Each draft must include headline, body_text, draft_type, cta_type, ai_reasoning."
        )
        drafts_data = await _try_gen(settings.CREATIVE_WRITING_MODEL, forceful_system, "retry-forceful")

    # Attempt 3: model fallback if primary keeps returning empty
    if not drafts_data:
        fallback_model = "gpt-4o-mini"  # fast, cheap, reliable JSON
        drafts_data = await _try_gen(fallback_model, system_prompt, f"fallback-{fallback_model}")

    if not drafts_data:
        # All retries exhausted — surface a clear error to the API caller
        logger.error("[DRAFT-GEN] All attempts returned empty. Last error: %s", _last_err)
        raise ValueError(
            "AI returned empty drafts after retries. "
            "This usually means the LLM service is degraded or your prompt is too complex. "
            f"Last error: {_last_err or 'empty response'}"
        )

    # ── GEO-CULTURAL VALIDATION LOOP ──────────────────────────────────────
    # For paid drafts: collect AI-suggested interest keywords, validate them
    # against Meta's API via the MCP search_meta_interests tool, and store
    # the validated Meta Interest IDs in targeting_spec.
    access_token = ad_account.get("access_token", "") if ad_account else ""
    # Cache validated interests per unique keyword set (avoids duplicate API calls
    # for same keywords, but allows different drafts to have different targeting)
    _interests_cache: dict[str, list[dict]] = {}

    async def _validate_interests(suggested_keywords: list[str]) -> list[dict]:
        cache_key = ",".join(sorted(set(k.lower().strip() for k in suggested_keywords)))
        if cache_key in _interests_cache:
            return _interests_cache[cache_key]
        if not suggested_keywords:
            _interests_cache[cache_key] = []
            return []
        if not access_token:
            logger.warning("No access_token — skipping MCP interest validation")
            _interests_cache[cache_key] = []
            return []
        try:
            validated = await mcp_client.search_interests(
                suggested_keywords, target_country, access_token
            )
            result = validated if isinstance(validated, list) else []
            if result:
                logger.info(
                    "Interests validated: country=%s, keywords=%s, found=%d",
                    target_country, suggested_keywords, len(result),
                )
            else:
                logger.warning(
                    "search_meta_interests returned empty for keywords=%s country=%s",
                    suggested_keywords, target_country,
                )
            _interests_cache[cache_key] = result
            return result
        except Exception as e:
            logger.warning("search_meta_interests failed: %s", e)
            _interests_cache[cache_key] = []
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
    _fallback_targeting_spec: dict | None = None  # cached for consistency across all drafts
    for draft in drafts_data:
        # Bug Fix #1: Sanitize ad copy — fix spacing, strip banned buzzwords
        headline = _sanitize_ad_text(draft.get("headline") or "")
        body_text = _sanitize_ad_text(draft.get("body_text", ""))

        # Bug Fix #2: Override CTA based on product type + ticket price
        ai_cta = draft.get("cta_type", "LEARN_MORE")
        # Hiring ads: skip CTA override — use the LLM's suggestion directly
        # (APPLY_NOW / LEARN_MORE / SIGN_UP — never SHOP_NOW)
        if hiring_data:
            resolved_cta = ai_cta if ai_cta in ("APPLY_NOW", "LEARN_MORE", "SIGN_UP", "CONTACT_US") else "APPLY_NOW"
        else:
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
        # Persist SAC detection on the draft so it shows in the UI badge and
        # ad_executor uses the cached result at publish time (no re-detection).
        _sac_for_record = locals().get("_sac_decision")
        if _sac_for_record and _sac_for_record.category:
            record["special_ad_category"] = _sac_for_record.category
            record["special_ad_category_confidence"] = round(_sac_for_record.confidence, 2)
            record["special_ad_category_reasoning"] = _sac_for_record.reasoning[:500]
        if workspace_id:
            record["workspace_id"] = workspace_id
        if ad_account and draft.get("draft_type", "paid") == "paid":
            record["ad_account_id"] = ad_account["id"]
        # Hiring ad fields
        if hiring_data:
            record["is_employment_ad"] = True
            record["hiring_data"] = json.dumps(hiring_data)
            record["target_country"] = hiring_data.get("target_country", target_country)
            if job_id:
                record["job_id"] = job_id

        if destination_type:
            record["destination_type"] = destination_type
        if whatsapp_number and destination_type in ("WHATSAPP", "MESSAGING"):
            record["whatsapp_number"] = whatsapp_number
        if selected_messaging_apps and destination_type == "MESSAGING":
            record["selected_messaging_apps"] = selected_messaging_apps
        if call_phone_number and destination_type == "PHONE_CALL":
            record["call_phone_number"] = call_phone_number

        # Product-specific fields
        if focused_product:
            record["product_id"] = focused_product["id"]
            if focused_product.get("image_url"):
                record["image_url"] = focused_product["image_url"]
            # Pixel only for WEBSITE destination — messaging/call/form destinations don't use pixel
            _NO_PIXEL_DESTINATIONS = {"WHATSAPP", "INSTAGRAM_DM", "INSTANT_FORM", "MESSAGING", "PHONE_CALL"}
            if focused_product.get("pixel_id") and destination_type not in _NO_PIXEL_DESTINATIONS:
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

        # Geo-cultural targeting: use pre-validated interests if available,
        # otherwise fall back to validating AI's suggestions
        if record["draft_type"] == "paid":
            if pre_validated_interests:
                # All drafts get the same interests — A/B testing should only vary copy, not targeting
                _spec_payload = {
                    "target_country": target_country,
                    "validated_interests": pre_validated_interests,
                    "suggested_keywords": [i["name"] for i in pre_validated_interests],
                }
                if advantage_plus_expanded:
                    _spec_payload["advantage_plus_expanded"] = True
                record["targeting_spec"] = json.dumps(_spec_payload)
                logger.info("Draft %d: assigned %d interests: %s",
                            len(created), len(pre_validated_interests), [i["name"] for i in pre_validated_interests])
            else:
                # Fallback: validate AI's suggested keywords once, reuse for all drafts
                if _fallback_targeting_spec is None:
                    suggested = suggested_interests
                    logger.info("Validating %d AI-suggested interests against Meta API: %s", len(suggested), suggested)
                    validated_interests = await _validate_interests(suggested)
                    logger.info("Meta API validated %d/%d interests: %s", len(validated_interests), len(suggested), [i.get("name") for i in validated_interests])
                    if validated_interests:
                        # If we validated fewer than suggested, supplement with unvalidated ones
                        validated_names = {i["name"].lower() for i in validated_interests}
                        combined = list(validated_interests)
                        for kw in suggested:
                            if kw.lower() not in validated_names and len(combined) < 5:
                                combined.append({"id": f"ai_{kw}", "name": kw})
                        _fallback_targeting_spec = {
                            "target_country": target_country,
                            "validated_interests": combined,
                            "suggested_keywords": suggested,
                        }
                        # Sparse fallback pool also gets Advantage+ expansion
                        _real_validated = [i for i in combined if not str(i.get("id", "")).startswith("ai_")]
                        if len(_real_validated) < 3 or advantage_plus_expanded:
                            _fallback_targeting_spec["advantage_plus_expanded"] = True
                        if len(combined) > len(validated_interests):
                            logger.info("Supplemented %d validated interests with %d unvalidated: %s",
                                        len(validated_interests), len(combined) - len(validated_interests),
                                        [i["name"] for i in combined])
                    elif suggested:
                        _fallback_targeting_spec = {
                            "target_country": target_country,
                            "validated_interests": [{"id": f"ai_{i}", "name": kw} for i, kw in enumerate(suggested[:5])],
                            "suggested_keywords": suggested,
                            "validation_status": "fallback",
                        }
                        logger.info("Using AI fallback interests for all drafts: %s", suggested[:5])
                    else:
                        _fallback_targeting_spec = {
                            "target_country": target_country,
                            "validated_interests": [],
                            "suggested_keywords": [],
                        }
                record["targeting_spec"] = json.dumps(_fallback_targeting_spec)

        resp = httpx.post(
            _postgrest_url("content_drafts"),
            headers=_postgrest_headers(),
            json=record,
            timeout=10,
        )
        if resp.status_code in (200, 201) and resp.json():
            created.append(resp.json()[0])

    return created
