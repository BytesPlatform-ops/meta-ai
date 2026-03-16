"""
Strategy Engine — Autonomous market research & content strategy generator.

Orchestrates existing MCP tools (research_niche_trends, fetch_competitor_ads)
and the angle_analyzer to produce a structured content strategy.
"""
import json
import logging

from openai import AsyncOpenAI

from ..core.config import get_settings
from ..db.supabase_client import get_supabase
from .mcp_client import mcp_client, MCPError
from .angle_analyzer import analyze_market_gaps
from .targeting_engine import _parse_mcp_json

logger = logging.getLogger(__name__)
settings = get_settings()
openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def generate_content_strategy(user_id: str) -> dict:
    """
    Full CMO pipeline:
      1. Load user's brand context from preferences + products
      2. Research niche trends via MCP (Tavily web search)
      3. Fetch competitor ads via MCP (Meta Ad Library)
      4. Analyze market gaps (angle_analyzer)
      5. Feed everything to LLM for structured strategy
      6. Persist to content_strategies table
    """
    supabase = get_supabase()

    # ── 1. Load brand context ─────────────────────────────────────────────────
    prefs_result = (
        supabase.table("user_preferences")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )
    prefs = prefs_result.data[0] if prefs_result.data else {}

    biz_name = prefs.get("business_name") or "My Business"
    biz_desc = prefs.get("business_description") or ""
    niche = prefs.get("industry_niche") or biz_desc[:80]
    target_audience = prefs.get("target_audience") or ""
    website = prefs.get("website_url") or ""
    website_intel = prefs.get("website_intel") or {}
    target_country = prefs.get("target_country") or "PK"

    # Load products for richer context
    products_result = (
        supabase.table("products")
        .select("name, description, price, currency, target_audience")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(10)
        .execute()
    )
    products = products_result.data or []
    product_summary = "; ".join(
        f"{p['name']} ({p.get('currency','USD')} {p.get('price','')})"
        for p in products
    ) or "No products listed"

    # Load ad account for access token (needed for competitor ads)
    account_result = (
        supabase.table("ad_accounts")
        .select("meta_account_id, access_token")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    access_token = ""
    if account_result.data:
        access_token = account_result.data[0]["access_token"]

    # ── 2. Research niche trends (Tavily) ─────────────────────────────────────
    trends_data = {}
    try:
        trends_result = await mcp_client.call_tool(
            "research_niche_trends",
            {"niche": niche, "country": target_country},
            user_access_token="",
        )
        trends_data = _parse_mcp_json(trends_result) if not isinstance(trends_result, dict) else trends_result
        if not isinstance(trends_data, dict):
            trends_data = {}
    except MCPError as e:
        logger.warning("Trends research failed: %s", e)

    trends = trends_data.get("trends", [])
    audience_insights = trends_data.get("audience_insights", [])
    competitor_angles = trends_data.get("competitor_angles", [])

    # ── 3. Fetch competitor ads (Meta Ad Library) ─────────────────────────────
    competitor_ads = []
    if access_token:
        # Build search keywords from niche + business name
        keywords = [niche]
        if biz_name and biz_name.lower() not in niche.lower():
            keywords.append(biz_name)

        try:
            ads_result = await mcp_client.call_tool(
                "fetch_competitor_ads",
                {"keywords_json": json.dumps(keywords), "country_code": target_country},
                user_access_token=access_token,
            )
            parsed = _parse_mcp_json(ads_result) if not isinstance(ads_result, dict) else ads_result
            if isinstance(parsed, dict):
                competitor_ads = parsed.get("ads", [])
        except MCPError as e:
            logger.warning("Competitor ads fetch failed: %s", e)

    # ── 4. Analyze market gaps ────────────────────────────────────────────────
    gap_analysis = await analyze_market_gaps(competitor_ads)

    # ── 5. LLM: Generate structured strategy ──────────────────────────────────
    research_context = f"""## Brand
- Name: {biz_name}
- Description: {biz_desc}
- Niche: {niche}
- Target Audience: {target_audience}
- Products: {product_summary}
- Website: {website}
{f"""
## Website Intelligence (Scraped)
{json.dumps(website_intel, indent=2)}
""" if website_intel and not website_intel.get("error") else ""}
## Live Market Research (Tavily)
- Trends: {json.dumps(trends)}
- Audience Insights: {json.dumps(audience_insights)}
- Competitor Angles: {json.dumps(competitor_angles)}

## Competitor Ads from Meta Ad Library ({len(competitor_ads)} ads found)
{json.dumps(competitor_ads[:15], indent=2) if competitor_ads else "No competitor ads found."}

## Market Gap Analysis
- Differentiation Strategy: {gap_analysis.get('differentiation_strategy', '')}
- Recommended Angles: {json.dumps(gap_analysis.get('recommended_angles', []))}
- Avoid Patterns: {json.dumps(gap_analysis.get('avoid_patterns', []))}"""

    system_prompt = """You are an elite marketing strategist and CMO. Based on the live web research and competitor ad library data provided, generate a comprehensive content strategy.

Return ONLY valid JSON with this exact structure:
{
  "market_insights": ["insight 1", "insight 2", "insight 3"],
  "competitor_weaknesses": ["weakness 1", "weakness 2"],
  "campaign_suggestions": [
    {
      "angle": "The main creative angle",
      "hook": "The opening hook/headline that grabs attention",
      "format": "recommended ad format (image, video, carousel, story)",
      "platform": "facebook, instagram, or both",
      "reasoning": "Why this will work based on the research"
    }
  ],
  "content_calendar": [
    {
      "week": 1,
      "theme": "Theme for this week",
      "posts": ["post idea 1", "post idea 2"]
    }
  ],
  "brand_voice_notes": "Recommended tone and messaging style based on the niche"
}

Rules:
- Generate exactly 3-5 campaign suggestions
- Generate a 4-week content calendar
- Be specific — reference actual trends and competitor gaps
- Every suggestion must tie back to the live research data
- Prioritize angles competitors are NOT using"""

    response = await openai_client.chat.completions.create(
        model=settings.CHEAP_FAST_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": research_context},
        ],
        max_completion_tokens=2000,
    )
    raw = response.choices[0].message.content.strip()

    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        strategy_json = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse strategy JSON, wrapping as raw text")
        strategy_json = {
            "market_insights": [],
            "competitor_weaknesses": [],
            "campaign_suggestions": [],
            "content_calendar": [],
            "brand_voice_notes": raw[:1000],
        }

    # ── 6. Persist to DB ──────────────────────────────────────────────────────
    research_summary = (
        f"Analyzed {len(competitor_ads)} competitor ads. "
        f"Found {len(trends)} market trends. "
        f"Gap analysis: {gap_analysis.get('differentiation_strategy', 'N/A')}"
    )

    record = {
        "user_id": user_id,
        "niche": niche,
        "research_summary": research_summary,
        "strategy_json": strategy_json,
        "status": "DRAFT",
    }

    result = supabase.table("content_strategies").insert(record).execute()
    saved = result.data[0] if result.data else record

    return {
        "id": saved.get("id"),
        "niche": niche,
        "research_summary": research_summary,
        "strategy": strategy_json,
        "competitor_ads_analyzed": len(competitor_ads),
        "trends_found": len(trends),
        "status": "DRAFT",
    }
