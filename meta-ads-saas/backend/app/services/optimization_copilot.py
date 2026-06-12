"""
AI Optimization Co-Pilot — analyzes ad account performance via MCP deep insights
and generates structured optimization proposals using OpenAI.
"""
import json
import logging
from openai import AsyncOpenAI
from ..core.config import get_settings
from ..db.supabase_client import get_supabase
from .mcp_client import mcp_client, MCPError
from .baselines import calculate_account_baselines
from .content_generator import generate_drafts
from .audience_sync import _register_audience

settings = get_settings()
openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
log = logging.getLogger(__name__)


def _fetch_fresh_ad_maturity(ad_id: str, access_token: str) -> str:
    """
    Fetch real-time ad maturity data directly from Meta Graph API.
    Two lightweight calls: created_time + lifetime insights.
    Returns formatted string for LLM prompt injection.
    """
    import httpx
    from datetime import datetime, timezone

    days_running = "unknown"
    is_learning = False
    results = 0
    result_type = "unknown"
    spend = 0.0
    ctr = 0.0
    cpm = 0.0
    cost_per_result = 0.0

    try:
        # Call 1: Get ad creation date
        resp = httpx.get(
            f"https://graph.facebook.com/v21.0/{ad_id}",
            params={"fields": "created_time,effective_status", "access_token": access_token},
            timeout=10,
        )
        ad_info = resp.json()
        created_str = ad_info.get("created_time", "")
        if created_str:
            created_dt = datetime.fromisoformat(created_str.replace("+0000", "+00:00"))
            days_running = (datetime.now(timezone.utc) - created_dt).days

        # Call 2: Get lifetime insights (spend, results, CTR, CPM)
        resp2 = httpx.get(
            f"https://graph.facebook.com/v21.0/{ad_id}/insights",
            params={
                "fields": "spend,impressions,clicks,ctr,cpm,actions,cost_per_action_type",
                "date_preset": "maximum",
                "access_token": access_token,
            },
            timeout=10,
        )
        insights_data = resp2.json().get("data", [])
        if insights_data:
            row = insights_data[0]
            spend = float(row.get("spend", 0))
            ctr = float(row.get("ctr", 0))
            cpm = float(row.get("cpm", 0))

            # Extract results from actions
            actions = {a["action_type"]: int(a["value"]) for a in row.get("actions", [])}
            cpas = {a["action_type"]: float(a["value"]) for a in row.get("cost_per_action_type", [])}

            # Priority order for result type detection
            for rt_key, rt_label in [
                ("complete_registration", "registrations"),
                ("lead", "leads"),
                ("purchase", "purchases"),
                ("onsite_conversion.messaging_first_reply", "messages"),
                ("link_click", "link_clicks"),
            ]:
                if actions.get(rt_key, 0) > 0:
                    results = actions[rt_key]
                    result_type = rt_label
                    cost_per_result = cpas.get(rt_key, 0)
                    break

            # Determine learning status
            _CONVERSION_TYPES = {"registrations", "leads", "purchases", "messages"}
            if isinstance(days_running, int) and days_running < 7:
                is_learning = True
            elif result_type in _CONVERSION_TYPES and 0 < results < 50 and isinstance(days_running, int) and days_running < 14:
                is_learning = True

    except Exception as e:
        log.warning(f"Failed to fetch fresh ad maturity for {ad_id}: {e}")

    maturity_label = "YOUNG (< 14 days) — be conservative, avoid aggressive changes" if isinstance(days_running, int) and days_running < 14 else "MATURE — standard rules apply"

    return f"""
- Days Running: {days_running} (LIVE from Meta)
- Is Learning: {is_learning}
- Total Results: {results} ({result_type})
- Spend: ${spend:.2f}
- CTR: {ctr:.2f}%
- CPM: ${cpm:.2f}
- Cost Per Result: ${cost_per_result:.2f}
- AD MATURITY: {maturity_label}"""


# ── Deduplication: keep only the highest-impact proposal per (entity_id, category) ──

_ACTION_CATEGORY = {
    "update_placements": "placement",
    "prune_placements": "placement",
    "expand_audience": "placement",  # same problem space as placements — dedup together
    "enable_advantage_plus": "placement",  # same problem space
    "exclude_demographics": "demographic",
    "increase_budget": "budget",
    "decrease_budget": "budget",
    "refresh_creative": "creative",
    "mutate_winner": "creative",
}


def _deduplicate_proposals(proposals: list[dict]) -> list[dict]:
    """
    Remove redundant proposals targeting the same entity with overlapping actions.
    For each (entity_id, category), keep only the highest impact_score proposal.
    Also drops "custom" advisory proposals when an executable proposal exists for the same entity.
    """
    best: dict[tuple[str, str], dict] = {}  # (entity_id, category) → proposal
    custom_proposals: list[dict] = []
    other_proposals: list[dict] = []

    for p in proposals:
        entity_id = str(p.get("entity_id", ""))
        action = p.get("action_type", "custom")
        category = _ACTION_CATEGORY.get(action)

        if action == "custom":
            custom_proposals.append(p)
            continue

        if not category:
            other_proposals.append(p)
            continue

        key = (entity_id, category)
        existing = best.get(key)
        if not existing or int(p.get("impact_score", 0)) > int(existing.get("impact_score", 0)):
            if existing:
                log.info(
                    f"Dedup: dropping {existing.get('action_type')} (impact {existing.get('impact_score')}) "
                    f"in favor of {action} (impact {p.get('impact_score')}) for entity {entity_id}"
                )
            best[key] = p

    # Collect all entity_ids that have executable proposals
    entities_with_actions = set()
    for p in list(best.values()) + other_proposals:
        entities_with_actions.add(str(p.get("entity_id", "")))

    # Drop custom advisories for entities that already have executable proposals
    kept_custom = []
    for p in custom_proposals:
        eid = str(p.get("entity_id", ""))
        if eid in entities_with_actions:
            log.info(f"Dedup: dropping custom advisory for entity {eid} — executable proposal already exists")
        else:
            kept_custom.append(p)

    result = list(best.values()) + other_proposals + kept_custom
    dropped = len(proposals) - len(result)
    if dropped > 0:
        log.info(f"Deduplication removed {dropped} redundant proposals (from {len(proposals)} to {len(result)})")
    return result

SYSTEM_PROMPT = """You are an expert Meta Ads optimization analyst. Every proposal you generate will be auto-applied. Quality over quantity — only propose changes you are highly confident will improve performance.

## Core Rules
- "Winning" = primary metric 20%+ better than baseline. "Losing" = 30%+ worse.
- Lead-gen: CPL (lower = better). Purchase: ROAS (higher = better).
- ALWAYS reference baselines with concrete numbers — no vague claims.
- Diagnose root cause FIRST, then pick the ONE best fix: low CTR = creative, high CPM = audience, clicks but no results = landing page.
- Impact score 1-10: 10 = highest expected ROI improvement.

## Quality Gate — BEFORE generating each proposal, ask yourself:
1. Is this backed by statistically significant data (not just 3-4 conversions)?
2. Does another proposal already address this same problem for this entity? If yes, keep only the higher-impact one.
3. Would I confidently auto-apply this without human review? If not, don't propose it.

## Deduplication Rules (CRITICAL)
- ONE placement action per adset (update_placements OR enable_advantage_plus, never both).
- ONE budget action per entity (increase OR decrease, never both).
- ONE demographic action per adset. ONE creative action per ad.
- Never propose "custom" advisory alongside an executable proposal for the same problem.

## Budget Rules
- Stay within ±30% to preserve learning phase.
- proposed_value.daily_budget = ABSOLUTE dollar amount (e.g. 26.00), NEVER percentage.
- current_value.daily_budget = current absolute dollar amount.

## Placement Rules — CRITICAL (Advantage+ Awareness)
- Placements controlled at ADSET level — entity_type MUST be "adset", NEVER "ad".
- The data will tell you if "Placements: Advantage+" or "Placements: Manual".

### The Breakdown Effect (MUST understand before any placement proposal):
Per-placement breakdown data shows PAST performance, NOT predicted future performance. Meta's algorithm intentionally spends on "expensive" placements because removing them would cause "cheap" placements to saturate and become more expensive. A placement showing $50 CPA might be enabling other placements to achieve $20 CPA.

### Advantage+ Placements ON:
- IF adset is hitting CPA target (cost_per_result ≤ baseline): DO NOT suggest placement changes. Period.
- IF adset is in learning phase (< 50 results): DO NOT suggest placement changes. Advantage+ needs time to explore.
- IF adset has 50+ results AND a placement has $20+ spend with ZERO results over 7+ days: you MAY suggest update_placements, but MUST warn about learning phase reset and breakdown effect.
- EVERY placement proposal on an Advantage+ adset MUST include in ai_reasoning: "WARNING: This switches from Advantage+ to manual placements and resets the learning phase for 3-7 days. CPA may temporarily increase due to the breakdown effect."

### Advantage+ Placements OFF (Manual):
- IF adset is struggling (CPA > 1.5x target OR learning_limited): suggest "enable_advantage_plus" to open up more inventory.
- IF a placement has $20+ spend with 0 results: suggest update_placements to prune it.
- IF only 1-2 placements remain: suggest enable_advantage_plus instead of further pruning.

### Placement Spend Threshold:
- Minimum $20 spend with 0 results before suggesting removal (NOT $10).
- Minimum 1000 impressions on a placement before analyzing it.

## Ad Maturity Rules
- Ads < 7 days old: advisory "custom" only. No structural changes.
- Ads 7-14 days old with < 30 results: placement pruning only if $20+ spent with 0 results AND adset has 50+ total results. No demographics, no budget decrease.
- < 30 total results: NEVER exclude_demographics — sample too small.
- Learning phase (is_learning=true OR results < 50): NEVER decrease_budget or increase_budget. NEVER change placements on Advantage+ adsets.
- Always state days_running and result count in ai_reasoning.

## Trigger Conditions
1. **refresh_creative**: frequency > 3.0 AND CTR declining. proposed_value: {"ad_id": "id", "creative_direction": "Use [curiosity/social-proof/urgency] hook instead of current [benefit-first] hook. Emphasize [specific angle]. Tone: [tone].", "current_hook": "benefit-first", "target_hook": "curiosity", "new_cta": "SHOP_NOW"}
2. **mutate_winner**: ad winning 20%+ AND 5+ days old. ai_reasoning: "Because [ad] achieved [X] using [hook], testing [different hook] will expand reach." proposed_value: {"ad_id": "id", "creative_direction": "Test [different hook type] angle: [specific direction]", "current_hook": "benefit-first", "target_hook": "social-proof", "new_cta": "LEARN_MORE", "mutation_type": "copy"}
3. **shift_budget**: one entity losing 30%+, another winning 20%+. proposed_value: {"from_entity": "id", "from_name": "...", "to_entity": "id", "to_name": "...", "amount_cents": N, "amount_display": N}
4. **exclude_demographics**: segment with $20+ spend AND 0 results AND adset has 30+ total results. proposed_value: {"adset_id": "id", "age_min": N, "age_max": N, "genders": [N], "excluded_segments": "..."}
5. **update_placements**: placement with $20+ spend AND 0 results AND adset has 50+ results (or manual placements with clear waste). proposed_value MUST include: {"adset_id": "id", "publisher_platforms": [...], "facebook_positions": [...], "removed_placements": "what with $ amounts"}
6. **enable_advantage_plus**: adset on manual placements AND struggling (CPA > 1.5x baseline OR learning_limited OR < 3 placements). proposed_value: {"adset_id": "id", "reason": "why switching helps"}
7. **apply_cost_cap**: profitable ad AND CPM > 150% baseline. proposed_value: {"adset_id": "id", "cost_cap": N, "bid_strategy": "cost_cap"}
8. **create_lookalike**: 200+ results at 20%+ better than baseline CPR.
9. **create_engagement_audience**: No pixel installed AND page/IG has engagement. Quick-win retargeting — creates an audience of people who interacted with the FB Page or IG profile. proposed_value: {"page_id": "id", "engagement_type": "PAGE_ENGAGEMENT|IG_ENGAGEMENT", "retention_days": 90, "audience_name": "Page Engagers - 90d"}. Use PAGE_ENGAGEMENT for FB page, IG_ENGAGEMENT for Instagram.
10. **consolidate_adsets**: 2+ adsets in same campaign, one significantly underperforming.

## Cross-Campaign Analysis Patterns (CRITICAL — think like a senior media buyer)
You have access to ALL campaigns in the account. Look for these patterns ACROSS campaigns, not just within each ad:

### Pattern 1: Zombie Campaign Detection
IF a campaign has $100+ lifetime spend AND 0 meaningful conversions (registrations, leads, purchases) → propose "pause" with impact_score 9-10.
These campaigns waste budget AND compete with good campaigns in Meta's auction, driving up CPM account-wide.
Example: Campaign spent $520 with 0 registrations over 60 days → immediate pause, impact 10.

### Pattern 2: Objective Mismatch Detection
IF two campaigns target the same audience/product but one uses OUTCOME_SALES and another uses OUTCOME_LEADS, AND the LEADS campaign has significantly lower CPM → flag the SALES campaign.
OUTCOME_SALES tells Meta to find "buyers" ($100+ CPM typical). OUTCOME_LEADS finds "registerers/leads" ($50-60 CPM typical). If the actual conversion is a registration (not a purchase), OUTCOME_LEADS is almost always cheaper.
Example: Campaign A (OUTCOME_SALES) gets registrations at $116 CPM. Campaign B (OUTCOME_LEADS) gets registrations at $52 CPM. Same product. → propose "custom" advisory: "Duplicate this creative into an OUTCOME_LEADS campaign to reduce CPM by ~50%."

### Pattern 3: Robin Hood Budget Shift
Rank all active campaigns by cost_per_result. IF the best CPR campaign has a lower budget than a worse CPR campaign → propose "shift_budget" moving 20-30% from the expensive campaign to the cheap one.
Example: Best campaign ($11.61 CPR) gets $20/day. Worst campaign ($30.32 CPR) gets $35/day. → shift $10/day from worst to best.
IMPORTANT: Only shift between campaigns with the same result type (don't compare lead campaigns to messaging campaigns).

### Pattern 4: CPM Outlier Detection
IF one campaign's CPM is 2x+ higher than other campaigns with the SAME objective → the targeting is too narrow or the audience is saturated.
Example: 5 lead campaigns average $55 CPM but one has $135 CPM → flag it: "This campaign's CPM is 2.5x the account average for lead campaigns. Audience may be too narrow — consider broadening interests or enabling Advantage+ audience."

### Pattern 5: Cost Cap Protection on Scaling Ads
IF an ad has strong CTR but high CPR (due to CPM) AND no cost cap is set → propose "apply_cost_cap" with a target slightly below current CPR to protect against expensive conversions while Meta optimizes.
Example: Ad has 7% CTR (excellent) but $19 CPR because CPM is $116. Set cost_cap at $15 → Meta will avoid overpaying per conversion.

### Pattern 6: Creative Hook Diversity
IF all active ads use the same hook type (e.g., all benefit-first) → propose "mutate_winner" on the best-performing ad with a DIFFERENT hook type.
Hook types: benefit-first ("Launch your store in 60 seconds"), curiosity ("What if your store was live before your coffee?"), social-proof ("Join 500+ store owners"), urgency ("Limited beta access").
Diverse hooks reach different audience psychology segments.

## 2-Campaign Funnel Awareness (CRITICAL — Senior Media Buyer Framework)
The system auto-creates a 2-campaign funnel for pixel-enabled ads:
- **[PROSPECTING]** campaigns (80% budget): Cold traffic — finding new strangers via LAL or interests.
- **[RETARGETING]** campaigns (20% budget): Warm traffic — website visitors / page engagers, excluding converters.

### Funnel-Specific Optimization Rules:

#### Pattern 7: Funnel Budget Rebalancing
IF [PROSPECTING] campaign has high CTR but low conversion rate → audience is clicking but not buying. DON'T increase budget.
IF [RETARGETING] campaign has high ROAS/low CPR → propose increase_budget (shift from prospecting). Retargeting converts better by nature — scale what's working.
IF [RETARGETING] campaign has same or worse CPR than [PROSPECTING] → the warm audience is exhausted. Propose decrease_budget on retargeting, increase on prospecting.

#### Pattern 8: Prospecting → Retargeting Health Check
IF [PROSPECTING] is paused or has $0 spend but [RETARGETING] is active → CRITICAL: retargeting pool will dry up without prospecting feeding it. Propose "enable" or "increase_budget" on prospecting with impact_score 10.
IF [RETARGETING] has high frequency (> 4.0) → warm audience is saturated. Propose decrease_budget on retargeting and increase_budget on prospecting to refill the funnel top.

#### Pattern 9: Funnel Pair Detection
When you see [PROSPECTING] and [RETARGETING] campaigns with the same product/creative, treat them as a PAIR. Never propose pausing one without considering impact on the other. A "losing" prospecting campaign may still be feeding a profitable retargeting campaign.

#### Pattern 10: Retargeting Audience Refresh
IF [RETARGETING] campaign shows declining performance over 14+ days → the retargeting window may need refreshing. Propose "custom" advisory: "Consider extending the retargeting lookback window from 14d to 30d to include more warm visitors."

## Copy Generation (IMPORTANT)
- Do NOT write full ad body text. Only provide creative_direction in proposed_value.
- A separate AI content generator with full product/brand context will write the actual copy.
- Your job: identify current hook type, pick a DIFFERENT target hook, and describe the angle/tone.
- Hook types: benefit-first, curiosity, social-proof, urgency.

Available action_types: increase_budget, decrease_budget, pause, enable, refresh_creative, mutate_winner, shift_budget, create_lookalike, create_engagement_audience, prune_placements, update_placements, consolidate_adsets, apply_cost_cap, exclude_demographics, expand_audience, enable_advantage_plus, custom

Return ONLY {"proposals": [...]}:
{"proposals": [
  {
    "entity_id": "campaign/adset/ad ID",
    "entity_type": "campaign|adset|ad",
    "entity_name": "string",
    "action_type": "one of the above",
    "current_value": {"key": "value — always include relevant metrics"},
    "proposed_value": {"key": "value — NEVER empty, always include specific changes"},
    "ai_reasoning": "2-3 sentences with numbers, baseline comparison, days_running, result count. For placement changes: MUST mention learning phase reset warning and breakdown effect.",
    "impact_score": 1-10
  }
]}

No markdown, no extra keys. Return valid JSON only."""


async def analyze_account(user_id: str, ad_account_id: str | None = None, workspace_id: str | None = None) -> list[dict]:
    """
    Fetch deep insights from MCP, send to OpenAI for analysis, and save proposals to DB.
    Returns the list of generated proposals.
    """
    supabase = get_supabase()

    # Resolve ad account (scoped to workspace)
    print(f"[COPILOT] analyze_account called: user={user_id}, ws={workspace_id}, ad_account={ad_account_id}", flush=True)
    if not ad_account_id:
        query = (
            supabase.table("ad_accounts")
            .select("meta_account_id, access_token")
            .eq("user_id", user_id)
            .eq("is_active", True)
        )
        if workspace_id:
            query = query.eq("workspace_id", workspace_id)
        result = query.limit(1).maybe_single().execute()
        print(f"[COPILOT] ad_account query result: {result.data}", flush=True)
        if not result.data:
            raise ValueError("No active ad account found")
        ad_account_id = result.data["meta_account_id"]
        access_token = result.data["access_token"]
    else:
        result = (
            supabase.table("ad_accounts")
            .select("access_token")
            .eq("user_id", user_id)
            .eq("meta_account_id", ad_account_id)
            .single()
            .execute()
        )
        if not result.data:
            raise ValueError("Ad account not found")
        access_token = result.data["access_token"]

    # Fetch deep insights from MCP (campaign + adset level)
    log.info(f"Copilot: fetching insights for ad_account={ad_account_id}, workspace={workspace_id}")
    try:
        campaign_insights = await mcp_client.get_deep_ad_insights(
            ad_account_id, access_token, date_preset="last_30d", entity_level="campaign"
        )
        adset_insights = await mcp_client.get_deep_ad_insights(
            ad_account_id, access_token, date_preset="last_30d", entity_level="adset"
        )
        log.info(f"MCP insights: campaign_age={len(campaign_insights.get('by_age',[]))}, adset_age={len(adset_insights.get('by_age',[]))}")
    except MCPError as e:
        log.error(f"MCP error fetching deep insights: {e}")
        raise ValueError(f"Failed to fetch ad insights: {e}")

    # Fetch campaign list + ad creatives + compute baselines
    try:
        campaigns_data = await mcp_client.list_campaigns(ad_account_id, access_token, status_filter="active")
    except MCPError:
        campaigns_data = {"campaigns": []}

    # Fetch current ad creatives with performance (for research-backed copy generation)
    try:
        creatives_data = await mcp_client.get_ad_creatives_with_performance(
            ad_account_id, access_token, date_preset="last_30d"
        )
    except MCPError:
        creatives_data = {"ads": []}

    baselines = await calculate_account_baselines(ad_account_id, access_token, user_id=user_id)
    bl = baselines.to_dict()

    # Pre-format threshold strings (can't use ternary inside f-string format spec)
    win_str = f"${bl['win_threshold']:.2f}" if bl['win_threshold'] else "N/A"
    lose_str = f"${bl['lose_threshold']:.2f}" if bl['lose_threshold'] else "N/A"

    # Build baselines context for prompt
    baselines_prompt = f"""## Account Historical Baselines (30-day averages)
- Source: {bl['source']}
- Dominant campaign type: {bl['dominant_type']}
- Avg CPL: ${bl['avg_cpl'] or 'N/A'}  |  Winning Threshold: ≤ {win_str}  |  Losing Threshold: ≥ {lose_str}
- Avg CPA: ${bl['avg_cpa'] or 'N/A'}
- Avg ROAS: {bl['avg_roas'] or 'N/A'}x
- Avg CTR: {bl['avg_ctr']}%
- Avg CPC: ${bl['avg_cpc']}
- Avg CPM: ${bl['avg_cpm']}
- Total Spend: ${bl['total_spend']}
- Sample Size: {bl['sample_size']} ads"""

    # Build the user prompt with all data
    user_prompt = f"""Analyze this Meta ad account and generate optimization proposals.

{baselines_prompt}

## Campaign-Level Breakdown (Last 30 Days)

### By Age:
{json.dumps(campaign_insights.get("by_age", [])[:50], indent=2)}

### By Gender:
{json.dumps(campaign_insights.get("by_gender", [])[:30], indent=2)}

### By Placement:
{json.dumps(campaign_insights.get("by_placement", [])[:30], indent=2)}

## Adset-Level Breakdown (Last 30 Days)

### By Age:
{json.dumps(adset_insights.get("by_age", [])[:50], indent=2)}

### By Gender:
{json.dumps(adset_insights.get("by_gender", [])[:30], indent=2)}

### By Placement:
{json.dumps(adset_insights.get("by_placement", [])[:30], indent=2)}

## Active Campaigns:
{json.dumps(campaigns_data.get("campaigns", [])[:20], indent=2)}

## 3-Day Trend Data (for fatigue/trend detection):
{json.dumps(campaign_insights.get("trend_3d", [])[:30], indent=2)}

## Current Ad Creatives (body text, headline, CTA, performance):
{json.dumps(creatives_data.get("ads", [])[:25], indent=2)}

## Creative Pattern Analysis
Before generating refresh_creative or mutate_winner proposals, analyze the winning ads' copy patterns:
- Identify the HOOK TYPE used by each winning ad (benefit-first, curiosity, social-proof, urgency)
- For refresh_creative: write copy using a DIFFERENT hook type than the fatigued ad
- For mutate_winner: write copy using a DIFFERENT hook type than the winning ad
- Hook types:
  * Benefit-first: "[Verb] [specific outcome] [timeframe]" — leads with what user gets
  * Curiosity: "[Surprising/counterintuitive statement]" — creates information gap
  * Social-proof: "[Number] [people/companies] [outcome]" — leverages social validation
  * Urgency: "[Genuine scarcity or time limit]" — only if real, never fake

Generate 3-8 high-impact optimization proposals. Use the baselines above to judge performance — do NOT use arbitrary thresholds like "$20 CPL" or "2x ROAS".

Check for these opportunities in priority order:
1. Creative fatigue (frequency > 3.0 + declining CTR) → refresh_creative with NEW ad copy in proposed_value
2. Robin Hood (losing entity + winning entity in same account) → shift_budget with exact amount_cents
3. Winner A/B testing (winning ad running 5+ days) → mutate_winner with variation copy
4. Scale via LAL (200+ leads at profitable CPL) → create_lookalike
5. Placement waste (audience_network with 0 results) → prune_placements
6. Budget adjustments → increase_budget / decrease_budget with absolute daily_budget
7. Scale protection → apply_cost_cap"""

    # Call OpenAI
    response = await openai_client.chat.completions.create(
        model=settings.ELITE_REASONING_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=4000,
        response_format={"type": "json_object"},
    )

    raw_content = response.choices[0].message.content or "[]"
    print(f"[COPILOT] OpenAI response type={type(json.loads(raw_content)).__name__}, len={len(raw_content)}", flush=True)
    try:
        parsed = json.loads(raw_content)
        # Handle {"proposals": [...]}, plain [...], or single proposal object
        if isinstance(parsed, dict):
            if "proposals" in parsed:
                proposals = parsed["proposals"]
            elif "data" in parsed:
                proposals = parsed["data"]
            elif "entity_id" in parsed:
                # Single proposal object — wrap in list
                proposals = [parsed]
            else:
                proposals = []
        elif isinstance(parsed, list):
            proposals = parsed
        else:
            proposals = []
    except json.JSONDecodeError:
        log.error(f"Failed to parse OpenAI response: {raw_content[:200]}")
        proposals = []

    print(f"[COPILOT] Parsed {len(proposals)} proposals for workspace={workspace_id}, ad_account={ad_account_id}", flush=True)
    if not proposals:
        return []

    proposals = _deduplicate_proposals(proposals)

    # Save new proposals (keep existing pending proposals — user can reject unwanted ones)
    saved = []
    valid_actions = {
        "increase_budget", "decrease_budget", "pause", "enable",
        "reallocate", "audience_shift", "custom",
        "refresh_creative", "prune_placements", "consolidate_adsets", "apply_cost_cap",
        "mutate_winner", "shift_budget", "create_lookalike", "create_engagement_audience",
        "exclude_demographics", "update_placements", "expand_audience", "enable_advantage_plus",
    }
    for p in proposals:
        action = p.get("action_type", "custom")
        if action not in valid_actions:
            action = "custom"
        row = {
            "user_id": user_id,
            "ad_account_id": ad_account_id,
            "entity_id": str(p.get("entity_id", "")),
            "entity_type": p.get("entity_type", "campaign"),
            "entity_name": p.get("entity_name", ""),
            "action_type": action,
            "current_value": p.get("current_value", {}),
            "proposed_value": p.get("proposed_value", {}),
            "ai_reasoning": p.get("ai_reasoning", ""),
            "impact_score": min(max(int(p.get("impact_score", 5)), 1), 10),
            "status": "pending",
        }
        if workspace_id:
            row["workspace_id"] = workspace_id
        result = supabase.table("optimization_proposals").insert(row).execute()
        if result.data:
            saved.append(result.data[0])

    return saved


AD_SYSTEM_PROMPT = """You are an expert Meta Ads optimization analyst. Given a SINGLE ad's performance data, generate ONLY high-confidence proposals that are safe to auto-apply. Quality over quantity — 1-3 perfect proposals, never filler.

## Quality Gate — ask yourself before each proposal:
1. Is there enough data (30+ results) to justify this change? If not, skip or use "custom" advisory.
2. Does another proposal already fix this same problem? If yes, keep only the better one.
3. Would I auto-apply this without human review? If not, don't propose it.

## Deduplication (CRITICAL)
- ONE placement action per adset (update_placements OR enable_advantage_plus, never both).
- ONE budget action per entity. ONE demographic action per adset. ONE creative action per ad.
- Never propose "custom" alongside an executable proposal for the same issue.

## Rules
- Budget: ±30% max. proposed_value.daily_budget = absolute dollars.
- Placements: ADSET level only — entity_type="adset", entity_id=parent adset ID.
- Pause: only if 30%+ worse than baseline.
- Always reference baselines with numbers.

## Placement Rules — Advantage+ Awareness (CRITICAL)
The data tells you if placements are "Advantage+" or "Manual".

### The Breakdown Effect:
Per-placement breakdown data shows PAST performance, not predicted future. Meta intentionally spends on "expensive" placements because removing them would saturate "cheap" placements and raise their CPA. A $50 CPA placement may be enabling a $20 CPA placement.

### When Advantage+ is ON:
- IF adset cost_per_result ≤ baseline: DO NOT suggest placement changes. The algorithm is working.
- IF adset in learning (< 50 results): DO NOT suggest placement changes. Advantage+ needs time to explore.
- IF adset has 50+ results AND placement has $20+ spend with 0 results over 7+ days: MAY suggest update_placements, but MUST warn about learning reset and breakdown effect.
- EVERY placement proposal MUST include in ai_reasoning: "WARNING: Switches from Advantage+ to manual placements, resetting learning phase for 3-7 days. CPA may temporarily increase due to breakdown effect."

### When Advantage+ is OFF (Manual):
- IF adset struggling (CPA > 1.5x baseline OR learning_limited): suggest "enable_advantage_plus".
- IF placement has $20+ spend with 0 results: suggest update_placements.
- IF only 1-2 placements active: suggest enable_advantage_plus instead of further pruning.

## Ad Maturity (CRITICAL)
- < 7 days old: "custom" advisory only. No structural changes.
- 7-14 days with < 30 results: NO placement changes when Advantage+ is ON. Only prune if manual AND $20+ spent with 0 results.
- < 30 results: NEVER exclude_demographics.
- Learning phase (is_learning=true OR results < 50): NEVER change budget. NEVER change placements on Advantage+ adsets.
- Always state days_running and result count in reasoning.

## Action Types
- increase_budget / decrease_budget — adset daily budget (absolute $)
- pause — pause underperforming ad
- refresh_creative — pause + new ad with AI-generated copy. proposed_value: {"ad_id": "id", "creative_direction": "Use [target hook] instead of [current hook]. Angle: [specific direction].", "current_hook": "benefit-first", "target_hook": "curiosity", "new_cta": "CTA"}. Do NOT write full body text — only provide creative direction.
- mutate_winner — A/B test variant. proposed_value: {"ad_id": "id", "creative_direction": "Test [hook type]: [direction]", "current_hook": "type", "target_hook": "type", "new_cta": "CTA", "mutation_type": "copy"}. Do NOT write full body text — only provide creative direction.
- update_placements — set platforms/positions to KEEP. proposed_value MUST include: {"adset_id": "id", "publisher_platforms": ["facebook"], "facebook_positions": ["feed", "reels"], "removed_placements": "what removed with $ amounts"}
- exclude_demographics — narrow age/gender (30+ results required). proposed_value: {"adset_id": "id", "age_min": N, "age_max": N, "genders": [N], "excluded_segments": "details with $ amounts"}
- apply_cost_cap — COST_CAP bidding. proposed_value: {"adset_id": "id", "cost_cap": N, "bid_strategy": "cost_cap"}
- enable_advantage_plus — switch manual placements to Advantage+ for struggling adsets. proposed_value: {"adset_id": "id", "reason": "why this helps"}
- custom — advisory only

## Copy Generation
- Do NOT write full ad body text. Only provide creative_direction in proposed_value.
- A separate AI content generator with full product/brand context will write the actual copy.
- Your job: identify current hook type, pick a DIFFERENT target hook, describe the angle/tone.
- Hook types: benefit-first, curiosity, social-proof, urgency.
- For mutate_winner: "Because [ad] achieved [X] using [hook], testing [different hook] will expand reach."

Return ONLY {"proposals": [...]}:
{"proposals": [{"entity_id": "id", "entity_type": "ad|adset", "entity_name": "name", "action_type": "type", "current_value": {"must include relevant metrics"}, "proposed_value": {"must include specific changes — NEVER empty"}, "ai_reasoning": "2-3 sentences with numbers + baseline + days_running + results. Placement changes MUST warn about learning phase reset.", "impact_score": 1-10}]}

No markdown, no extra keys. Return valid JSON only."""


async def analyze_specific_ad(
    user_id: str,
    ad_id: str,
    campaign_id: str | None = None,
    ad_name: str | None = None,
    workspace_id: str | None = None,
) -> list[dict]:
    """
    Fetch performance data for a single ad and generate focused proposals.
    """
    supabase = get_supabase()

    # Resolve ad account (scoped to workspace)
    query = (
        supabase.table("ad_accounts")
        .select("meta_account_id, access_token")
        .eq("user_id", user_id)
        .eq("is_active", True)
    )
    if workspace_id:
        query = query.eq("workspace_id", workspace_id)
    result = query.limit(1).maybe_single().execute()
    if not result.data:
        raise ValueError("No active ad account found")
    ad_account_id = result.data["meta_account_id"]
    access_token = result.data["access_token"]

    # Fetch ad creatives with performance (includes per-ad spend, CTR, etc.)
    try:
        creatives_data = await mcp_client.get_ad_creatives_with_performance(
            ad_account_id, access_token, date_preset="last_30d"
        )
    except MCPError:
        creatives_data = {"ads": []}

    # Find this specific ad's creative data
    target_ad_creative = None
    for ad_item in creatives_data.get("ads", []):
        if str(ad_item.get("id")) == str(ad_id):
            target_ad_creative = ad_item
            break

    # Fetch actual adset budget from Meta (so AI doesn't hallucinate)
    adset_budget_info = ""
    if target_ad_creative and target_ad_creative.get("adset_id"):
        try:
            import httpx
            adset_id = target_ad_creative["adset_id"]
            resp = httpx.get(
                f"https://graph.facebook.com/v21.0/{adset_id}",
                params={"fields": "daily_budget,lifetime_budget,bid_strategy,bid_amount,targeting,targeting_optimization", "access_token": access_token},
                timeout=10,
            )
            adset_info = resp.json()
            daily_b = adset_info.get("daily_budget")
            lifetime_b = adset_info.get("lifetime_budget")
            bid = adset_info.get("bid_strategy", "")
            if daily_b:
                adset_budget_info = f"\n- ACTUAL Adset Daily Budget: ${int(daily_b)/100:.2f}/day (this is the REAL budget — do NOT guess or invent different numbers)"
            elif lifetime_b and int(lifetime_b) > 0:
                adset_budget_info = f"\n- ACTUAL Adset Lifetime Budget: ${int(lifetime_b)/100:.2f}"
            if bid:
                adset_budget_info += f"\n- Bid Strategy: {bid}"
            # Advantage+ placement detection
            targeting = adset_info.get("targeting", {})
            publisher_platforms = targeting.get("publisher_platforms")
            if not publisher_platforms:
                adset_budget_info += "\n- Placements: Advantage+ (automatic — Meta decides placement distribution, all platforms enabled)"
            else:
                adset_budget_info += f"\n- Placements: Manual — {', '.join(publisher_platforms)}"
            # Advantage+ audience detection
            targeting_opt = adset_info.get("targeting_optimization", "")
            if targeting_opt:
                adset_budget_info += f"\n- Targeting Optimization: {targeting_opt}"
        except Exception:
            pass

    # Account baselines for comparison
    baselines = await calculate_account_baselines(ad_account_id, access_token, user_id=user_id)
    bl = baselines.to_dict()

    win_str = f"${bl['win_threshold']:.2f}" if bl['win_threshold'] else "N/A"
    lose_str = f"${bl['lose_threshold']:.2f}" if bl['lose_threshold'] else "N/A"

    baselines_prompt = f"""## Account Historical Baselines (30-day averages)
- Dominant campaign type: {bl['dominant_type']}
- Avg CPL: ${bl['avg_cpl'] or 'N/A'}  |  Winning: ≤ {win_str}  |  Losing: ≥ {lose_str}
- Avg CPA: ${bl['avg_cpa'] or 'N/A'}
- Avg ROAS: {bl['avg_roas'] or 'N/A'}x
- Avg CTR: {bl['avg_ctr']}%
- Avg CPC: ${bl['avg_cpc']}
- Avg CPM: ${bl['avg_cpm']}"""

    creative_str = json.dumps(target_ad_creative, indent=2) if target_ad_creative else "No creative data available"

    # Fetch per-segment breakdowns (age, gender, placement) for data-backed decisions
    segment_info = ""
    if ad_id:
        import httpx as _httpx
        try:
            # Age breakdown
            resp = _httpx.get(
                f"https://graph.facebook.com/v21.0/{ad_id}/insights",
                params={"fields": "spend,clicks,actions,cost_per_action_type", "breakdowns": "age", "date_preset": "maximum", "access_token": access_token},
                timeout=15,
            )
            age_rows = resp.json().get("data", [])
            if age_rows:
                segment_info += "\n\n## Per-Age Segment Performance"
                for r in age_rows:
                    actions = {a["action_type"]: a["value"] for a in r.get("actions", [])}
                    regs = actions.get("complete_registration", actions.get("lead", actions.get("onsite_conversion.messaging_first_reply", "0")))
                    cpas = {a["action_type"]: a["value"] for a in r.get("cost_per_action_type", [])}
                    cpr = cpas.get("complete_registration", cpas.get("lead", "-"))
                    segment_info += f"\n- Age {r.get('age', '?')}: Spend ${float(r.get('spend', 0)):.2f}, Clicks {r.get('clicks', 0)}, Results {regs}, Cost/Result ${cpr}"

            # Gender breakdown
            resp = _httpx.get(
                f"https://graph.facebook.com/v21.0/{ad_id}/insights",
                params={"fields": "spend,clicks,actions,cost_per_action_type", "breakdowns": "gender", "date_preset": "maximum", "access_token": access_token},
                timeout=15,
            )
            gender_rows = resp.json().get("data", [])
            if gender_rows:
                segment_info += "\n\n## Per-Gender Segment Performance"
                for r in gender_rows:
                    actions = {a["action_type"]: a["value"] for a in r.get("actions", [])}
                    regs = actions.get("complete_registration", actions.get("lead", actions.get("onsite_conversion.messaging_first_reply", "0")))
                    cpas = {a["action_type"]: a["value"] for a in r.get("cost_per_action_type", [])}
                    cpr = cpas.get("complete_registration", cpas.get("lead", "-"))
                    segment_info += f"\n- {r.get('gender', '?')}: Spend ${float(r.get('spend', 0)):.2f}, Clicks {r.get('clicks', 0)}, Results {regs}, Cost/Result ${cpr}"

            # Placement breakdown
            resp = _httpx.get(
                f"https://graph.facebook.com/v21.0/{ad_id}/insights",
                params={"fields": "spend,clicks,actions", "breakdowns": "publisher_platform,platform_position", "date_preset": "maximum", "access_token": access_token},
                timeout=15,
            )
            place_rows = resp.json().get("data", [])
            if place_rows:
                segment_info += "\n\n## Per-Placement Performance"
                for r in sorted(place_rows, key=lambda x: float(x.get("spend", 0)), reverse=True)[:8]:
                    actions = {a["action_type"]: a["value"] for a in r.get("actions", [])}
                    regs = actions.get("complete_registration", actions.get("lead", "0"))
                    segment_info += f"\n- {r.get('publisher_platform', '?')} {r.get('platform_position', '?')}: Spend ${float(r.get('spend', 0)):.2f}, Clicks {r.get('clicks', 0)}, Results {regs}"
        except Exception:
            pass

    # Fetch FRESH ad maturity info directly from Meta (not stale audit data)
    ad_maturity_info = _fetch_fresh_ad_maturity(ad_id, access_token)

    user_prompt = f"""Analyze this SPECIFIC ad and generate optimization proposals.

## Ad Being Analyzed
- Ad ID: {ad_id}
- Ad Name: {ad_name or 'Unknown'}
- Campaign ID: {campaign_id or 'Unknown'}{adset_budget_info}{ad_maturity_info}

{baselines_prompt}

## Ad Creative & Performance (Last 30 Days):
{creative_str}
{segment_info}

## Other Ads for Context (to avoid duplicate copy):
{json.dumps(creatives_data.get("ads", [])[:10], indent=2)}

## Creative Pattern Analysis
If proposing refresh_creative or mutate_winner:
- Identify the hook type of the current ad (benefit-first, curiosity, social-proof, urgency)
- Write NEW copy using a DIFFERENT hook type to test audience responsiveness
- Hook types: benefit-first (leads with outcome), curiosity (information gap), social-proof (numbers/validation), urgency (genuine scarcity only)

Generate 1-3 high-confidence proposals for this specific ad. Use the segment breakdowns above for data-backed targeting/placement decisions. Compare performance to account baselines.

IMPORTANT: Every proposal MUST have populated current_value (showing current metrics/state) and proposed_value (showing exact change). Never leave them empty — the frontend displays these to the user."""

    response = await openai_client.chat.completions.create(
        model=settings.ELITE_REASONING_MODEL,
        messages=[
            {"role": "system", "content": AD_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=2500,
        response_format={"type": "json_object"},
    )

    raw_content = response.choices[0].message.content or "[]"
    try:
        parsed = json.loads(raw_content)
        if isinstance(parsed, dict):
            if "proposals" in parsed:
                proposals = parsed["proposals"]
            elif "data" in parsed:
                proposals = parsed["data"]
            elif "entity_id" in parsed:
                proposals = [parsed]
            else:
                proposals = []
        elif isinstance(parsed, list):
            proposals = parsed
        else:
            proposals = []
    except json.JSONDecodeError:
        log.error(f"Failed to parse OpenAI response for ad analysis: {raw_content[:200]}")
        proposals = []

    if not proposals:
        return []

    proposals = _deduplicate_proposals(proposals)

    # Save new proposals (keep existing — user can reject unwanted ones)
    saved = []
    valid_actions = {
        "increase_budget", "decrease_budget", "pause", "enable",
        "refresh_creative", "prune_placements", "apply_cost_cap",
        "mutate_winner", "custom", "create_engagement_audience",
        "exclude_demographics", "update_placements", "expand_audience", "enable_advantage_plus",
    }
    for p in proposals:
        action = p.get("action_type", "custom")
        if action not in valid_actions:
            action = "custom"
        row = {
            "user_id": user_id,
            "ad_account_id": ad_account_id,
            "entity_id": str(p.get("entity_id", ad_id)),
            "entity_type": p.get("entity_type", "ad"),
            "entity_name": p.get("entity_name", ad_name or ""),
            "action_type": action,
            "current_value": p.get("current_value", {}),
            "proposed_value": p.get("proposed_value", {}),
            "ai_reasoning": p.get("ai_reasoning", ""),
            "impact_score": min(max(int(p.get("impact_score", 5)), 1), 10),
            "status": "pending",
        }
        if workspace_id:
            row["workspace_id"] = workspace_id
        result = supabase.table("optimization_proposals").insert(row).execute()
        if result.data:
            saved.append(result.data[0])

    return saved


async def generate_diagnosis_fix(
    user_id: str, ad_id: str, diagnosis: str,
    ad_name: str = "", adset_id: str = "", campaign_id: str = "",
    workspace_id: str | None = None,
) -> list[dict]:
    """Generate a targeted fix proposal from an audit diagnosis."""
    supabase = get_supabase()

    query = supabase.table("ad_accounts").select("meta_account_id, access_token").eq("user_id", user_id).eq("is_active", True)
    if workspace_id:
        query = query.eq("workspace_id", workspace_id)
    result = query.limit(1).maybe_single().execute()
    if not result.data:
        raise ValueError("No active ad account found")
    ad_account_id = result.data["meta_account_id"]
    access_token = result.data["access_token"]

    # Auto-resolve adset_id from ad_id if not provided
    import httpx
    if not adset_id and ad_id:
        try:
            resp = httpx.get(
                f"https://graph.facebook.com/v21.0/{ad_id}",
                params={"fields": "adset_id", "access_token": access_token},
                timeout=10,
            )
            adset_id = resp.json().get("adset_id", "")
        except Exception:
            pass

    # Fetch actual adset + ad info from Meta for full context
    budget_info = ""
    ad_creative_info = ""
    if adset_id:
        try:
            resp = httpx.get(
                f"https://graph.facebook.com/v21.0/{adset_id}",
                params={"fields": "daily_budget,lifetime_budget,bid_strategy,targeting,targeting_optimization", "access_token": access_token},
                timeout=10,
            )
            info = resp.json()
            db = info.get("daily_budget")
            if db:
                budget_info = f"\n- ACTUAL Daily Budget: ${int(db)/100:.2f}/day"
            targeting = info.get("targeting", {})
            budget_info += f"\n- Current Age: {targeting.get('age_min', 18)}-{targeting.get('age_max', 65)}"
            genders = targeting.get("genders", "all")
            budget_info += f"\n- Current Genders: {genders}"
            pubs = targeting.get("publisher_platforms", [])
            if pubs:
                budget_info += f"\n- Current Platforms: Manual — {', '.join(pubs)}"
            else:
                budget_info += "\n- Placements: Advantage+ (automatic — Meta decides placement distribution, all platforms enabled)"
            targeting_opt = info.get("targeting_optimization", "")
            if targeting_opt:
                budget_info += f"\n- Targeting Optimization: {targeting_opt}"
            interests = targeting.get("flexible_spec", [])
            if interests:
                names = [i.get("name", "") for spec in interests for i in spec.get("interests", [])]
                if names:
                    budget_info += f"\n- Current Interests: {', '.join(names[:5])}"
        except Exception:
            pass

    # Fetch ad creative for refresh_creative proposals
    if ad_id:
        try:
            resp = httpx.get(
                f"https://graph.facebook.com/v21.0/{ad_id}",
                params={"fields": "creative{body,title,call_to_action_type}", "access_token": access_token},
                timeout=10,
            )
            ad_info = resp.json()
            creative = ad_info.get("creative", {})
            if creative.get("body"):
                ad_creative_info = f"\n\n## Current Ad Creative\n- Headline: {creative.get('title', 'N/A')}\n- Body: {creative.get('body', 'N/A')}\n- CTA: {creative.get('call_to_action_type', 'N/A')}"
        except Exception:
            pass

    # Fetch per-segment breakdowns for data-backed targeting decisions
    segment_info = ""
    if ad_id:
        try:
            # Age breakdown
            resp = httpx.get(
                f"https://graph.facebook.com/v21.0/{ad_id}/insights",
                params={"fields": "spend,clicks,actions,cost_per_action_type", "breakdowns": "age", "date_preset": "maximum", "access_token": access_token},
                timeout=15,
            )
            age_rows = resp.json().get("data", [])
            if age_rows:
                segment_info += "\n\n## Per-Age Segment Performance"
                for r in age_rows:
                    actions = {a["action_type"]: a["value"] for a in r.get("actions", [])}
                    regs = actions.get("complete_registration", actions.get("lead", actions.get("onsite_conversion.messaging_first_reply", "0")))
                    cpas = {a["action_type"]: a["value"] for a in r.get("cost_per_action_type", [])}
                    cpr = cpas.get("complete_registration", cpas.get("lead", "-"))
                    segment_info += f"\n- Age {r.get('age', '?')}: Spend ${float(r.get('spend', 0)):.2f}, Clicks {r.get('clicks', 0)}, Results {regs}, Cost/Result ${cpr}"

            # Gender breakdown
            resp = httpx.get(
                f"https://graph.facebook.com/v21.0/{ad_id}/insights",
                params={"fields": "spend,clicks,actions,cost_per_action_type", "breakdowns": "gender", "date_preset": "maximum", "access_token": access_token},
                timeout=15,
            )
            gender_rows = resp.json().get("data", [])
            if gender_rows:
                segment_info += "\n\n## Per-Gender Segment Performance"
                for r in gender_rows:
                    actions = {a["action_type"]: a["value"] for a in r.get("actions", [])}
                    regs = actions.get("complete_registration", actions.get("lead", actions.get("onsite_conversion.messaging_first_reply", "0")))
                    cpas = {a["action_type"]: a["value"] for a in r.get("cost_per_action_type", [])}
                    cpr = cpas.get("complete_registration", cpas.get("lead", "-"))
                    segment_info += f"\n- {r.get('gender', '?')}: Spend ${float(r.get('spend', 0)):.2f}, Clicks {r.get('clicks', 0)}, Results {regs}, Cost/Result ${cpr}"

            # Placement breakdown
            resp = httpx.get(
                f"https://graph.facebook.com/v21.0/{ad_id}/insights",
                params={"fields": "spend,clicks,actions", "breakdowns": "publisher_platform,platform_position", "date_preset": "maximum", "access_token": access_token},
                timeout=15,
            )
            place_rows = resp.json().get("data", [])
            if place_rows:
                segment_info += "\n\n## Per-Placement Performance"
                for r in sorted(place_rows, key=lambda x: float(x.get("spend", 0)), reverse=True)[:8]:
                    actions = {a["action_type"]: a["value"] for a in r.get("actions", [])}
                    regs = actions.get("complete_registration", actions.get("lead", "0"))
                    segment_info += f"\n- {r.get('publisher_platform', '?')} {r.get('platform_position', '?')}: Spend ${float(r.get('spend', 0)):.2f}, Clicks {r.get('clicks', 0)}, Results {regs}"
        except Exception:
            pass

    # Fetch FRESH ad maturity info directly from Meta (not stale audit data)
    ad_maturity_info_fix = _fetch_fresh_ad_maturity(ad_id, access_token)

    # Fetch audit data for cross-campaign context only (stale is OK for relative rankings)
    audit_result = None
    try:
        audit_result = (
            supabase.table("account_audits")
            .select("winning_ads")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )
    except Exception:
        pass

    # Account baselines for comparison
    baselines_fix = await calculate_account_baselines(ad_account_id, access_token, user_id=user_id)
    bl_fix = baselines_fix.to_dict()
    baselines_prompt_fix = f"""
## Account Baselines (30-day averages)
- Avg CPL: ${bl_fix['avg_cpl'] or 'N/A'} | Avg CPA: ${bl_fix['avg_cpa'] or 'N/A'} | Avg ROAS: {bl_fix['avg_roas'] or 'N/A'}x
- Avg CTR: {bl_fix['avg_ctr']}% | Avg CPC: ${bl_fix['avg_cpc']} | Avg CPM: ${bl_fix['avg_cpm']}"""

    # Cross-campaign context from latest audit (lightweight — just names, objectives, CPR, budgets)
    cross_campaign_info = ""
    try:
        if audit_result and audit_result.data:
            winning_raw = audit_result.data.get("winning_ads", "[]")
            all_audit_ads = json.loads(winning_raw) if isinstance(winning_raw, str) else winning_raw
            if all_audit_ads and len(all_audit_ads) > 1:
                cross_campaign_info = "\n\n## Other Active Ads in Account (for cross-campaign context)"
                for other_ad in sorted(all_audit_ads, key=lambda x: x.get("spend", 0), reverse=True):
                    if str(other_ad.get("ad_id")) == str(ad_id):
                        continue  # skip the ad being analyzed
                    obj = other_ad.get("objective", "?")
                    cpr = other_ad.get("cost_per_result")
                    cpr_str = f"${cpr:.2f}" if cpr else "N/A"
                    cpm_val = other_ad.get("cpm", 0)
                    spend = other_ad.get("spend", 0)
                    results = other_ad.get("results", 0)
                    rt = other_ad.get("result_type", "?")
                    verdict = other_ad.get("verdict", "?")
                    cross_campaign_info += f"\n- {other_ad.get('ad_name', '?')}: {obj} | Spend ${spend:.0f} | {results} {rt} | CPR {cpr_str} | CPM ${cpm_val:.0f} | {verdict}"
                cross_campaign_info += "\n\nUse this to identify: objective mismatches (OUTCOME_SALES vs OUTCOME_LEADS for same product), budget imbalances (best CPR ad has lowest budget), and CPM outliers."
    except Exception:
        pass

    prompt = f"""The audit system diagnosed this ad with a specific issue. Generate a MULTI-STEP OPTIMIZATION PLAN — multiple proposals ordered by priority.

## Ad Details
- Ad ID: {ad_id}
- Ad Name: {ad_name or 'Unknown'}
- Adset ID: {adset_id or 'Unknown'}
- Campaign ID: {campaign_id or 'Unknown'}{budget_info}{ad_maturity_info_fix}{ad_creative_info}{segment_info}
{baselines_prompt_fix}{cross_campaign_info}

## Audit Diagnosis
{diagnosis}

## Instructions
You have REAL per-segment data, account baselines, AND cross-campaign context above. Generate 1-3 high-confidence proposals only. Every proposal will be auto-applied — no filler.

If the cross-campaign data reveals a strategic insight (e.g., this ad uses OUTCOME_SALES but similar ads in the account get cheaper results with OUTCOME_LEADS, or this ad's CPM is 2x+ other campaigns with the same objective), include ONE "custom" advisory about it. This is the ONE exception where a "custom" advisory alongside an executable proposal is allowed — only for cross-campaign strategic insights that can't be auto-applied.

### Rules:
- ONE placement action per adset (update_placements OR enable_advantage_plus, never both).
- ONE budget action per entity. ONE demographic action per adset. ONE creative action per ad.
- Never add a "custom" advisory if you already have an executable proposal for the same problem.
- Compare this ad's metrics to the baselines above — cite specific numbers.
- If the ad has < 30 results, do NOT propose exclude_demographics (sample too small).

### Placement Decision Framework — Advantage+ Awareness (CRITICAL):

**The Breakdown Effect**: Per-placement breakdown data shows PAST performance, not predicted future. Meta intentionally spends on "expensive" placements because removing them would saturate "cheap" ones. A $50 CPA placement may enable a $20 CPA placement.

**When Advantage+ is ON:**
- IF adset cost_per_result ≤ baseline: DO NOT suggest placement changes. The algorithm is working.
- IF adset in learning (< 50 results): DO NOT suggest placement changes. Advantage+ needs exploration time.
- IF adset has 50+ results AND placement has $20+ spend with 0 results over 7+ days: MAY suggest update_placements, but MUST warn: "WARNING: Switches from Advantage+ to manual, resetting learning for 3-7 days. CPA may increase due to breakdown effect."

**When Advantage+ is OFF (Manual):**
- IF adset struggling (CPA > 1.5x baseline): suggest "enable_advantage_plus" to open inventory.
- IF placement has $20+ spend with 0 results: suggest update_placements.
- IF only 1-2 placements active: suggest enable_advantage_plus instead of further pruning.

### Other Decision Frameworks:

**Demographics (use per-age/gender data):**
- Age segments with $0 results + $20+ spend AND 30+ total results → "exclude_demographics"

**Creative:**
- Low CTR diagnosis → "refresh_creative" with genuinely different hook type

**Budget:**
- Only on mature ads (50+ results, not learning). ±30% max.

### Available action_types:
- "exclude_demographics" — entity_type "adset". proposed_value MUST include: {{"adset_id": "id", "age_min": 45, "age_max": 65, "genders": [1], "excluded_segments": "details with $ amounts"}}
- "update_placements" — entity_type "adset". proposed_value MUST include: {{"adset_id": "id", "publisher_platforms": ["facebook", "audience_network"], "facebook_positions": ["feed", "reels"], "removed_placements": "what removed with $ amounts"}}. NEVER leave publisher_platforms or facebook_positions empty.
- "enable_advantage_plus" — entity_type "adset". For struggling manual-placement adsets. proposed_value: {{"adset_id": "id", "reason": "why switching helps — cite CPA vs baseline, learning_limited status, or low placement count"}}
- "refresh_creative" — entity_type "ad". proposed_value: {{"ad_id": "id", "creative_direction": "Use [target hook] instead of [current hook]. Angle: [direction].", "current_hook": "type", "target_hook": "type", "new_cta": "CTA"}}. Do NOT write full body text — only provide creative direction.
- "decrease_budget" / "increase_budget" — entity_type "adset". proposed_value: {{"adset_id": "id", "daily_budget": amount}}
- "custom" — advisory only. proposed_value: {{"recommendation": "specific action with metrics and timeline"}}

### CRITICAL OUTPUT RULES:
1. Generate 1-3 high-confidence proposals only. No filler.
2. current_value MUST show current state with real metrics (e.g. {{"adset_id": "id", "days_running": 11, "results": 11, "is_learning": true, "cpm": 116, "ctr": 6.89, "daily_budget": 20, "placements_mode": "advantage_plus"}})
3. proposed_value MUST show exact change — NEVER leave empty or just {{"adset_id": "id"}}.
4. Use REAL numbers from the segment data above.
5. entity_type for targeting/placement changes MUST be "adset".
6. Placement change proposals MUST warn about 3-7 day learning phase reset in ai_reasoning.

Return {{"proposals": [1-3 proposals ordered by priority, each with fully populated current_value and proposed_value]. Return valid JSON only.}}"""

    response = await openai_client.chat.completions.create(
        model=settings.ELITE_REASONING_MODEL,
        messages=[
            {"role": "system", "content": "You are a Meta Ads optimization strategist. Given a diagnosis and real segment data, generate a multi-step optimization plan with 2-4 proposals covering different dimensions (demographics, placements, monitoring). Return JSON only."},
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=4000,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            if "proposals" in parsed:
                proposals = parsed["proposals"]
            elif "entity_id" in parsed:
                proposals = [parsed]
            else:
                proposals = []
        elif isinstance(parsed, list):
            proposals = parsed
        else:
            proposals = []
    except json.JSONDecodeError:
        return []

    if not proposals:
        return []

    proposals = _deduplicate_proposals(proposals)

    valid_actions = {
        "increase_budget", "decrease_budget", "pause", "enable",
        "refresh_creative", "prune_placements", "apply_cost_cap",
        "mutate_winner", "custom", "create_engagement_audience",
        "exclude_demographics", "update_placements", "expand_audience", "enable_advantage_plus",
    }
    saved = []
    for p in proposals:
        action = p.get("action_type", "custom")
        if action not in valid_actions:
            action = "custom"
        row = {
            "user_id": user_id,
            "ad_account_id": ad_account_id,
            "entity_id": str(p.get("entity_id", adset_id or ad_id)),
            "entity_type": p.get("entity_type", "ad"),
            "entity_name": p.get("entity_name", ad_name or ""),
            "action_type": action,
            "current_value": p.get("current_value", {}),
            "proposed_value": p.get("proposed_value", {}),
            "ai_reasoning": p.get("ai_reasoning", f"Fix for: {diagnosis}"),
            "impact_score": min(max(int(p.get("impact_score", 7)), 1), 10),
            "status": "pending",
        }
        if workspace_id:
            row["workspace_id"] = workspace_id
        result = supabase.table("optimization_proposals").insert(row).execute()
        if result.data:
            saved.append(result.data[0])
    return saved


async def apply_proposal(user_id: str, proposal_id: str) -> dict:
    """Execute a single approved optimization proposal via MCP."""
    supabase = get_supabase()

    # Fetch the proposal
    result = (
        supabase.table("optimization_proposals")
        .select("*")
        .eq("id", proposal_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not result.data:
        raise ValueError("Proposal not found")

    proposal = result.data
    if proposal["status"] not in ("pending", "approved"):
        raise ValueError(f"Cannot apply proposal with status '{proposal['status']}'")

    # Get access token
    account = (
        supabase.table("ad_accounts")
        .select("access_token")
        .eq("user_id", user_id)
        .eq("meta_account_id", proposal["ad_account_id"])
        .single()
        .execute()
    )
    if not account.data:
        raise ValueError("Ad account not found")
    access_token = account.data["access_token"]

    action = proposal["action_type"]
    entity_id = proposal["entity_id"]
    proposed = proposal["proposed_value"]

    try:
        if action in ("increase_budget", "decrease_budget"):
            daily_budget = proposed.get("daily_budget")
            if daily_budget is not None:
                # Convert to cents if it looks like dollars
                if isinstance(daily_budget, (int, float)) and daily_budget < 1000:
                    daily_budget = int(daily_budget * 100)
                mcp_result = await mcp_client.update_adset_budget(
                    entity_id, access_token, daily_budget=int(daily_budget)
                )
            else:
                raise ValueError("No budget value in proposed_value")

        elif action == "pause":
            mcp_result = await mcp_client.update_entity_status(
                entity_id, "PAUSED", access_token
            )

        elif action == "enable":
            mcp_result = await mcp_client.update_entity_status(
                entity_id, "ACTIVE", access_token
            )

        elif action == "refresh_creative":
            # Pause fatigued ad + create new ad with AI-generated copy
            ad_id = proposed.get("ad_id", entity_id)
            new_body = proposed.get("new_body_text", "")
            new_cta = proposed.get("new_cta", "")

            # Pause the old ad first
            await mcp_client.update_entity_status(ad_id, "PAUSED", access_token)

            if new_body:
                # Use duplicate_ad_with_mutations to create fresh ad
                mcp_result = await mcp_client.duplicate_ad_with_mutations(
                    proposal["ad_account_id"], ad_id, access_token,
                    new_body_text=new_body, new_cta=new_cta, new_name_suffix="Refresh",
                )
                if mcp_result.get("success"):
                    mcp_result["note"] = "Fatigued ad paused + new ad created with fresh copy"
            else:
                # Fallback: trigger generic draft generation
                try:
                    await generate_drafts(user_id)
                    mcp_result = {"success": True, "note": "Ad paused + draft generation triggered"}
                except Exception as e:
                    log.warning(f"Draft generation after refresh_creative failed: {e}")
                    mcp_result = {"success": True, "note": "Ad paused, draft generation failed — generate manually"}

        elif action == "mutate_winner":
            # Duplicate winning ad with copy/CTA variation for A/B test
            ad_id = proposed.get("ad_id", entity_id)
            new_body = proposed.get("new_body_text", "")
            new_cta = proposed.get("new_cta", "")
            suffix = proposed.get("mutation_type", "B")

            mcp_result = await mcp_client.duplicate_ad_with_mutations(
                proposal["ad_account_id"], ad_id, access_token,
                new_body_text=new_body, new_cta=new_cta,
                new_name_suffix=f"Variant-{suffix}",
            )

        elif action == "shift_budget":
            # Robin Hood: move budget from loser to winner
            from_id = proposed.get("from_entity")
            to_id = proposed.get("to_entity")
            amount = proposed.get("amount_cents")
            if not from_id or not to_id or not amount:
                raise ValueError("shift_budget requires from_entity, to_entity, and amount_cents")
            # Convert dollars to cents if needed
            if isinstance(amount, float) and amount < 1000:
                amount = int(amount * 100)
            mcp_result = await mcp_client.shift_budget_between_entities(
                from_id, to_id, int(amount), access_token
            )

        elif action == "create_lookalike":
            # Auto-create LAL from a winning campaign
            campaign_id = proposed.get("campaign_id", entity_id)
            country = proposed.get("country_code", "PK")
            ratio = proposed.get("ratio", 0.01)
            mcp_result = await mcp_client.create_lookalike_from_campaign(
                proposal["ad_account_id"], campaign_id, access_token,
                country_code=country, ratio=ratio,
            )
            # create_lookalike_from_campaign returns audience_id on success, not "success" key
            if mcp_result.get("audience_id"):
                mcp_result["success"] = True
                _register_audience(
                    supabase, user_id, proposal.get("workspace_id"), None,
                    mcp_result["audience_id"],
                    mcp_result.get("name", f"LAL from campaign {campaign_id}"),
                    "LAL", origin_audience_id=mcp_result.get("origin_audience_id"),
                )

        elif action == "prune_placements":
            # Exclude wasteful placements from adset targeting
            exclude = proposed.get("exclude_placements", proposed.get("exclude_publisher_platforms", []))
            if not exclude:
                raise ValueError("No placements to exclude in proposed_value")
            # entity_id should be the adset ID
            adset_id = proposed.get("adset_id", entity_id)
            mcp_result = await mcp_client.update_adset_targeting(
                adset_id, access_token, exclude_publisher_platforms=exclude
            )

        elif action == "exclude_demographics":
            adset_id = proposed.get("adset_id", entity_id)
            kwargs: dict = {}
            if proposed.get("age_min") is not None:
                kwargs["age_min"] = int(proposed["age_min"])
            if proposed.get("age_max") is not None:
                kwargs["age_max"] = int(proposed["age_max"])
            if proposed.get("genders"):
                kwargs["genders"] = proposed["genders"]
            if not kwargs:
                raise ValueError("No demographic constraints specified")
            if kwargs.get("age_min") and (kwargs["age_min"] < 18 or kwargs["age_min"] > 65):
                raise ValueError("age_min must be 18-65")
            if kwargs.get("age_max") and (kwargs["age_max"] < 18 or kwargs["age_max"] > 65):
                raise ValueError("age_max must be 18-65")
            mcp_result = await mcp_client.update_adset_targeting(adset_id, access_token, **kwargs)

        elif action == "update_placements":
            adset_id = proposed.get("adset_id", entity_id)
            kwargs = {}
            if proposed.get("publisher_platforms"):
                kwargs["publisher_platforms"] = proposed["publisher_platforms"]
            if proposed.get("facebook_positions"):
                kwargs["facebook_positions"] = proposed["facebook_positions"]
            if proposed.get("instagram_positions"):
                kwargs["instagram_positions"] = proposed["instagram_positions"]
            if not kwargs:
                raise ValueError("No placement config specified")
            mcp_result = await mcp_client.update_adset_targeting(adset_id, access_token, **kwargs)

        elif action == "create_engagement_audience":
            page_id = proposed.get("page_id")
            if not page_id:
                raise ValueError("page_id required for create_engagement_audience")
            engagement_type = proposed.get("engagement_type", "PAGE_ENGAGEMENT")
            retention_days = proposed.get("retention_days", 365)
            audience_name = proposed.get("audience_name", f"Engagers - {retention_days}d")
            mcp_result = await mcp_client.create_engagement_custom_audience(
                proposal["ad_account_id"], audience_name, page_id, access_token,
                retention_days=retention_days, engagement_type=engagement_type,
            )
            if mcp_result.get("audience_id"):
                mcp_result["success"] = True
                _register_audience(
                    supabase, user_id, proposal.get("workspace_id"), None,
                    mcp_result["audience_id"], audience_name, "ENGAGEMENT",
                )

        elif action == "expand_audience":
            adset_id = proposed.get("adset_id", entity_id)
            mcp_result = await mcp_client.update_adset_targeting(
                adset_id, access_token, enable_advantage_audience=True
            )

        elif action == "enable_advantage_plus":
            # Switch manual placements to Advantage+ by removing publisher_platforms from targeting
            # We fetch current targeting, strip placement keys, and re-post
            adset_id = proposed.get("adset_id", entity_id)
            import httpx as _httpx_apply
            try:
                # Fetch current targeting to preserve geo/age/interests
                fetch_resp = _httpx_apply.get(
                    f"https://graph.facebook.com/v21.0/{adset_id}",
                    params={"fields": "targeting", "access_token": access_token},
                    timeout=10,
                )
                current_targeting = fetch_resp.json().get("targeting", {})

                # Remove placement restrictions — this enables Advantage+
                for key in ["publisher_platforms", "facebook_positions", "instagram_positions",
                            "messenger_positions", "audience_network_positions"]:
                    current_targeting.pop(key, None)

                # Update with cleaned targeting
                update_resp = _httpx_apply.post(
                    f"https://graph.facebook.com/v21.0/{adset_id}",
                    params={"access_token": access_token},
                    data={"targeting": json.dumps(current_targeting)},
                    timeout=15,
                )
                result_data = update_resp.json()
                if result_data.get("success"):
                    mcp_result = {"success": True, "note": "Switched to Advantage+ placements — removed manual platform restrictions"}
                else:
                    mcp_result = result_data
            except Exception as e:
                raise ValueError(f"Failed to enable Advantage+ placements: {e}")

        elif action == "consolidate_adsets":
            # Pause loser adset + increase winner budget
            loser_id = proposed.get("loser_adset_id", entity_id)
            winner_id = proposed.get("winner_adset_id")
            budget_transfer = proposed.get("budget_transfer")
            if not winner_id:
                raise ValueError("No winner_adset_id in proposed_value")
            # Pause the loser
            pause_result = await mcp_client.update_entity_status(
                loser_id, "PAUSED", access_token
            )
            if pause_result.get("success") and budget_transfer:
                # Convert to cents if it looks like dollars
                if isinstance(budget_transfer, (int, float)) and budget_transfer < 1000:
                    budget_transfer = int(budget_transfer * 100)
                await mcp_client.update_adset_budget(
                    winner_id, access_token, daily_budget=int(budget_transfer)
                )
            mcp_result = {"success": True, "paused": loser_id, "boosted": winner_id}

        elif action == "apply_cost_cap":
            # Switch adset bid strategy to COST_CAP
            bid_amount = proposed.get("bid_amount")
            if bid_amount is None:
                raise ValueError("No bid_amount in proposed_value for cost cap")
            # Convert to cents if it looks like dollars
            if isinstance(bid_amount, (int, float)) and bid_amount < 1000:
                bid_amount = int(bid_amount * 100)
            adset_id = proposed.get("adset_id", entity_id)
            mcp_result = await mcp_client.update_adset_targeting(
                adset_id, access_token, bid_strategy="COST_CAP", bid_amount=int(bid_amount)
            )

        elif action in ("reallocate", "audience_shift", "custom"):
            # These are advisory — mark as applied without MCP call
            mcp_result = {"success": True, "note": "Advisory proposal marked as applied"}

        else:
            raise ValueError(f"Unknown action type: {action}")

        if mcp_result.get("success"):
            supabase.table("optimization_proposals").update({
                "status": "applied",
                "applied_at": "now()",
            }).eq("id", proposal_id).execute()
            return {"success": True, "proposal_id": proposal_id, "result": mcp_result}
        else:
            supabase.table("optimization_proposals").update({
                "status": "failed",
            }).eq("id", proposal_id).execute()
            return {"success": False, "proposal_id": proposal_id, "error": mcp_result.get("error", "Unknown error")}

    except MCPError as e:
        supabase.table("optimization_proposals").update({
            "status": "failed",
        }).eq("id", proposal_id).execute()
        return {"success": False, "proposal_id": proposal_id, "error": str(e)}
