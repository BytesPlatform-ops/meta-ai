"""
Angle Analyzer — Competitor intelligence engine.

Analyzes competitor ads fetched from Meta Ad Library to identify market gaps
and produce a differentiation strategy for campaign creative.
"""
import json
import logging

from openai import AsyncOpenAI

from ..core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def analyze_market_gaps(competitor_ads_data: list[dict]) -> dict:
    """
    Analyze competitor ads to identify patterns and market gaps.

    Args:
        competitor_ads_data: List of competitor ad dicts from fetch_competitor_ads MCP tool.
            Each dict has: body, headline, caption, cta, media_type, keyword.

    Returns:
        {
            "differentiation_strategy": str,
            "recommended_angles": list[str],
            "avoid_patterns": list[str],
        }
    """
    if not competitor_ads_data:
        return {
            "differentiation_strategy": "No competitor data available. Use a unique value proposition and test multiple creative angles.",
            "recommended_angles": ["unique selling proposition", "customer testimonials", "limited-time offer"],
            "avoid_patterns": [],
        }

    ads_summary = json.dumps(competitor_ads_data[:30], indent=2)

    prompt = f"""You are an expert Meta Ads strategist specializing in competitive analysis for e-commerce brands.

Analyze these {len(competitor_ads_data)} competitor ads and identify patterns and market gaps.

## Competitor Ads Data
{ads_summary}

## Your Analysis Must Return ONLY valid JSON with this exact structure:
{{
    "differentiation_strategy": "A 2-3 sentence strategy explaining HOW to differentiate from competitors. Be specific — reference what competitors are doing and what angle to take instead.",
    "recommended_angles": ["angle 1", "angle 2", "angle 3"],
    "avoid_patterns": ["saturated pattern 1", "saturated pattern 2"]
}}

Rules:
- Identify the most common hooks, offers, and CTAs used by competitors
- Find gaps — what are competitors NOT saying that could resonate with buyers?
- recommended_angles should be specific creative directions (e.g., "gifting angle with premium packaging" not just "be different")
- avoid_patterns should list saturated approaches that won't stand out
- Return ONLY the JSON object, no markdown, no explanation"""

    response = await openai_client.chat.completions.create(
        model=settings.ELITE_REASONING_MODEL,
        messages=[
            {"role": "system", "content": "You are a competitive intelligence analyst. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=800,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content.strip()

    # Parse JSON response, stripping markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse angle analysis JSON, using fallback")
        result = {
            "differentiation_strategy": raw[:500],
            "recommended_angles": [],
            "avoid_patterns": [],
        }

    return {
        "differentiation_strategy": result.get("differentiation_strategy", ""),
        "recommended_angles": result.get("recommended_angles", []),
        "avoid_patterns": result.get("avoid_patterns", []),
    }
