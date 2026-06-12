"""
Targeting Engine — Dynamic targeting pipeline.

Validates interests and resolves geo-locations via the MCP server (no direct
Meta API calls). Uses Hybrid Targeting: LLM generates search terms, Meta API
grounds them into real interests.
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


# ── Hybrid Targeting: LLM Search Terms → Meta API Grounding ──────────────────

_SEARCH_TERMS_SYSTEM_PROMPT = """You are an Elite Meta Ads Media Buyer. Analyze the product/service and identify the ultimate decision-maker (the person with the credit card).

Your job is NOT to pick final Meta interests. Your job is to output SEARCH TERMS that we will use to search Meta's interest database. Think of these as Google-style search queries to find the buyer's world.

Output strict JSON:
{
  "step_1_buyer_type": "B2B or B2C",
  "step_2_buyer_identity": "Describe WHO the buyer is in THIS SPECIFIC COUNTRY — their daily life, habits, profession, lifestyle, local culture. Be specific to the target market.",
  "step_3_forbidden_terms": ["term1", "term2", "term3"],
  "step_4_search_terms": ["search1", "search2", ... up to 20 terms],
  "age_min": 25,
  "age_max": 55
}

RULES:

step_1_buyer_type: Decide if this is B2B (buyer is a business) or B2C (buyer is an individual consumer).

step_3_forbidden_terms: List ALL technical/industry terms of the product itself as an array. These will be used to filter OUT irrelevant results from Meta's API. Be thorough. (e.g., if selling SEO services: ["SEO", "digital marketing", "advertising", "analytics", "content marketing"])

step_4_search_terms: Output 15-20 search terms. Mix BROAD (high volume) and NICHE (high intent) queries.

  CRITICAL: Keep each search term SHORT (1-3 words max). Meta's interest search works best with simple terms, not long phrases.
  BAD: "small business owner", "ecommerce business management", "shopify store owner"
  GOOD: "small business", "ecommerce", "shopify", "franchise", "real estate"

  NICHE-FIRST RULE (CRITICAL — READ THIS FIRST):
  Always prioritize the PRODUCT'S CORE BUYER INTENT first, then filter through local culture second.
  DO NOT fall into "Geo-Stereotyping" — targeting generic interests like "smartphones", "online shopping",
  or "technology" just because it's an emerging market. If the product is a high-tech financial tool,
  target investors, specific local stock exchanges, crypto behaviors, and trading platforms in that region.
  Example: AI Trading Bot for Pakistan → "Pakistan Stock Exchange", "cryptocurrency", "forex trading",
  "Binance", "day trading" — NOT "smartphones", "online shopping", "technology".

  LATERAL TARGETING (PRESERVE THIS):
  Continue to use lateral targeting where appropriate — targeting the buyer's LIFESTYLE, not the product category.
  e.g., "healthy eating recipes" for honey, "Startup Weekend" for B2B SaaS.
  But ensure the lateral interest always represents a HIGH-INTENT buyer for the SPECIFIC product.
  "Cooking" is lateral but high-intent for honey. "Smartphones" is NOT lateral — it's just generic.

  GEO-CULTURAL RULE:
  Your search terms MUST reflect the culture, brands, sports, and lifestyle of the TARGET COUNTRY.
  - If targeting Germany: suggest "DACH startups", "Mittelstand", "Otto", NOT "Walmart", "Target"
  - If targeting Pakistan: suggest "Daraz", "JazzCash", "cricket", NOT "baseball", "Best Buy"
  - If targeting Ireland: suggest "GAA", "Revolut", "pub culture", NOT "NFL", "Chick-fil-A"
  - If targeting USA: suggest "Shopify", "Y Combinator", "NFL", NOT "Flipkart", "cricket"
  Think LOCAL. What brands, sports, media, and platforms does this buyer use in THEIR country?

  Include a mix of:
  - 7-10 NICHE terms (specific tools, platforms, communities, behaviors the buyer uses — HIGHEST PRIORITY)
  - 3-5 BROAD terms (large audience, buyer's general world)
  - 3-5 CULTURAL terms (local brands, sports, lifestyle unique to target country)

  IF B2B: Search for the buyer's profession, job title, business tools, industry, LOCAL business platforms.
    Examples: "small business", "real estate", "franchise", "shopify", "management", "venture capital", "restaurant"

  IF B2C: Search for the buyer's lifestyle, hobbies, shopping habits, personal interests, LOCAL brands.
    DO NOT search for business terms like "entrepreneurship", "management", "leadership", "startup".
    Examples: "organic food", "fitness", "cooking", "yoga", "skincare", "hiking", "home decor", "pet care", "healthy eating", "running"
    Think: what does this person do on weekends? What are their hobbies? What local brands do they buy from?
"""


COUNTRY_NAMES_MAP = {
    "AF": "Afghanistan", "AL": "Albania", "DZ": "Algeria", "AO": "Angola",
    "AR": "Argentina", "AM": "Armenia", "AU": "Australia", "AT": "Austria",
    "AZ": "Azerbaijan", "BH": "Bahrain", "BD": "Bangladesh", "BY": "Belarus",
    "BE": "Belgium", "BJ": "Benin", "BO": "Bolivia", "BA": "Bosnia & Herzegovina",
    "BW": "Botswana", "BR": "Brazil", "BN": "Brunei", "BG": "Bulgaria",
    "BF": "Burkina Faso", "KH": "Cambodia", "CM": "Cameroon", "CA": "Canada",
    "CL": "Chile", "CN": "China", "CO": "Colombia", "CD": "Congo (DRC)",
    "CR": "Costa Rica", "CI": "Côte d'Ivoire", "HR": "Croatia", "CY": "Cyprus",
    "CZ": "Czech Republic", "DK": "Denmark", "DO": "Dominican Republic",
    "EC": "Ecuador", "EG": "Egypt", "SV": "El Salvador", "EE": "Estonia",
    "ET": "Ethiopia", "FI": "Finland", "FR": "France", "GA": "Gabon",
    "GE": "Georgia", "DE": "Germany", "GH": "Ghana", "GR": "Greece",
    "GT": "Guatemala", "GN": "Guinea", "HN": "Honduras", "HK": "Hong Kong",
    "HU": "Hungary", "IS": "Iceland", "IN": "India", "ID": "Indonesia",
    "IQ": "Iraq", "IE": "Ireland", "IL": "Israel", "IT": "Italy",
    "JM": "Jamaica", "JP": "Japan", "JO": "Jordan", "KZ": "Kazakhstan",
    "KE": "Kenya", "KW": "Kuwait", "KG": "Kyrgyzstan", "LA": "Laos",
    "LV": "Latvia", "LB": "Lebanon", "LY": "Libya", "LT": "Lithuania",
    "LU": "Luxembourg", "MG": "Madagascar", "MW": "Malawi", "MY": "Malaysia",
    "MV": "Maldives", "ML": "Mali", "MT": "Malta", "MU": "Mauritius",
    "MX": "Mexico", "MD": "Moldova", "MN": "Mongolia", "ME": "Montenegro",
    "MA": "Morocco", "MZ": "Mozambique", "MM": "Myanmar", "NA": "Namibia",
    "NP": "Nepal", "NL": "Netherlands", "NZ": "New Zealand", "NI": "Nicaragua",
    "NE": "Niger", "NG": "Nigeria", "MK": "North Macedonia", "NO": "Norway",
    "OM": "Oman", "PK": "Pakistan", "PS": "Palestine", "PA": "Panama",
    "PY": "Paraguay", "PE": "Peru", "PH": "Philippines", "PL": "Poland",
    "PT": "Portugal", "PR": "Puerto Rico", "QA": "Qatar", "RO": "Romania",
    "RU": "Russia", "RW": "Rwanda", "SA": "Saudi Arabia", "SN": "Senegal",
    "RS": "Serbia", "SG": "Singapore", "SK": "Slovakia", "SI": "Slovenia",
    "SO": "Somalia", "ZA": "South Africa", "KR": "South Korea", "ES": "Spain",
    "LK": "Sri Lanka", "SD": "Sudan", "SE": "Sweden", "CH": "Switzerland",
    "TW": "Taiwan", "TJ": "Tajikistan", "TZ": "Tanzania", "TH": "Thailand",
    "TN": "Tunisia", "TR": "Turkey", "TM": "Turkmenistan", "UG": "Uganda",
    "UA": "Ukraine", "AE": "UAE", "GB": "United Kingdom", "US": "United States",
    "UY": "Uruguay", "UZ": "Uzbekistan", "VE": "Venezuela", "VN": "Vietnam",
    "YE": "Yemen", "ZM": "Zambia", "ZW": "Zimbabwe",
}


async def _generate_search_terms(
    product_description: str,
    product_type: str = "",
    industry_niche: str = "",
    business_description: str = "",
    target_country: str = "US",
) -> dict:
    """
    Hybrid Step 1: LLM analyzes the buyer persona and outputs broad SEARCH TERMS
    (not final Meta interests). These are then searched against Meta's real interest
    API for grounding. Returns {"search_terms": [...], "forbidden_terms": [...], ...}
    """
    country_name = COUNTRY_NAMES_MAP.get(target_country, target_country)
    is_islamic = target_country in {"PK", "SA", "AE", "BD", "MY", "TR"}

    islamic_rule = ""
    if is_islamic:
        islamic_rule = "\nISLAMIC MARKET: NEVER suggest alcohol, pork, gambling search terms. Family-friendly only."

    system_prompt = _SEARCH_TERMS_SYSTEM_PROMPT + islamic_rule + f"\nTarget market: {country_name}."

    user_prompt = f"""Product: {product_description}
Type: {product_type or 'unknown'}
Country: {country_name}
Business: {business_description or 'N/A'}

First decide B2B or B2C. Then describe the buyer AS THEY EXIST IN {country_name} — their local habits, local brands, local culture. Then list forbidden industry terms. Then output 15-20 search terms that describe the buyer's world in {country_name} — NOT the product's industry."""

    try:
        resp = await _openai.chat.completions.create(
            model=_settings.CREATIVE_WRITING_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=800,
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content.strip()
        logger.info("Hybrid targeting raw: %s", text[:500])
        result = json.loads(text)

        search_terms = result.get("step_4_search_terms") or result.get("search_terms") or []
        forbidden_raw = result.get("step_3_forbidden_terms") or []
        # Normalize forbidden terms to a flat list of lowercase strings
        if isinstance(forbidden_raw, str):
            forbidden_terms = [t.strip().lower() for t in forbidden_raw.split(",") if t.strip()]
        else:
            forbidden_terms = [str(t).strip().lower() for t in forbidden_raw if str(t).strip()]

        import unicodedata
        cleaned_terms = []
        for t in search_terms[:20]:
            t = unicodedata.normalize("NFKC", str(t).strip()).replace("\u2011", "-").replace("\u2013", "-")
            if len(t) >= 2:
                cleaned_terms.append(t)

        if not cleaned_terms:
            cleaned_terms = _extract_keywords(product_description)[:5]
            logger.warning("LLM returned no search terms — using NLP fallback")

        out = {
            "search_terms": cleaned_terms,
            "forbidden_terms": forbidden_terms,
            "age_min": result.get("age_min", 25),
            "age_max": result.get("age_max", 55),
            "persona_reasoning": result.get("step_2_buyer_identity", ""),
            "buyer_type": result.get("step_1_buyer_type", "unknown"),
        }
        logger.info("Hybrid search terms for '%s': %s (forbidden: %s, type: %s)",
                     product_description[:50], out["search_terms"], out["forbidden_terms"][:5],
                     out["buyer_type"])
        return out
    except Exception as e:
        logger.warning("LLM search term generation failed: %s — falling back to NLP", e)
        return {
            "search_terms": _extract_keywords(product_description)[:5],
            "forbidden_terms": [],
            "age_min": 18,
            "age_max": 65,
            "persona_reasoning": "",
            "buyer_type": "unknown",
        }


def _filter_forbidden(interests: list[dict], forbidden_terms: list[str]) -> list[dict]:
    """Remove interests whose name matches any forbidden industry term.

    Safety: if the filter would remove >70% of interests, the product IS in that
    niche (e.g., a trading product where 'trading' is forbidden). In that case,
    skip the filter entirely and let the sniper LLM handle relevance.
    """
    if not forbidden_terms:
        return interests
    filtered = []
    removed = []
    for interest in interests:
        name_lower = interest.get("name", "").lower()
        # Strip category suffix like "(business and finance)" for matching
        base_name = name_lower.split("(")[0].strip()
        is_forbidden = any(ft in base_name for ft in forbidden_terms if len(ft) > 2)
        if is_forbidden:
            removed.append(interest.get("name"))
            continue
        filtered.append(interest)
    # Safety valve: if we'd remove >70% of interests, the forbidden terms are too aggressive
    # for this niche — pass everything through and let sniper LLM decide
    if len(filtered) < len(interests) * 0.3 and len(interests) >= 5:
        logger.info("Forbidden filter too aggressive (would remove %d/%d) — skipping, letting sniper decide",
                     len(removed), len(interests))
        return interests
    if removed:
        logger.info("Forbidden-filter removed %d interests: %s", len(removed), removed[:10])
    return filtered


def _filter_sac_blocklist(
    interests: list[dict], sac_categories: list[str] | None
) -> list[dict]:
    """Drop interests Meta has previously rejected under any of the given SAC
    categories. Reads the persistent ``sac_blocked_interests`` table populated
    by the post-publish reconciler.

    Generic — no category-specific or business-specific logic. The blocklist
    starts empty and grows as the platform learns from real Meta rejections.
    No-ops when ``sac_categories`` is empty.
    """
    if not sac_categories or not interests:
        return interests
    try:
        # Local import: avoids a circular at module-load time and keeps the
        # cost zero for non-SAC code paths.
        from .sac_reconciler import get_blocked_interest_ids
        blocked = get_blocked_interest_ids(sac_categories)
    except Exception as e:
        logger.warning("_filter_sac_blocklist: blocklist read failed: %s", e)
        return interests
    if not blocked:
        return interests
    out: list[dict] = []
    removed: list[str] = []
    for it in interests:
        if str(it.get("id") or "") in blocked:
            removed.append(it.get("name") or it.get("id"))
        else:
            out.append(it)
    if removed:
        logger.info(
            "SAC blocklist filtered %d interest(s) under %s: %s",
            len(removed), sac_categories, removed[:10],
        )
    return out


async def _sniper_selection(
    interests: list[dict],
    product_description: str,
    business_description: str = "",
    country_name: str = "United States",
    forbidden_terms: list[str] | None = None,
) -> list[dict]:
    """
    Hybrid 2.0 Sniper Selection — Elite LLM picks the best 5 interests
    from the full Meta API pool, prioritizing buyer intent over audience size.
    Uses the ELITE_REASONING_MODEL for maximum accuracy.
    """
    if not interests:
        return interests
    if len(interests) <= 5:
        return interests

    # Build the interest list with sizes for the LLM
    interest_options = []
    for i in interests:
        name = i.get("name", "")
        size = i.get("audience_size", 0)
        size_label = f"{size / 1_000_000:.1f}M" if size >= 1_000_000 else f"{size / 1_000:.0f}K" if size >= 1000 else str(size)
        interest_options.append(f"- {name} ({size_label})")
    options_text = "\n".join(interest_options)

    context = product_description
    if business_description:
        context += f"\nBusiness: {business_description}"

    forbidden_text = ", ".join(forbidden_terms[:15]) if forbidden_terms else "none"

    try:
        resp = await _openai.chat.completions.create(
            model=_settings.ELITE_REASONING_MODEL,
            messages=[
                {"role": "system", "content": "You are a Master Media Buyer selecting Meta ad targeting interests. Output strict JSON only."},
                {"role": "user", "content": f"""Product/Service: {context}
Target Market: {country_name}
Forbidden industry terms: {forbidden_text}

Here are ALL valid Meta interests from the API with their audience sizes:
{options_text}

Select EXACTLY 5 interests. Output JSON:
{{"selected": ["Interest Name 1", "Interest Name 2", "Interest Name 3", "Interest Name 4", "Interest Name 5"], "reasoning": "brief explanation"}}

RULES:
A) Prioritize HIGH BUYER INTENT and DEEP RELEVANCE over raw audience size. A niche 500K interest that perfectly describes the buyer is better than a generic 200M interest.
B) GEO-RELEVANCE FILTER: Only pick interests that are relevant IN {country_name}. Reject foreign brands, companies, or organizations that don't operate or have recognition in {country_name}. For example, if targeting Pakistan, reject "The ADT Corporation" (US-only company) or "Allied Universal" (US security firm). Only pick brands/companies if they are actually known and relevant to people in {country_name}.
C) NEVER select an interest that matches the forbidden product industry terms: [{forbidden_text}]. You are targeting the BUYER, not people in the product's own industry.
D) Mix broad reach (1-2 large interests) with sniper precision (3-4 niche high-intent interests).
E) Every selected interest must pass this test: "Would someone with this interest be a likely BUYER of this product?" If no, don't pick it.
F) ANTI-GENERIC FILTER: Actively reject overly broad interests like "Technology", "Smartphones", "Online shopping", "Business", "Science" if more specific niche interests are available in the pool. For example, if both "Technology" (2B) and "Cryptocurrency exchange" (15M) are in the pool for a crypto trading product, ALWAYS pick "Cryptocurrency exchange". Generic interests waste budget on unqualified impressions.
G) NICHE-FIRST: The product's core category MUST be represented. If it's a trading platform, at least 2-3 selected interests must be directly related to trading/investing/finance. Do NOT let geo-cultural interests completely replace niche intent."""},
            ],
            max_completion_tokens=400,
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content.strip())
        selected_names = result.get("selected", [])
        reasoning = result.get("reasoning", "")
        logger.info("Sniper selection reasoning: %s", reasoning)

        # Map selected names back to full interest objects
        name_map = {i.get("name", ""): i for i in interests}
        selected = [name_map[n] for n in selected_names if n in name_map]

        if not selected:
            logger.warning("Sniper selection returned no valid matches — falling back to top 5 by size")
            selected = sorted(interests, key=lambda x: x.get("audience_size", 0), reverse=True)[:5]

        logger.info("Sniper selected %d interests: %s",
                     len(selected), [(s.get("name"), s.get("audience_size", 0)) for s in selected])
        return selected
    except Exception as e:
        logger.warning("Sniper selection failed: %s — falling back to top 5 by size", e)
        return sorted(interests, key=lambda x: x.get("audience_size", 0), reverse=True)[:5]


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
        print(f"[TARGETING] Sending to MCP search: {keywords}", flush=True)
        result = await mcp_client.search_interests(keywords, target_country, access_token)
        print(f"[TARGETING] MCP returned: {result}", flush=True)
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
    raw_country = client_profile.get("target_country", "PK")
    industry_niche = client_profile.get("industry_niche", "")
    product_type = client_profile.get("product_type", "")
    business_description = client_profile.get("business_description", "")

    # Parse multi-country: "PK,US,AE" or "WORLDWIDE"
    is_worldwide = raw_country == "WORLDWIDE"
    if is_worldwide:
        country_codes = []  # Meta targets all countries when geo_locations is omitted
        target_country = "US"  # Fallback for API calls that need a single code
    elif "," in raw_country:
        country_codes = [c.strip() for c in raw_country.split(",") if c.strip()]
        target_country = country_codes[0]  # Primary country for single-country API calls
    else:
        country_codes = [raw_country]
        target_country = raw_country

    # Build a label string for LLM prompts (all countries, not just the first)
    if is_worldwide:
        llm_country_label = "Worldwide (global audience)"
    elif len(country_codes) > 1:
        llm_country_label = ", ".join(COUNTRY_NAMES_MAP.get(c, c) for c in country_codes)
    else:
        llm_country_label = target_country

    # Step A: LLM generates search terms + forbidden terms (Hybrid Step 1)
    llm_result = await _generate_search_terms(
        product_desc, product_type, industry_niche, business_description,
        target_country=llm_country_label,
    )
    search_terms = llm_result.get("search_terms", _extract_keywords(product_desc))[:20]
    forbidden_terms = llm_result.get("forbidden_terms", [])
    # Normalize Unicode
    import unicodedata
    search_terms = [
        unicodedata.normalize("NFKC", kw).replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
        for kw in search_terms
    ]
    print(f"[TARGETING] Search terms: {search_terms}, Forbidden: {forbidden_terms}", flush=True)
    age_min = llm_result.get("age_min", 18)
    age_max = llm_result.get("age_max", 65)
    persona_reasoning = llm_result.get("persona_reasoning", "")

    # Step B: research trends via MCP (for context, not keyword extraction)
    trends = await _research_trends_via_mcp(product_desc, industry_niche, target_country)

    # Step C: Search Meta API with each search term → collect real interests (Hybrid Step 2)
    all_validated = []
    seen_ids = set()
    search_countries = country_codes if country_codes else ["US"]
    for cc in search_countries[:3]:  # Cap at 3 countries to avoid excessive API calls
        validated = await _search_interests_via_mcp(search_terms, cc, access_token)
        for interest in validated:
            iid = interest.get("id")
            if iid and iid not in seen_ids:
                seen_ids.add(iid)
                all_validated.append(interest)

    # Step C2: Filter out interests that match forbidden industry terms
    filtered = _filter_forbidden(all_validated, forbidden_terms)
    print(f"[TARGETING] After forbidden filter: {len(all_validated)} → {len(filtered)} interests", flush=True)

    # Step D: SNIPER SELECTION — Elite LLM picks the best 5 from the full pool
    top_interests = await _sniper_selection(
        filtered, product_desc, business_description, llm_country_label, forbidden_terms,
    )
    print(f"[TARGETING] Sniper selected: {[(i.get('name'), i.get('audience_size', 0)) for i in top_interests]}", flush=True)

    # Step D: build geo_locations
    # target_cities can be:
    #   - list of dicts with "key" (pre-resolved from Meta geo search) → use directly
    #   - list of strings (legacy free-text) → resolve via MCP
    if target_cities:
        if isinstance(target_cities[0], dict) and target_cities[0].get("key"):
            # Pre-resolved geo objects — build geo_locations directly
            geo_cities = [{"key": c["key"], "name": c.get("name", ""), "country_code": c.get("country_code", target_country)} for c in target_cities]
            geo_locations = {"countries": country_codes, "cities": geo_cities}
        else:
            # Legacy string names — resolve via MCP
            city_names = [c if isinstance(c, str) else c.get("name", "") for c in target_cities]
            geo_locations = await _resolve_geo_via_mcp(city_names, target_country, access_token)
    elif is_worldwide:
        # Worldwide: omit countries → Meta targets globally
        geo_locations = {}
    else:
        geo_locations = {"countries": country_codes}

    return {
        "interests": top_interests,
        "geo_locations": geo_locations,
        "trends": trends,
        "keywords_used": search_terms,
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
