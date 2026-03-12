"""
Targeting Engine — Dynamic targeting pipeline.

Validates interests and resolves geo-locations via the MCP server (no direct
Meta API calls). Uses LLM-powered keyword generation for senior-level targeting.
"""
import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from ..core.config import get_settings
from .mcp_client import mcp_client, MCPError

logger = logging.getLogger(__name__)

_settings = get_settings()
_openai = AsyncOpenAI(api_key=_settings.OPENAI_API_KEY)


# ── Keyword Extraction (fallback) ────────────────────────────────────────────

def _extract_keywords(text: str) -> list[str]:
    """Extract candidate keywords from text (simple NLP fallback)."""
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "and", "but", "or", "nor", "not", "so", "yet",
        "both", "either", "neither", "each", "every", "all", "any", "few",
        "more", "most", "other", "some", "such", "no", "only", "own", "same",
        "than", "too", "very", "just", "it", "its", "this", "that", "these",
        "those", "i", "me", "my", "we", "our", "you", "your", "he", "she",
        "they", "them", "their", "what", "which", "who", "whom", "how",
        "about", "up", "out", "if", "then", "also", "over", "new",
    }
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    seen: set[str] = set()
    keywords: list[str] = []
    for w in words:
        if w not in stop_words and w not in seen:
            seen.add(w)
            keywords.append(w)
    return keywords


# ── LLM-Powered Keyword Generation ───────────────────────────────────────────

async def _generate_llm_keywords(
    product_description: str,
    product_type: str = "",
    industry_niche: str = "",
    business_description: str = "",
    target_country: str = "US",
) -> dict:
    """
    Use LLM to generate Meta Ad interest keywords like a senior media buyer.
    Returns {"keywords": [...], "age_min": int, "age_max": int, "persona_reasoning": str}
    """
    # Country-specific cultural context
    COUNTRY_NAMES = {
        "PK": "Pakistan", "US": "United States", "GB": "United Kingdom",
        "AE": "UAE", "SA": "Saudi Arabia", "IN": "India", "CA": "Canada",
        "AU": "Australia", "DE": "Germany", "FR": "France", "TR": "Turkey",
        "MY": "Malaysia", "NG": "Nigeria", "KE": "Kenya", "BD": "Bangladesh",
    }
    country_name = COUNTRY_NAMES.get(target_country, target_country)
    is_islamic = target_country in {"PK", "SA", "AE", "BD", "MY", "TR"}

    cultural_rules = f"""
GEO-CULTURAL TARGETING — TARGET MARKET: {country_name} ({target_country})
You are an expert LOCAL Ads media buyer for {country_name}. Your interest keywords MUST reflect
what REAL people in {country_name} actually search for, buy, and engage with on social media.

DO NOT use generic Western/US-centric brand interests (like "Whole Foods", "Trader Joe's",
"Target (store)", "Walmart") UNLESS the target country is the US.

Instead, suggest culturally relevant interests that match local purchasing behavior in {country_name}.
Examples by region:
- Pakistan: "Desi food", "Natural skin care", "Daraz (e-commerce)", "Homemade food"
- Saudi Arabia: "Organic products", "مواد غذائية صحية", "Online shopping Saudi"
- India: "Ayurveda", "Natural remedies", "Flipkart", "Healthy cooking"
- UK: "Organic food UK", "Holland & Barrett", "Health food"
"""
    if is_islamic:
        cultural_rules += """
ISLAMIC MARKET RULES (MANDATORY):
- NEVER suggest: Alcohol, Wine, Beer, Pork, Bacon, Ham, Gambling, Casino, Betting
- Stick to family-friendly, halal-appropriate categories only.
- Prefer health/wellness, natural/organic, family, and food categories.
"""

    try:
        resp = await _openai.chat.completions.create(
            model=_settings.CHEAP_FAST_MODEL,
            messages=[
                {"role": "system", "content": f"""You are a senior Meta Ads media buyer with 10+ years of experience.

{cultural_rules}

Your job: Read the PRODUCT DESCRIPTION below, determine what it actually is, then generate EXACT interest keywords from Meta's ad targeting system that match THAT SPECIFIC product FOR THE {country_name} MARKET.

STEP 1 — ANALYZE THE PRODUCT FIRST:
- Read the product description carefully. What is this product? Food? Software? Clothing? Service?
- Your keywords MUST match the product's actual category. Nothing else matters.
- IGNORE the "Business" field — it describes the seller, NOT the product being advertised.

2026 META TARGETING STRATEGY — BROAD & HIGH-LIQUIDITY:
Meta's Advantage+ algorithm performs best with BROAD, high-liquidity audiences.
Hyper-niche micro-targeting is DEAD. Stacking 10+ narrow interests KILLS delivery.
Your job is to give the algorithm ROOM TO EXPLORE by selecting broad signal interests.

STEP 2 — GENERATE 3-5 BROAD, HIGH-INTENT INTERESTS for {country_name}:
- Output 3-5 keywords. NEVER more than 5. Fewer broad signals is BETTER than many narrow ones.
- Each interest MUST have millions of audience members — think CATEGORY level, not sub-niche.
- DO NOT search for the product name. Search for the PRODUCT CATEGORY and BUYER INTENT.
- Every keyword should be a broad behavioral or lifestyle signal, not a micro-niche.

LIQUIDITY PRINCIPLE (2026 — the #1 rule):
- GOOD: "Healthy eating", "Organic food", "Online shopping" (millions of people, high liquidity)
- BAD: "Raw Manuka Honey Enthusiasts", "Artisan Beekeeping" (too narrow, kills delivery)
- Pick interests that describe the BUYER'S LIFESTYLE, not the exact product specification.
- 3 broad interests with millions of audience > 10 narrow ones with thousands each.

CATEGORY-BASED EXAMPLES (broad, not niche):
- FOOD products: "Healthy eating", "Organic food", "Cooking" (NOT "Cinnamon lovers")
- B2B/TECH: "Entrepreneurship", "Small business", "Digital marketing" (NOT "CRM software users")
- FASHION: "Online shopping", "Fashion", "Clothing" (NOT "Vintage denim collectors")
- FITNESS: "Health & wellness", "Fitness", "Gym" (NOT "Kettlebell training")

NEGATIVE MATCH BLOCKLIST (automatic fail if any appear):
- NEVER output keywords that are: brands, movies, musicals, TV shows, alcoholic beverages, songs, or celebrities.
- NEVER output the product's ingredient as a standalone keyword.
- NEVER output hyper-specific sub-niches with tiny audiences.

GEOGRAPHIC HALLUCINATION BLOCKER:
- NEVER output city names or country names as interests. Zero exceptions.

OTHER RULES:
- Determine the ideal age range for this product's buyers in {country_name}
- Choose objective: TRAFFIC (website), ENGAGEMENT (WhatsApp/messages), SALES (pixel), LEADS (forms)

Return ONLY valid JSON, no markdown."""},
                {"role": "user", "content": f"""PRODUCT DESCRIPTION: {product_description}
PRODUCT TYPE: {product_type or 'unknown'}
PRODUCT NICHE/TAGS: {industry_niche or 'general'}
SELLER CONTEXT: {business_description[:200] if business_description else 'N/A'}
TARGET COUNTRY: {country_name} ({target_country})

IMPORTANT: Your keywords must be about the PRODUCT above, not the seller's business.
IMPORTANT: Keywords must be culturally relevant to {country_name} consumers.

Return JSON:
{{
  "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
  "age_min": 25,
  "age_max": 45,
  "objective_hint": "TRAFFIC|ENGAGEMENT|SALES|LEADS",
  "persona_reasoning": "Brief explanation — start with what the product IS, then why you chose these interests for {country_name}"
}}"""},
            ],
            max_completion_tokens=500,
        )
        text = resp.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        keywords = result.get("keywords", [])
        if not keywords:
            raise ValueError("No keywords returned")
        logger.info("LLM keywords for '%s': %s (age %d-%d)",
                     product_description[:50], keywords,
                     result.get("age_min", 18), result.get("age_max", 65))
        return result
    except Exception as e:
        logger.warning("LLM keyword generation failed: %s — falling back to NLP", e)
        return {
            "keywords": _extract_keywords(product_description),
            "age_min": 18,
            "age_max": 65,
            "persona_reasoning": "",
        }


async def _research_trends_via_mcp(
    product_description: str,
    industry_niche: str,
    country: str,
) -> list[str]:
    """
    Research real advertising trends for the niche via the MCP server's
    research_niche_trends tool (Tavily-backed web search).
    Falls back to generic keywords if MCP call fails.
    """
    niche = industry_niche or product_description[:60]
    try:
        result = await mcp_client.call_tool(
            "research_niche_trends",
            {"niche": niche, "country": country},
            user_access_token="",  # not needed for Tavily
        )
        # research_niche_trends returns a dict directly (JSON tool)
        trends = result.get("trends", [])
        audience = result.get("audience_insights", [])
        return trends + audience if (trends or audience) else _fallback_trends(product_description)
    except MCPError:
        logger.warning("research_niche_trends MCP call failed, using fallback")
        return _fallback_trends(product_description)


def _fallback_trends(product_description: str) -> list[str]:
    """Generic fallback trends when web research is unavailable."""
    return [
        "health and wellness products",
        "natural organic supplements",
        "online shopping trends",
    ]


# ── MCP-backed Validation ────────────────────────────────────────────────────

def _parse_mcp_json(result: dict) -> Any:
    """Extract and parse JSON from MCP tool result (FastMCP content format)."""
    content = result.get("content", [])
    if content and isinstance(content, list):
        text = content[0].get("text", "[]")
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
    return result


async def _validate_interests_via_mcp(
    keywords: list[str],
    access_token: str,
) -> list[dict]:
    """Validate keywords against Meta's interest taxonomy via the MCP server."""
    try:
        result = await mcp_client.validate_interests(keywords, access_token)
        parsed = _parse_mcp_json(result)
        return parsed if isinstance(parsed, list) else []
    except MCPError as e:
        logger.warning("MCP validate_meta_interests failed: %s", e)
        return []


async def _search_interests_via_mcp(
    keywords: list[str],
    target_country: str,
    access_token: str,
) -> list[dict]:
    """Search culturally relevant Meta interests for a target country via the MCP server."""
    try:
        result = await mcp_client.search_interests(keywords, target_country, access_token)
        return result if isinstance(result, list) else []
    except MCPError as e:
        logger.warning("MCP search_meta_interests failed: %s — falling back to validate", e)
        # Fallback to the old validate_interests if search fails
        return await _validate_interests_via_mcp(keywords, access_token)


async def _resolve_geo_via_mcp(
    cities: list[str],
    country_code: str,
    access_token: str,
) -> dict:
    """Resolve city names to Meta geo-location keys via the MCP server."""
    try:
        result = await mcp_client.resolve_geo(cities, country_code, access_token)
        parsed = _parse_mcp_json(result)
        return parsed if isinstance(parsed, dict) else {"countries": [country_code]}
    except MCPError as e:
        logger.warning("MCP resolve_geo_locations failed: %s", e)
        return {"countries": [country_code]}


# ── Campaign Strategy Generation ─────────────────────────────────────────────

async def generate_campaign_strategy(
    client_profile: dict,
    access_token: str,
    differentiation_strategy: str | None = None,
) -> dict:
    """
    Build a full targeting strategy from client profile.

    Autonomous mode: provide just product_description + target_country and
    the engine will research the audience, trends, and targeting automatically.

    client_profile: {
        "product_description": str,
        "target_cities": list[str],       # optional — auto-resolved if empty
        "target_country": str,            # default "PK"
        "industry_niche": str,            # optional — improves research quality
    }
    differentiation_strategy: Optional strategy text from competitor analysis
        that influences keyword selection.
    """
    product_desc = client_profile.get("product_description", "")
    target_cities = client_profile.get("target_cities", [])
    target_country = client_profile.get("target_country", "PK")
    industry_niche = client_profile.get("industry_niche", "")
    product_type = client_profile.get("product_type", "")
    business_description = client_profile.get("business_description", "")

    # Step A: LLM-powered keyword generation (senior media buyer logic, geo-cultural)
    llm_result = await _generate_llm_keywords(
        product_desc, product_type, industry_niche, business_description,
        target_country=target_country,
    )
    all_keywords = llm_result.get("keywords", _extract_keywords(product_desc))[:5]
    age_min = llm_result.get("age_min", 18)
    age_max = llm_result.get("age_max", 65)
    persona_reasoning = llm_result.get("persona_reasoning", "")

    # Step B: research trends via MCP (for context, not keyword extraction)
    trends = await _research_trends_via_mcp(product_desc, industry_niche, target_country)

    # Step C: validate LLM keywords against Meta API via geo-cultural search (via MCP)
    validated = await _search_interests_via_mcp(all_keywords, target_country, access_token)
    # Pick top 5 by audience size (seed interests for Advantage+ expansion)
    top_interests = sorted(validated, key=lambda x: x.get("audience_size", 0), reverse=True)[:5]

    # Step D: build geo_locations (via MCP)
    if target_cities:
        geo_locations = await _resolve_geo_via_mcp(target_cities, target_country, access_token)
    else:
        geo_locations = {"countries": [target_country]}

    return {
        "interests": top_interests,
        "geo_locations": geo_locations,
        "trends": trends,
        "keywords_used": all_keywords,
        "autonomous": not bool(target_cities),
        "age_min": age_min,
        "age_max": age_max,
        "objective_hint": llm_result.get("objective_hint", "TRAFFIC"),
        "persona_reasoning": persona_reasoning,
        "custom_audiences": client_profile.get("custom_audiences", []),
    }


# ── Adset Payload Builder ────────────────────────────────────────────────────

def build_adset_payload(
    strategy: dict,
    daily_budget: float,
    campaign_id: str,
    campaign_name: str = "AI Campaign",
    bid_amount: int = 0,
) -> dict:
    """
    Build a complete adset params dict for Meta API.

    Uses OFFSITE_CONVERSIONS optimization (for OUTCOME_SALES campaigns),
    dynamic geo from strategy, and validated interest IDs.
    When bid_amount > 0, uses COST_CAP bid strategy (Profit-Protection).
    """
    targeting: dict[str, Any] = {
        "age_min": strategy.get("age_min", 18),
        "age_max": strategy.get("age_max", 65),
        "geo_locations": strategy["geo_locations"],
    }

    if strategy.get("interests"):
        targeting["flexible_spec"] = [
            {"interests": [{"id": i["id"], "name": i["name"]} for i in strategy["interests"]]}
        ]

    payload = {
        "name": f"{campaign_name} — Ad Set",
        "campaign_id": campaign_id,
        "daily_budget": int(daily_budget * 100),  # dollars → cents
        "billing_event": "IMPRESSIONS",
        "optimization_goal": "OFFSITE_CONVERSIONS",
        "targeting": targeting,
        "status": "PAUSED",
    }
    # Lock bid_strategy + bid_amount together
    if bid_amount > 0:
        payload["bid_strategy"] = "COST_CAP"
        payload["bid_amount"] = bid_amount
    else:
        payload["bid_strategy"] = "LOWEST_COST_WITHOUT_CAP"
        payload.pop("bid_amount", None)
    return payload
