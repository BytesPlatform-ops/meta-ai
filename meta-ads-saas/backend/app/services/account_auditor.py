"""
Account Auditor — Fetches ad performance via MCP, analyzes with OpenAI,
and saves an account health & strategy report.
"""
import json
import logging
from datetime import datetime, timezone

import httpx
from openai import AsyncOpenAI

from ..core.config import get_settings
from ..db.supabase_client import get_supabase
from .mcp_client import mcp_client, MCPError
from .baselines import calculate_account_baselines, evaluate_ad, build_diagnostic_prompt, AccountBaselines

logger = logging.getLogger(__name__)
settings = get_settings()
openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def _postgrest_headers() -> dict:
    return {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _postgrest_url(table: str) -> str:
    return f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1/{table}"


async def run_audit(user_id: str, ad_account_id: str | None = None) -> dict:
    """
    Full audit pipeline:
      1. Resolve ad account + access token
      2. Create pending audit row
      3. Call MCP for 30-day ad data
      4. Analyze with OpenAI
      5. Save results
    Returns the completed audit record.
    """
    supabase = get_supabase()

    # 1. Get ad account
    query = supabase.table("ad_accounts").select("*").eq("user_id", user_id).eq("is_active", True)
    if ad_account_id:
        query = query.eq("id", ad_account_id)
    result = query.limit(1).execute()
    if not result.data:
        raise ValueError("No active ad account found")
    account = result.data[0]

    # 2. Create pending audit row (direct httpx to avoid supabase-py issues)
    audit_row = {
        "user_id": user_id,
        "ad_account_id": account["id"],
        "status": "processing",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    resp = httpx.post(
        _postgrest_url("account_audits"),
        headers=_postgrest_headers(),
        json=audit_row,
        timeout=10,
    )
    if resp.status_code not in (200, 201) or not resp.json():
        raise RuntimeError(f"Failed to create audit row: {resp.status_code} {resp.text}")
    audit = resp.json()[0]
    audit_id = audit["id"]

    try:
        # 3. Call MCP for ad performance data
        meta_account_id = account["meta_account_id"].replace("act_", "")
        mcp_result = await mcp_client.call_tool(
            "get_account_audit_data",
            {"ad_account_id": meta_account_id},
            account["access_token"],
        )

        # Parse MCP result — may be in content[0].text (FastMCP) or direct dict (custom server)
        content = mcp_result.get("content", [])
        if content and isinstance(content, list) and isinstance(content[0], dict) and "text" in content[0]:
            ad_data = json.loads(content[0]["text"])
        elif isinstance(mcp_result, dict) and "ads" in mcp_result:
            ad_data = mcp_result
        else:
            ad_data = mcp_result

        ads = ad_data.get("ads", [])
        total_spend = ad_data.get("total_spend", 0)
        dominant_type = ad_data.get("dominant_result_type", "purchases")

        # Calculate dynamic baselines from historical data
        baselines = await calculate_account_baselines(
            meta_account_id, account["access_token"], user_id=user_id
        )

        # Evaluate every ad against baselines
        evaluated_ads = [evaluate_ad(a, baselines) for a in ads]

        winning = [a for a in evaluated_ads if a.get("verdict") == "scale"][:10]
        losing = [a for a in evaluated_ads if a.get("verdict") in ("underperforming", "kill", "no_results")][:10]

        # Sort winners: leads by CPL asc, purchases by ROAS desc
        if dominant_type == "leads":
            winning.sort(key=lambda a: a.get("cost_per_result") or 9999)
            losing.sort(key=lambda a: -(a.get("cost_per_result") or 0))
        else:
            winning.sort(key=lambda a: -(a.get("roas") or 0))
            losing.sort(key=lambda a: a.get("roas") or 9999)

        avg_roas = ad_data.get("avg_roas")
        demographics = ad_data.get("demographics")

        # 4. Generate AI strategy report (with diagnostics + baselines)
        report, tone_recommendation = await _generate_strategy_report(
            evaluated_ads, total_spend, avg_roas, winning, losing, demographics,
            dominant_type=dominant_type,
            baselines=baselines,
        )

        # Strip evaluation dicts before serializing (frontend doesn't need raw eval)
        def _clean_for_json(ad_list: list[dict]) -> str:
            return json.dumps([{k: v for k, v in a.items() if k != "evaluation"} for a in ad_list])

        # 5. Update audit row with results
        update = {
            "total_spend": total_spend,
            "roas": avg_roas,
            "winning_ads": _clean_for_json(winning),
            "losing_ads": _clean_for_json(losing),
            "ai_strategy_report": report,
            "baselines": json.dumps(baselines.to_dict()),
            "status": "completed",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if demographics:
            update["audience_demographics"] = json.dumps(demographics)
        if tone_recommendation:
            update["tone_recommendation"] = tone_recommendation
        resp = httpx.patch(
            f"{_postgrest_url('account_audits')}?id=eq.{audit_id}",
            headers={**_postgrest_headers(), "Prefer": "return=representation"},
            json=update,
            timeout=10,
        )
        return resp.json()[0] if resp.json() else {**audit, **update}

    except Exception as e:
        logger.exception(f"Audit failed for user {user_id}")
        httpx.patch(
            f"{_postgrest_url('account_audits')}?id=eq.{audit_id}",
            headers=_postgrest_headers(),
            json={
                "status": "failed",
                "error_message": str(e)[:500],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            timeout=10,
        )
        raise


async def _generate_strategy_report(
    ads: list[dict],
    total_spend: float,
    avg_roas: float | None,
    winning: list[dict],
    losing: list[dict],
    demographics: dict | None = None,
    dominant_type: str = "purchases",
    baselines: "AccountBaselines | None" = None,
) -> tuple[str, str | None]:
    """Use OpenAI to generate a strategic analysis. Returns (report, tone_recommendation)."""

    ads_summary = json.dumps(ads[:30], indent=2)  # Cap to avoid token limits

    demo_section = ""
    if demographics:
        demo_section = f"""

## Audience Demographics (by spend distribution)
- Age Groups: {json.dumps(demographics.get('age_groups', {}))}
- Gender Split: {json.dumps(demographics.get('gender', {}))}

Analyze these demographics to understand WHO is converting and recommend targeting adjustments."""

    # Build baselines context
    baselines_section = ""
    if baselines and baselines.source != "fallback":
        bl = baselines.to_dict()
        win_str = f"{bl['win_threshold']:.2f}" if bl['win_threshold'] else "N/A"
        lose_str = f"{bl['lose_threshold']:.2f}" if bl['lose_threshold'] else "N/A"
        baselines_section = f"""
## Account Historical Baselines (30-day averages)
- Source: {baselines.source}
- Avg CPL: ${bl['avg_cpl'] or 'N/A'}
- Avg CPA: ${bl['avg_cpa'] or 'N/A'}
- Avg ROAS: {bl['avg_roas'] or 'N/A'}
- Avg CTR: {bl['avg_ctr']}%
- Avg CPC: ${bl['avg_cpc']}
- Avg CPM: ${bl['avg_cpm']}
- Winning Threshold: {win_str}
- Losing Threshold: {lose_str}

IMPORTANT: Use these baselines to judge each ad. "Winning" = 20% better than baseline. "Losing" = 30% worse than baseline. Do NOT use arbitrary fixed thresholds."""

    # Build diagnostic context for top winners/losers
    diagnostics_section = ""
    if baselines:
        diag_parts = []
        for ad in winning[:5]:
            name = ad.get("ad_name", ad.get("ad_id", "?"))
            diag = build_diagnostic_prompt(ad, baselines)
            if diag != "Insufficient data for comparison.":
                diag_parts.append(f"  - **{name}** (Winner): {diag}")
        for ad in losing[:5]:
            name = ad.get("ad_name", ad.get("ad_id", "?"))
            diag = build_diagnostic_prompt(ad, baselines)
            if diag != "Insufficient data for comparison.":
                diag_parts.append(f"  - **{name}** (Loser): {diag}")
        if diag_parts:
            diagnostics_section = "\n## Per-Ad Diagnostic Context\n" + "\n".join(diag_parts)

    # Build context based on campaign type
    if dominant_type == "leads":
        total_leads = sum(a.get("leads", 0) for a in ads)
        avg_cpl = round(total_spend / total_leads, 2) if total_leads > 0 else None
        win_label = f"CPL ≤ ${baselines.winning_threshold('cpl'):.2f}" if baselines and baselines.winning_threshold('cpl') else "best CPL"
        lose_label = f"CPL ≥ ${baselines.losing_threshold('cpl'):.2f}" if baselines and baselines.losing_threshold('cpl') else "worst CPL"
        kpi_section = f"""- Campaign Type: LEAD GENERATION
- Total Leads: {total_leads}
- Account Average CPL: ${avg_cpl or 'N/A'}
- Winning Ads ({win_label}): {len(winning)}
- Losing Ads ({lose_label} or no leads): {len(losing)}"""
        metric_note = "Use CPL (Cost Per Lead) as the primary metric, NOT ROAS. Lower CPL = better. Judge relative to account baseline, NOT arbitrary dollar values."
    else:
        win_label = f"ROAS ≥ {baselines.winning_threshold('roas'):.2f}x" if baselines and baselines.winning_threshold('roas') else "best ROAS"
        lose_label = f"ROAS ≤ {baselines.losing_threshold('roas'):.2f}x" if baselines and baselines.losing_threshold('roas') else "worst ROAS"
        kpi_section = f"""- Campaign Type: PURCHASE/CONVERSION
- Account Average ROAS: {avg_roas or 'N/A'}
- Winning Ads ({win_label}): {len(winning)}
- Losing Ads ({lose_label} or no purchases): {len(losing)}"""
        metric_note = "Use ROAS as the primary metric. Higher ROAS = better. Judge relative to account baseline, NOT arbitrary fixed thresholds."

    prompt = f"""You are an expert Meta Ads strategist. Analyze this account's last 30 days of ad performance and provide actionable recommendations.

## Account Data
- Total Spend: ${total_spend:.2f}
{kpi_section}
- Total Ads: {len(ads)}
{baselines_section}
{demo_section}
{diagnostics_section}

NOTE: {metric_note}

## Ad Performance Data
{ads_summary}

## Your Report Must Include:
1. **Account Health Score** (1-10) with brief justification
2. **Top Performing Ads** — what makes them work (creative patterns, targeting signals). Compare to account baselines.
3. **Underperforming Ads** — diagnose WHY using both primary metric AND secondary metrics (CTR, CPM, CPC). Is it a creative problem (low CTR), an audience problem (high CPM), or a landing page problem (clicks but no results)?
4. **Budget Reallocation** — specific recommendations on where to shift spend
5. **Quick Wins** — 3 actionable things to do this week
6. **Strategic Recommendations** — longer-term improvements

Write in a clear, direct style. Use bullet points. Be specific with numbers. Reference the baselines when making judgments.

IMPORTANT: At the very end of your response, on its own line, write:
TONE_RECOMMENDATION: <one of: professional, humorous, educational, promotional>
Choose the tone that would best fit this account's audience and top-performing content patterns."""

    response = await openai_client.chat.completions.create(
        model=settings.CHEAP_FAST_MODEL,
        messages=[
            {"role": "system", "content": "You are a Meta Ads performance analyst. Be concise, data-driven, and actionable."},
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=4000,
    )
    full_text = (response.choices[0].message.content or "").strip()
    if not full_text:
        return "Strategy report generation returned empty. Please re-run the audit.", None

    # Extract tone recommendation from end of response
    tone_recommendation = None
    lines = full_text.split("\n")
    for i, line in enumerate(lines):
        if line.strip().startswith("TONE_RECOMMENDATION:"):
            tone_recommendation = line.split(":", 1)[1].strip().lower()
            # Remove the line from the report
            lines.pop(i)
            break

    report = "\n".join(lines).strip()
    return report, tone_recommendation


async def generate_audit_proposals(user_id: str, audit_id: str) -> list[dict]:
    """
    Take a completed audit's data and generate structured optimization proposals
    (same schema as copilot) that the user can approve and apply directly on Meta.
    """
    supabase = get_supabase()

    # Load the audit
    audit_result = (
        supabase.table("account_audits")
        .select("*")
        .eq("id", audit_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not audit_result.data:
        raise ValueError("Audit not found")
    audit = audit_result.data[0]

    if audit["status"] != "completed":
        raise ValueError("Audit is not completed")

    # Load ad account for meta_account_id
    account_result = (
        supabase.table("ad_accounts")
        .select("id, meta_account_id, access_token")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if not account_result.data:
        raise ValueError("No active ad account")
    account = account_result.data[0]
    ad_account_id = account["meta_account_id"]

    # Get current live ad data via MCP for entity IDs
    live_data = None
    try:
        meta_id = ad_account_id.replace("act_", "")
        live_data = await mcp_client.call_tool(
            "get_account_audit_data",
            {"ad_account_id": meta_id},
            account["access_token"],
        )
        content = live_data.get("content", [])
        if content and isinstance(content, list) and isinstance(content[0], dict) and "text" in content[0]:
            live_data = json.loads(content[0]["text"])
    except Exception as e:
        logger.warning(f"Failed to get live data for proposals: {e}")

    ads_data = json.dumps((live_data or {}).get("ads", [])[:20], indent=2) if live_data else "No live data available"

    report = audit.get("ai_strategy_report", "") or ""
    winning = audit.get("winning_ads", "[]")
    losing = audit.get("losing_ads", "[]")
    if isinstance(winning, str):
        winning = json.loads(winning)
    if isinstance(losing, str):
        losing = json.loads(losing)

    prompt = f"""You are a Meta Ads optimization expert. Based on this 30-day audit report and ad data, generate SPECIFIC, EXECUTABLE optimization proposals.

## Strategy Report (AI-generated):
{report[:3000]}

## Winning Ads:
{json.dumps(winning[:5], indent=2)}

## Losing Ads:
{json.dumps(losing[:5], indent=2)}

## Current Live Ad Data (with entity IDs):
{ads_data}

## Instructions:
Convert the strategy report's recommendations into SPECIFIC, EXECUTABLE proposals.
Each proposal MUST reference a REAL entity_id from the live ad data above.
If the report says "pause X" — create a pause proposal with X's actual entity_id.
If the report says "increase budget for Y" — create an increase_budget proposal with Y's actual adset ID and exact dollar amounts.

## Available action_types:
- "increase_budget" — proposed_value: {{"daily_budget": 26.00}} (absolute dollars)
- "decrease_budget" — proposed_value: {{"daily_budget": 14.00}} (absolute dollars)
- "pause" — pause an underperforming entity
- "shift_budget" — proposed_value: {{"from_entity": "id", "from_name": "name", "to_entity": "id", "to_name": "name", "amount_cents": 4000, "amount_display": 40.00}}
- "refresh_creative" — proposed_value: {{"ad_id": "source_id", "new_body_text": "fresh copy", "new_cta": "SHOP_NOW"}}
- "mutate_winner" — proposed_value: {{"ad_id": "winner_id", "new_body_text": "variation copy", "new_cta": "LEARN_MORE"}}
- "create_lookalike" — proposed_value: {{"campaign_id": "id", "campaign_name": "name", "country_code": "XX", "ratio": 0.01}}
- "custom" — advisory only, no auto-execution

## Rules:
- Generate 3-8 high-impact proposals
- Each MUST have a real entity_id from the data above
- current_value MUST include the entity's current budget/status
- Sort by impact_score descending (highest impact first)
- For budget proposals, use ABSOLUTE dollar amounts (not percentages)

Return ONLY a JSON array of proposals:
[{{
  "entity_id": "real_id_from_data",
  "entity_type": "campaign|adset|ad",
  "entity_name": "actual name",
  "action_type": "one of the types above",
  "current_value": {{"key": "value"}},
  "proposed_value": {{"key": "value"}},
  "ai_reasoning": "2-3 sentences with numbers",
  "impact_score": 1-10
}}]

Return ONLY a JSON array — no markdown, no wrapper."""

    response = await openai_client.chat.completions.create(
        model=settings.CHEAP_FAST_MODEL,
        messages=[
            {"role": "system", "content": "You are a Meta Ads optimization engine. Return ONLY valid JSON arrays."},
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=3000,
    )
    raw = (response.choices[0].message.content or "").strip()

    # Parse JSON
    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        proposals = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse audit proposals: {raw[:200]}")
        return []

    if not proposals:
        return []

    # Clear old audit-sourced pending proposals
    supabase.table("optimization_proposals").delete().eq(
        "user_id", user_id
    ).eq("ad_account_id", ad_account_id).eq("status", "pending").execute()

    # Save proposals
    valid_actions = {
        "increase_budget", "decrease_budget", "pause", "enable",
        "reallocate", "audience_shift", "custom",
        "refresh_creative", "prune_placements", "consolidate_adsets", "apply_cost_cap",
        "mutate_winner", "shift_budget", "create_lookalike",
    }
    saved = []
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
