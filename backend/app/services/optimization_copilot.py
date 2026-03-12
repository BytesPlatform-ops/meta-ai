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

settings = get_settings()
openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert Meta Ads optimization analyst. Given performance data broken down by age, gender, and placement, WITH account historical baselines AND 3-day trend data, generate actionable optimization proposals.

Rules:
- Budget changes should stay within ±30% to avoid resetting Meta's learning phase
- Only suggest pausing entities with very poor performance (30%+ worse than account baseline)
- A "Winning" entity has its primary metric 20%+ better than the account baseline
- A "Losing" entity has its primary metric 30%+ worse than the account baseline
- For lead-gen: primary metric is CPL (lower = better). For purchase: primary metric is ROAS (higher = better)
- ALWAYS reference the account baselines when making judgments — do NOT use arbitrary fixed thresholds
- Diagnose issues using secondary metrics: low CTR = creative problem, high CPM = audience problem, clicks but no results = landing page problem
- Always include concrete numbers AND baseline comparison in your reasoning
- Impact score 1-10: 10 = highest expected ROI improvement
- Be conservative — fewer high-quality proposals beat many low-quality ones

## CRITICAL Budget Rules:
- For "increase_budget" or "decrease_budget" proposals, proposed_value MUST contain "daily_budget" as an ABSOLUTE dollar amount (e.g. 26.00), NEVER a percentage string like "30%"
- Calculate the exact new budget from the current budget. Example: current daily_budget is $20, you want +30% → proposed_value: {"daily_budget": 26.00}
- current_value MUST also contain "daily_budget" as the current absolute dollar amount (e.g. 20.00)

## CRITICAL Placement Rule:
- Meta's Graph API controls placements at the AD SET level, NEVER the ad level
- If you propose placement exclusions (e.g. prune_placements with exclude_placements: ["audience_network"]), your entity_type MUST be "adset" and entity_id MUST be the parent adset ID — NEVER use entity_type "ad"
- If the problematic data is at the ad level, look up the parent adset_id from the data and use that

## Advanced Diagnostic Rules:
1. **Creative Fatigue**: frequency > 2.5 AND CTR dropping over 3-day trend → use action_type "refresh_creative" to pause the fatigued ad and trigger a new creative draft
2. **Placement Waste**: audience_network spend > 0 with 0 conversions → use action_type "prune_placements" with proposed_value including exclude_placements list (e.g. ["audience_network"])
3. **Scale with Protection**: campaign is profitable (winning) AND you'd scale budget > 50% → use action_type "apply_cost_cap" with proposed_value including bid_amount set to historical avg CPA (in cents)
4. **Adset Consolidation**: 2+ adsets in same campaign, one significantly underperforming the other → use action_type "consolidate_adsets" with proposed_value including winner_adset_id and loser_adset_id, plus budget_transfer amount

## Agentic Workflow Rules:
## CRITICAL Copy Generation Rule:
- When generating new_body_text for refresh_creative or mutate_winner, you MUST reference the "Current Ad Creatives" section to understand what copy is already running
- Study which ads are winning (low CPR, high CTR) and which are losing — use winning patterns as inspiration
- NEVER repeat the same body_text as an existing ad — always write a genuinely fresh angle
- Match the brand voice and tone of the existing ads but bring a new hook or benefit angle

5. **Fatigue → Auto-Refresh (refresh_creative)**: IF frequency > 3.0 AND CTR is declining over 3-day trend data → propose "refresh_creative". You MUST generate new ad body_text in proposed_value (fresh angle, same product, inspired by winning ads). proposed_value format: {"ad_id": "source_ad_id", "new_body_text": "your new ad copy here", "new_cta": "SHOP_NOW"}
6. **Robin Hood Budget Shift (shift_budget)**: IF Campaign/Adset A is Losing (CPL > baseline by 30%+) AND Campaign/Adset B is Winning (CPL < baseline by 20%+) → propose "shift_budget". proposed_value format: {"from_entity": "losing_id", "from_name": "Losing Name", "to_entity": "winning_id", "to_name": "Winning Name", "amount_cents": 4000, "amount_display": 40.00}. Entity_id should be the LOSING entity.
7. **Winner Mutation / A-B Test (mutate_winner)**: IF an ad is clearly winning (20%+ better than baseline) and has been running 5+ days → propose "mutate_winner" to duplicate it with a variation. You MUST generate new_body_text with a fresh angle and optionally a different CTA. proposed_value format: {"ad_id": "winning_ad_id", "new_body_text": "your variation copy", "new_cta": "LEARN_MORE", "mutation_type": "copy"}
8. **Scale → Lookalike Audience (create_lookalike)**: IF a lead campaign has high volume results (200+ leads or conversions) at a highly profitable CPL (20%+ better than baseline) → propose "create_lookalike". proposed_value format: {"campaign_id": "source_campaign_id", "campaign_name": "Source Campaign", "country_code": "PK", "ratio": 0.01}

Available action_types:
- "increase_budget" — increase daily budget
- "decrease_budget" — decrease daily budget
- "pause" — pause an underperforming entity
- "enable" — re-enable a paused entity
- "reallocate" — advisory: shift budget between entities
- "audience_shift" — advisory: change audience targeting
- "refresh_creative" — pause fatigued ad + launch new ad with AI-generated copy (proposed_value MUST include new_body_text)
- "mutate_winner" — duplicate a winning ad with copy/CTA variation for A/B testing (proposed_value MUST include new_body_text)
- "shift_budget" — Robin Hood: move exact dollar amount from losing to winning entity (proposed_value MUST include from_entity, to_entity, amount_cents)
- "create_lookalike" — generate 1% LAL audience from a high-performing campaign
- "prune_placements" — exclude wasteful placements from adset targeting
- "consolidate_adsets" — pause losing adset + transfer budget to winning adset
- "apply_cost_cap" — switch adset bid strategy to COST_CAP with specified bid_amount
- "custom" — any other recommendation

You MUST return a JSON array of proposals. Each proposal:
{
  "entity_id": "string (campaign/adset/ad ID)",
  "entity_type": "campaign|adset|ad",
  "entity_name": "string",
  "action_type": "one of the action_types above",
  "current_value": {"key": "value pairs showing current state"},
  "proposed_value": {"key": "value pairs showing proposed change — see required formats above"},
  "ai_reasoning": "2-3 sentence explanation with numbers and baseline comparison",
  "impact_score": 1-10
}

Return ONLY a JSON array — no markdown, no wrapper object."""


async def analyze_account(user_id: str, ad_account_id: str | None = None) -> list[dict]:
    """
    Fetch deep insights from MCP, send to OpenAI for analysis, and save proposals to DB.
    Returns the list of generated proposals.
    """
    supabase = get_supabase()

    # Resolve ad account
    if not ad_account_id:
        result = (
            supabase.table("ad_accounts")
            .select("meta_account_id, access_token")
            .eq("user_id", user_id)
            .eq("is_active", True)
            .limit(1)
            .maybe_single()
            .execute()
        )
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
    try:
        campaign_insights = await mcp_client.get_deep_ad_insights(
            ad_account_id, access_token, date_preset="last_7d", entity_level="campaign"
        )
        adset_insights = await mcp_client.get_deep_ad_insights(
            ad_account_id, access_token, date_preset="last_7d", entity_level="adset"
        )
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
            ad_account_id, access_token, date_preset="last_7d"
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

## Campaign-Level Breakdown (Last 7 Days)

### By Age:
{json.dumps(campaign_insights.get("by_age", [])[:50], indent=2)}

### By Gender:
{json.dumps(campaign_insights.get("by_gender", [])[:30], indent=2)}

### By Placement:
{json.dumps(campaign_insights.get("by_placement", [])[:30], indent=2)}

## Adset-Level Breakdown (Last 7 Days)

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
    try:
        parsed = json.loads(raw_content)
        # Handle both {"proposals": [...]} and plain [...]
        if isinstance(parsed, dict):
            proposals = parsed.get("proposals", parsed.get("data", []))
        elif isinstance(parsed, list):
            proposals = parsed
        else:
            proposals = []
    except json.JSONDecodeError:
        log.error(f"Failed to parse OpenAI response: {raw_content[:200]}")
        proposals = []

    if not proposals:
        return []

    # Clear old pending proposals for this account
    supabase.table("optimization_proposals").delete().eq(
        "user_id", user_id
    ).eq("ad_account_id", ad_account_id).eq("status", "pending").execute()

    # Save new proposals
    saved = []
    valid_actions = {
        "increase_budget", "decrease_budget", "pause", "enable",
        "reallocate", "audience_shift", "custom",
        "refresh_creative", "prune_placements", "consolidate_adsets", "apply_cost_cap",
        "mutate_winner", "shift_budget", "create_lookalike",
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
        result = supabase.table("optimization_proposals").insert(row).execute()
        if result.data:
            saved.append(result.data[0])

    return saved


AD_SYSTEM_PROMPT = """You are an expert Meta Ads optimization analyst. Given a SINGLE ad's performance data with account baselines, generate focused optimization proposals for this specific ad.

Rules:
- Budget changes should stay within ±30% to avoid resetting Meta's learning phase
- Only suggest pausing if the ad has very poor performance (30%+ worse than account baseline)
- ALWAYS reference the account baselines when making judgments
- Diagnose issues using secondary metrics: low CTR = creative problem, high CPM = audience problem, clicks but no results = landing page problem
- Include concrete numbers AND baseline comparison in your reasoning
- Impact score 1-10: 10 = highest expected ROI improvement
- Be concise — 1-4 high-quality proposals for this single ad

## CRITICAL Budget Rules:
- For budget proposals, proposed_value MUST contain "daily_budget" as an ABSOLUTE dollar amount
- current_value MUST also contain "daily_budget" as the current absolute dollar amount

## CRITICAL Placement Rule:
- Meta controls placements at the AD SET level, not ad level
- If proposing placement exclusions, entity_type MUST be "adset" and entity_id MUST be the parent adset ID

## Available action_types:
- "increase_budget" / "decrease_budget" — adjust parent adset daily budget
- "pause" — pause this underperforming ad
- "refresh_creative" — pause fatigued ad + launch new ad with AI-generated copy (proposed_value MUST include new_body_text)
- "mutate_winner" — duplicate this winning ad with copy/CTA variation (proposed_value MUST include new_body_text)
- "prune_placements" — exclude wasteful placements from parent adset
- "apply_cost_cap" — switch parent adset to COST_CAP bidding
- "custom" — any other recommendation

## Copy Generation Rule:
- When generating new_body_text, study the current ad's copy and write something genuinely different
- Match the brand voice but bring a fresh hook or benefit angle

Return ONLY a JSON array of proposals. Each proposal:
{
  "entity_id": "string (ad/adset ID)",
  "entity_type": "ad|adset",
  "entity_name": "string",
  "action_type": "one of the action_types above",
  "current_value": {"key": "value pairs"},
  "proposed_value": {"key": "value pairs"},
  "ai_reasoning": "2-3 sentence explanation with numbers and baseline comparison",
  "impact_score": 1-10
}

Return ONLY a JSON array — no markdown, no wrapper object."""


async def analyze_specific_ad(
    user_id: str,
    ad_id: str,
    campaign_id: str | None = None,
    ad_name: str | None = None,
) -> list[dict]:
    """
    Fetch performance data for a single ad and generate focused proposals.
    """
    supabase = get_supabase()

    # Resolve ad account
    result = (
        supabase.table("ad_accounts")
        .select("meta_account_id, access_token")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(1)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise ValueError("No active ad account found")
    ad_account_id = result.data["meta_account_id"]
    access_token = result.data["access_token"]

    # Fetch ad creatives with performance (includes per-ad spend, CTR, etc.)
    try:
        creatives_data = await mcp_client.get_ad_creatives_with_performance(
            ad_account_id, access_token, date_preset="last_7d"
        )
    except MCPError:
        creatives_data = {"ads": []}

    # Find this specific ad's creative data
    target_ad_creative = None
    for ad_item in creatives_data.get("ads", []):
        if str(ad_item.get("id")) == str(ad_id):
            target_ad_creative = ad_item
            break

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

    user_prompt = f"""Analyze this SPECIFIC ad and generate optimization proposals.

## Ad Being Analyzed
- Ad ID: {ad_id}
- Ad Name: {ad_name or 'Unknown'}
- Campaign ID: {campaign_id or 'Unknown'}

{baselines_prompt}

## Ad Creative & Performance (Last 7 Days):
{creative_str}

## Other Ads for Context (to avoid duplicate copy):
{json.dumps(creatives_data.get("ads", [])[:10], indent=2)}

Generate 1-4 focused proposals for this specific ad. Compare its performance to the account baselines above."""

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
            proposals = parsed.get("proposals", parsed.get("data", []))
        elif isinstance(parsed, list):
            proposals = parsed
        else:
            proposals = []
    except json.JSONDecodeError:
        log.error(f"Failed to parse OpenAI response for ad analysis: {raw_content[:200]}")
        proposals = []

    if not proposals:
        return []

    # Clear old pending proposals for this ad
    supabase.table("optimization_proposals").delete().eq(
        "user_id", user_id
    ).eq("entity_id", ad_id).eq("status", "pending").execute()

    # Save new proposals
    saved = []
    valid_actions = {
        "increase_budget", "decrease_budget", "pause", "enable",
        "refresh_creative", "prune_placements", "apply_cost_cap",
        "mutate_winner", "custom",
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
