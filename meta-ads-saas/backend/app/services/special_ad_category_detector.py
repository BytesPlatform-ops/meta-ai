"""
Special Ad Category (SAC) detector.

Determines whether a draft must be marked under one of Meta's Special Ad
Categories before publishing. Uses an LLM in semantic-classification mode
(no hardcoded keyword lists) so the system works for any product, in any
country, in any language, and adapts as Meta's category boundaries evolve.

Design principles
-----------------
1. **Generic.** No keyword hardcoding. The LLM understands intent.
2. **World-applicable.** Region-aware — flags country-specific concerns.
3. **Authoritative definitions.** The prompt feeds Meta's own definitions
   (paraphrased) for each category, so the model classifies against the
   real policy boundary, not against a curated keyword set.
4. **Calibrated confidence.** Returns a 0–1 confidence so the caller can
   decide to auto-apply, prompt for confirmation, or skip.
5. **Strictness ranking.** When multiple categories could apply, returns
   the strictest one (HEC trumps Financial trumps None) — matches Meta's
   own enforcement priority.

Public API
----------
    await detect_special_ad_category(context: DraftContext) -> SACDecision

The caller assembles a ``DraftContext`` from whatever data sources are
relevant (draft body, attached product, workspace business profile,
target country). The detector is stateless — pass it everything you have,
get back a structured decision.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from typing import Any, Optional

from openai import AsyncOpenAI

from ..core.config import get_settings

logger = logging.getLogger(__name__)
_settings = get_settings()
_openai = AsyncOpenAI(api_key=_settings.OPENAI_API_KEY)


# ── Meta's category catalog (authoritative — keep in sync with Meta docs) ──────
#
# Each entry contains:
#   code        — exact value Meta's API expects in `special_ad_categories`
#   label       — human-readable name
#   strictness  — 0=none, 1=soft (Financial), 2=HEC, 3=auth-required (Issues/Gambling)
#   definition  — Meta's policy definition in plain English. Fed verbatim to LLM.
#
# Categories are sourced from Meta's Business Help and Transparency Center
# and the public 2025–2026 policy updates. Update this catalog when Meta
# changes definitions; the LLM prompt picks them up automatically.

CATEGORY_CATALOG: list[dict[str, Any]] = [
    {
        "code": "HOUSING",
        "label": "Housing",
        "strictness": 2,
        "definition": (
            "Ads that promote or directly link to housing opportunities — "
            "sale or rental of real estate, listings, agent services, "
            "mortgages aimed at home purchase, or housing-related insurance."
        ),
        "examples_for_llm": (
            "Rental listings, real-estate agent services, mortgage broker "
            "ads aimed at homebuyers, condo developments, REIT consumer "
            "products. NOT for B2B real-estate software (e.g. CRM for agents)."
        ),
    },
    {
        "code": "EMPLOYMENT",
        "label": "Employment",
        "strictness": 2,
        "definition": (
            "Ads that promote or directly link to employment opportunities — "
            "job postings, recruitment campaigns, hiring drives, internships, "
            "or services that connect employers to candidates."
        ),
        "examples_for_llm": (
            "Job listings, gig-economy driver/courier recruitment, "
            "recruitment-agency ads, job-board promotions, hiring fairs. "
            "NOT for HR-software ads selling tools to companies."
        ),
    },
    {
        "code": "CREDIT",
        "label": "Credit",
        "strictness": 2,
        "definition": (
            "Ads for credit-card offers, auto/personal/student loans, "
            "mortgages, Buy Now Pay Later (BNPL) products, lines of credit, "
            "and crypto lending platforms. As of 2026 Meta explicitly "
            "classifies BNPL and crypto-lending under Credit."
        ),
        "examples_for_llm": (
            "Klarna/Afterpay/Affirm-style BNPL, payday alternatives (where "
            "permitted), credit-card sign-ups, mortgage refi, student-loan "
            "products, crypto-collateral lending. NOT for general fintech "
            "tools that don't extend credit."
        ),
    },
    {
        # Meta's API enum drops the "AND" — display name says "Financial Products
        # and Services", but the Marketing API rejects FINANCIAL_PRODUCTS_AND_SERVICES
        # and only accepts FINANCIAL_PRODUCTS_SERVICES.
        "code": "FINANCIAL_PRODUCTS_SERVICES",
        "label": "Financial Products and Services",
        "strictness": 1,
        "definition": (
            "Ads for trading platforms, brokerages, investment advisors, "
            "robo-advisors, crypto exchanges/wallets, insurance products, "
            "tax services, retirement planning, and financial-data products. "
            "Distinct from Credit — this covers products that handle/route "
            "money or investments without extending credit."
        ),
        "examples_for_llm": (
            "Stock/crypto/forex trading platforms, brokerage accounts, "
            "robo-advisors, AI signal services, copy-trading tools, "
            "insurance carriers/brokers, wealth-management platforms, "
            "crypto exchanges, tax-prep services. NOT for general fintech "
            "infrastructure (e.g. payment-processing API for developers)."
        ),
    },
    {
        "code": "ISSUES_ELECTIONS_POLITICS",
        "label": "Social Issues, Elections or Politics",
        "strictness": 3,
        "definition": (
            "Ads about elections, candidates, ballot measures, government "
            "policy, or socially divisive issues (immigration, civil rights, "
            "guns, abortion, etc.). Requires advertiser identity verification "
            "and disclaimer through Meta's authorization flow."
        ),
        "examples_for_llm": (
            "Candidate ads, voter-mobilization, advocacy on social issues, "
            "policy-position content. Even commercial brands taking public "
            "stances on politicized topics can fall here."
        ),
    },
    {
        "code": "ONLINE_GAMBLING_AND_GAMING",
        "label": "Online Gambling and Gaming",
        "strictness": 3,
        "definition": (
            "Ads for sports betting, online casinos, lotteries, fantasy "
            "sports played for real money, and similar products. Requires "
            "regional licensing — only available in markets where Meta has "
            "approved gambling advertising."
        ),
        "examples_for_llm": (
            "Sports-betting apps, online casinos, lottery promotions, "
            "real-money fantasy sports. NOT for skill-based games without "
            "wagering, or for purely informational gambling-news content."
        ),
    },
]


# ── Structured I/O ────────────────────────────────────────────────────────────


@dataclass
class DraftContext:
    """Everything the detector needs to classify a draft.

    Pass `None` for fields that don't apply (e.g. no attached product).
    The detector handles missing context gracefully; more context = higher
    confidence.
    """

    headline: Optional[str] = None
    body_text: Optional[str] = None
    product_name: Optional[str] = None
    product_description: Optional[str] = None
    product_type: Optional[str] = None
    industry_niche: Optional[str] = None
    business_name: Optional[str] = None
    business_description: Optional[str] = None
    website_url: Optional[str] = None
    target_country: Optional[str] = None  # ISO code or comma-separated
    is_explicit_hiring: bool = False  # the legacy `is_employment_ad` flag
    extra_signals: Optional[dict] = None  # anything else worth passing


@dataclass
class SACDecision:
    """The detector's verdict.

    `category` is the exact Meta API code (or `None` for no SAC).
    `confidence` is in [0, 1] — calibrated by the model.
    `should_auto_apply` is the recommended action given confidence + strictness.
    `reasoning` is a short explanation for the UI/audit.
    `region_notes` flags country-specific concerns (verification, prohibited,
    regional licensing).
    """

    category: Optional[str]
    confidence: float
    should_auto_apply: bool
    reasoning: str
    region_notes: Optional[str] = None
    raw: Optional[dict] = None  # full LLM response for audit/debug

    def to_dict(self) -> dict:
        return asdict(self)


# Confidence policy — tunable.
# Above AUTO: trust the LLM, set the category at publish time.
# Between SUGGEST and AUTO: surface a prompt to the user before publishing.
# Below SUGGEST: don't apply anything.
#
# AUTO threshold tuned to 0.7: empirically the model returns 0.78-0.85 for
# clearly-regulated businesses (trading platforms, real-estate sites, hiring
# pages) when only the business profile is available without specific ad copy.
# 0.85 was too strict — it caused false negatives for obvious cases like Quantiva.
_CONFIDENCE_AUTO_APPLY = 0.70
_CONFIDENCE_SUGGEST = 0.50


# ── Detector ──────────────────────────────────────────────────────────────────


async def detect_special_ad_category(context: DraftContext) -> SACDecision:
    """
    Classify a draft against Meta's Special Ad Categories.

    Returns a `SACDecision`. The caller decides whether to:
      - auto-apply (decision.should_auto_apply == True)
      - prompt the user (CONFIDENCE_SUGGEST ≤ confidence < CONFIDENCE_AUTO_APPLY)
      - leave it alone (confidence < CONFIDENCE_SUGGEST)
    """
    # The legacy hiring flag is an explicit user signal — trust it without
    # paying for an LLM call.
    if context.is_explicit_hiring:
        return SACDecision(
            category="EMPLOYMENT",
            confidence=1.0,
            should_auto_apply=True,
            reasoning="User explicitly marked this draft as a hiring ad.",
            region_notes=None,
            raw={"source": "explicit_hiring_flag"},
        )

    prompt_text = _build_prompt(context)

    try:
        resp = await _openai.chat.completions.create(
            model=_settings.ELITE_REASONING_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a Meta Ads policy compliance classifier. Your job is "
                        "to determine whether an advertisement falls under one of Meta's "
                        "Special Ad Categories. Decide based on what the ad is *promoting*, "
                        "not on what platform it's running on. Output strict JSON only."
                    ),
                },
                {"role": "user", "content": prompt_text},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=600,
        )
        raw = json.loads(resp.choices[0].message.content.strip())
    except Exception as e:
        logger.warning("SAC detector LLM call failed: %s", e)
        return SACDecision(
            category=None,
            confidence=0.0,
            should_auto_apply=False,
            reasoning=f"Detector error — defaulted to no category: {e}",
            region_notes=None,
            raw={"error": str(e)},
        )

    return _parse_decision(raw)


def _build_prompt(ctx: DraftContext) -> str:
    """Compose the user-message prompt. Generic — no hardcoded keywords."""
    catalog_block = "\n\n".join(
        (
            f"### {c['label']}  (`{c['code']}`)\n"
            f"**Strictness tier:** {_strictness_label(c['strictness'])}\n"
            f"**Definition:** {c['definition']}\n"
            f"**Inclusion examples:** {c['examples_for_llm']}"
        )
        for c in CATEGORY_CATALOG
    )

    context_block = _format_context_block(ctx)

    return (
        "Classify the following advertisement against Meta's Special Ad Categories.\n\n"
        "## Meta's Special Ad Categories (authoritative reference)\n\n"
        f"{catalog_block}\n\n"
        "---\n\n"
        "## The advertisement to classify\n\n"
        f"{context_block}\n\n"
        "---\n\n"
        "## Your task\n\n"
        "Decide whether this ad falls under any Special Ad Category. Apply these rules:\n\n"
        "1. **Classify against intent, not vocabulary.** A keyword like \"crypto\" alone "
        "doesn't trigger a category — what matters is whether the ad is *promoting* a "
        "regulated product. A meme-coin t-shirt store is not Financial Products; a "
        "trading platform is.\n\n"
        "2. **Strictness ranking when multiple apply.** If an ad could fit two categories, "
        "pick the strictest. HEC (Housing/Employment/Credit, strictness 2) outranks "
        "Financial Products (strictness 1). Issues/Politics and Gambling (strictness 3) "
        "outrank everything else but only when the ad is *unambiguously* about that.\n\n"
        "3. **Be region-aware.** If the target country is provided, note any "
        "country-specific concerns: regulatory verification needed (FCA UK, BaFin DE, "
        "SEC/FINRA US, MAS SG, etc.), product type prohibited in that region "
        "(e.g. crypto restrictions, payday-loan bans), or licensing required (gambling).\n\n"
        "4. **Calibrate confidence honestly.** 0.95+ means \"obviously this category.\" "
        "0.7–0.9 means \"likely but the ad context is thin.\" 0.5–0.7 means \"borderline — "
        "could go either way.\" Below 0.5 means \"probably not a SAC ad.\"\n\n"
        "5. **B2B exception.** Software/tools/services *sold to businesses in a regulated "
        "industry* are usually NOT in the regulated category themselves. Example: a CRM "
        "for real-estate agents is NOT Housing; a payroll tool for employers is NOT "
        "Employment. The ad's audience matters.\n\n"
        "## Output format (strict JSON)\n\n"
        "{\n"
        '  "category": "<one of the codes above, or null>",\n'
        '  "confidence": <number between 0 and 1>,\n'
        '  "reasoning": "<2-3 sentence explanation in plain English>",\n'
        '  "region_notes": "<region-specific concerns if applicable, else null>",\n'
        '  "alternatives_considered": ["<other category codes ruled out, if any>"]\n'
        "}"
    )


def _format_context_block(ctx: DraftContext) -> str:
    fields: list[tuple[str, Optional[str]]] = [
        ("Headline", ctx.headline),
        ("Ad body text", ctx.body_text),
        ("Attached product name", ctx.product_name),
        ("Attached product description", ctx.product_description),
        ("Product type / category", ctx.product_type),
        ("Industry niche", ctx.industry_niche),
        ("Business name", ctx.business_name),
        ("Business description", ctx.business_description),
        ("Website", ctx.website_url),
        ("Target country (ISO code or comma-separated list)", ctx.target_country),
    ]
    lines = [f"- **{label}:** {value}" for label, value in fields if value]
    if ctx.extra_signals:
        lines.append(f"- **Other signals:** {json.dumps(ctx.extra_signals)}")
    if not lines:
        lines.append("- *(no context provided)*")
    return "\n".join(lines)


def _strictness_label(level: int) -> str:
    return {
        0: "None",
        1: "Soft (some targeting restrictions)",
        2: "HEC strict (heavy targeting strip)",
        3: "Authorization required",
    }.get(level, "Unknown")


def _parse_decision(raw: dict) -> SACDecision:
    """Validate and normalize the LLM's JSON response into a SACDecision."""
    valid_codes = {c["code"] for c in CATEGORY_CATALOG}
    code = raw.get("category")
    if isinstance(code, str):
        code = code.strip().upper()
        if code in {"NONE", "NULL", ""}:
            code = None
        elif code not in valid_codes:
            logger.warning("SAC detector returned unknown category code: %r", code)
            code = None
    else:
        code = None

    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    reasoning = (raw.get("reasoning") or "").strip() or "(no reasoning provided)"
    region_notes = raw.get("region_notes")
    if isinstance(region_notes, str):
        region_notes = region_notes.strip() or None
    else:
        region_notes = None

    should_auto = bool(code) and confidence >= _CONFIDENCE_AUTO_APPLY

    return SACDecision(
        category=code,
        confidence=confidence,
        should_auto_apply=should_auto,
        reasoning=reasoning,
        region_notes=region_notes,
        raw=raw,
    )


# ── Convenience wrapper for the publish path ─────────────────────────────────


async def detect_for_draft(
    *,
    draft: dict,
    workspace: Optional[dict] = None,
    product: Optional[dict] = None,
    preferences: Optional[dict] = None,
) -> SACDecision:
    """
    Higher-level helper: assemble a `DraftContext` from the typical
    Supabase row shapes used in ad_executor and content_generator, then
    call the detector. Use this from the publish pipeline.
    """
    workspace = workspace or {}
    product = product or {}
    preferences = preferences or {}

    target_country = (
        draft.get("target_country")
        or (draft.get("targeting") or {}).get("target_country")
        or product.get("target_country")
        or workspace.get("target_country")
        or preferences.get("target_country")
    )

    context = DraftContext(
        headline=draft.get("headline"),
        body_text=draft.get("body_text"),
        product_name=product.get("name"),
        product_description=product.get("description"),
        product_type=product.get("product_type"),
        industry_niche=(
            product.get("tags") or workspace.get("industry_niche") or preferences.get("industry_niche")
        ),
        business_name=workspace.get("business_name") or preferences.get("business_name"),
        business_description=(
            workspace.get("business_description") or preferences.get("business_description")
        ),
        website_url=workspace.get("website_url") or preferences.get("website_url"),
        target_country=target_country,
        is_explicit_hiring=bool(draft.get("is_employment_ad") or draft.get("hiring_data")),
    )
    return await detect_special_ad_category(context)
