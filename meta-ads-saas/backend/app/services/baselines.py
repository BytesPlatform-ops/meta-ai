"""
Dynamic Historical Baselines — calculates account-specific performance averages
from the last 60–90 days of Meta ad data via MCP.

Replaces all hardcoded $20/$30 CPL and 2x/3x ROAS thresholds with data-driven
baselines unique to each ad account.
"""
import logging
from typing import Any

from .mcp_client import mcp_client, MCPError
from ..db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


# ── Baseline data class ──────────────────────────────────────────────────────

class AccountBaselines:
    """Container for an account's computed performance baselines."""

    def __init__(
        self,
        avg_cpl: float | None = None,
        avg_cpa: float | None = None,
        avg_roas: float | None = None,
        avg_ctr: float = 0.0,
        avg_cpc: float = 0.0,
        avg_cpm: float = 0.0,
        total_spend: float = 0.0,
        total_leads: int = 0,
        total_purchases: int = 0,
        dominant_type: str = "none",
        sample_size: int = 0,
        target_cost_per_result: float | None = None,
        source: str = "historical",
    ):
        self.avg_cpl = avg_cpl
        self.avg_cpa = avg_cpa
        self.avg_roas = avg_roas
        self.avg_ctr = avg_ctr
        self.avg_cpc = avg_cpc
        self.avg_cpm = avg_cpm
        self.total_spend = total_spend
        self.total_leads = total_leads
        self.total_purchases = total_purchases
        self.dominant_type = dominant_type
        self.sample_size = sample_size
        self.target_cost_per_result = target_cost_per_result
        self.per_type_baselines: dict[str, float] = {}  # result_type → avg cost_per_result
        # Per-objective creative baselines: objective → {avg_ctr, avg_cpc, avg_cpm}
        self.per_objective_creative: dict[str, dict[str, float]] = {}
        self.source = source  # "historical", "user_target", or "fallback"

    @property
    def primary_metric_label(self) -> str:
        if self.dominant_type == "leads":
            return "CPL"
        return "ROAS" if self.total_purchases > 0 else "CPR"

    @property
    def primary_baseline(self) -> float | None:
        """The account's baseline for the primary metric."""
        if self.dominant_type == "leads":
            return self.avg_cpl
        if self.total_purchases > 0:
            return self.avg_roas
        return None

    def winning_threshold(self, metric: str = "primary") -> float | None:
        """20% better than baseline (lower CPL = better, higher ROAS = better)."""
        val = self._metric_baseline(metric)
        if val is None:
            return None
        if metric in ("cpl", "cpa", "cpc", "cpm", "cost_per_result"):
            return val * 0.80  # 20% lower = better
        return val * 1.20  # 20% higher = better (ROAS, CTR)

    def losing_threshold(self, metric: str = "primary") -> float | None:
        """30% worse than baseline."""
        val = self._metric_baseline(metric)
        if val is None:
            return None
        if metric in ("cpl", "cpa", "cpc", "cpm", "cost_per_result"):
            return val * 1.30  # 30% higher = worse
        return val * 0.70  # 30% lower = worse (ROAS, CTR)

    def _metric_baseline(self, metric: str) -> float | None:
        if metric == "primary":
            return self.primary_baseline
        return {
            "cpl": self.avg_cpl,
            "cpa": self.avg_cpa,
            "roas": self.avg_roas,
            "ctr": self.avg_ctr,
            "cpc": self.avg_cpc,
            "cpm": self.avg_cpm,
            "cost_per_result": self.avg_cpl if self.dominant_type == "leads" else self.avg_cpa,
        }.get(metric)

    def to_dict(self) -> dict:
        return {
            "avg_cpl": self.avg_cpl,
            "avg_cpa": self.avg_cpa,
            "avg_roas": self.avg_roas,
            "avg_ctr": round(self.avg_ctr, 2),
            "avg_cpc": round(self.avg_cpc, 2),
            "avg_cpm": round(self.avg_cpm, 2),
            "total_spend": round(self.total_spend, 2),
            "total_leads": self.total_leads,
            "total_purchases": self.total_purchases,
            "dominant_type": self.dominant_type,
            "sample_size": self.sample_size,
            "source": self.source,
            "win_threshold": self.winning_threshold(),
            "lose_threshold": self.losing_threshold(),
            "per_type_baselines": self.per_type_baselines,
            "per_objective_creative": self.per_objective_creative,
        }


# ── Baselines Cache (5-minute TTL to avoid Meta API rate limits) ──────────────

import time as _time

_baselines_cache: dict[str, tuple[float, AccountBaselines]] = {}
_BASELINES_TTL = 300  # 5 minutes


# ── Calculator ───────────────────────────────────────────────────────────────

async def calculate_account_baselines(
    ad_account_id: str,
    access_token: str,
    user_id: str | None = None,
) -> AccountBaselines:
    """
    Query 30-day ad data via MCP and compute the account's unique baselines.
    Falls back to user-defined target_cost_per_result if no historical data.
    Results cached for 5 minutes to avoid Meta API rate limits.
    """
    cache_key = f"{ad_account_id}:{user_id or ''}"
    cached = _baselines_cache.get(cache_key)
    if cached and cached[0] > _time.monotonic():
        return cached[1]

    try:
        mcp_result = await mcp_client.call_tool(
            "get_account_audit_data",
            {"ad_account_id": ad_account_id, "date_preset": "last_30d"},
            access_token,
        )

        # Parse MCP result
        content = mcp_result.get("content", [])
        if content and isinstance(content, list) and isinstance(content[0], dict) and "text" in content[0]:
            import json
            ad_data = json.loads(content[0]["text"])
        elif isinstance(mcp_result, dict) and "ads" in mcp_result:
            ad_data = mcp_result
        else:
            ad_data = mcp_result

        all_ads: list[dict] = ad_data.get("ads", [])
        # Include all ads that had spend in the period (active, paused, completed)
        ads = [a for a in all_ads if a.get("spend", 0) > 0 or a.get("effective_status", "ACTIVE") == "ACTIVE"]
        if not ads:
            return _fallback_baselines(user_id)

        total_spend = sum(a.get("spend", 0) for a in ads)
        total_impressions = sum(a.get("impressions", 0) for a in ads)
        total_clicks = sum(a.get("clicks", 0) for a in ads)
        total_leads = sum(a.get("leads", 0) for a in ads)
        total_purchases = sum(a.get("purchases", 0) for a in ads)
        dominant_type = ad_data.get("dominant_result_type", "purchases")

        # Per-result-type baselines: group ads by result_type, compute avg cost_per_result per group
        per_type_baselines: dict[str, float] = {}
        type_groups: dict[str, list[dict]] = {}
        for a in ads:
            rt = a.get("result_type", "none")
            if rt != "none" and a.get("results", 0) > 0 and a.get("spend", 0) > 0:
                type_groups.setdefault(rt, []).append(a)
        for rt, group in type_groups.items():
            group_spend = sum(a["spend"] for a in group)
            group_results = sum(a["results"] for a in group)
            if group_results > 0:
                per_type_baselines[rt] = round(group_spend / group_results, 2)
        logger.info("Per-type baselines: %s", per_type_baselines)

        avg_cpl = round(total_spend / total_leads, 2) if total_leads > 0 else None
        avg_cpa = round(total_spend / total_purchases, 2) if total_purchases > 0 else None
        avg_ctr = round(total_clicks / total_impressions * 100, 2) if total_impressions > 0 else 0.0
        avg_cpc = round(total_spend / total_clicks, 2) if total_clicks > 0 else 0.0
        avg_cpm = round(total_spend / total_impressions * 1000, 2) if total_impressions > 0 else 0.0

        # ROAS: use the account-level value from MCP if available
        avg_roas = ad_data.get("avg_roas")
        if avg_roas is None and total_purchases > 0:
            roas_ads = [a for a in ads if a.get("roas") is not None and a["roas"] > 0]
            if roas_ads:
                total_weighted_spend = sum(a["spend"] for a in roas_ads)
                if total_weighted_spend > 0:
                    avg_roas = round(
                        sum(a["roas"] * a["spend"] for a in roas_ads) / total_weighted_spend, 2
                    )

        # Per-objective creative baselines: group by objective, compute CTR/CPC/CPM per group
        per_objective_creative: dict[str, dict[str, float]] = {}
        obj_groups: dict[str, list[dict]] = {}
        for a in ads:
            obj = a.get("objective", "") or ""
            if obj and a.get("spend", 0) > 0:
                obj_groups.setdefault(obj, []).append(a)
        for obj, group in obj_groups.items():
            g_spend = sum(a.get("spend", 0) for a in group)
            g_impressions = sum(a.get("impressions", 0) for a in group)
            g_clicks = sum(a.get("clicks", 0) for a in group)
            if g_impressions > 0 and g_clicks > 0:
                per_objective_creative[obj] = {
                    "avg_ctr": round(g_clicks / g_impressions * 100, 2),
                    "avg_cpc": round(g_spend / g_clicks, 2),
                    "avg_cpm": round(g_spend / g_impressions * 1000, 2),
                }
        logger.info("Per-objective creative baselines: %s", per_objective_creative)

        baselines = AccountBaselines(
            avg_cpl=avg_cpl,
            avg_cpa=avg_cpa,
            avg_roas=avg_roas,
            avg_ctr=avg_ctr,
            avg_cpc=avg_cpc,
            avg_cpm=avg_cpm,
            total_spend=total_spend,
            total_leads=total_leads,
            total_purchases=total_purchases,
            dominant_type=dominant_type,
            sample_size=len(ads),
            source="historical",
        )
        baselines.per_type_baselines = per_type_baselines
        baselines.per_objective_creative = per_objective_creative

        logger.info(
            f"Baselines for {ad_account_id}: "
            f"CPL=${avg_cpl}, CPA=${avg_cpa}, ROAS={avg_roas}, "
            f"CTR={avg_ctr}%, CPC=${avg_cpc}, CPM=${avg_cpm} "
            f"(from {len(ads)} ads, {dominant_type})"
        )
        _baselines_cache[cache_key] = (_time.monotonic() + _BASELINES_TTL, baselines)
        return baselines

    except MCPError as e:
        logger.warning(f"MCP error calculating baselines: {e}")
        return _fallback_baselines(user_id)
    except Exception as e:
        logger.warning(f"Error calculating baselines: {e}")
        return _fallback_baselines(user_id)


def _fallback_baselines(user_id: str | None) -> AccountBaselines:
    """
    Fallback when no historical data: check user preferences for
    target_cost_per_result, otherwise return empty baselines.
    """
    target_cpr = None

    if user_id:
        try:
            supabase = get_supabase()
            result = (
                supabase.table("user_preferences")
                .select("target_cost_per_result")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            if result.data and result.data.get("target_cost_per_result"):
                target_cpr = float(result.data["target_cost_per_result"])
        except Exception:
            pass

    if target_cpr:
        return AccountBaselines(
            avg_cpl=target_cpr,
            avg_cpa=target_cpr,
            target_cost_per_result=target_cpr,
            source="user_target",
        )

    # Absolute fallback — no data, no user target
    return AccountBaselines(source="fallback")


# ── Multi-factor Ad Scoring (0-100) ──────────────────────────────────────────
#
# Score = Creative(40%) + Efficiency(35%) + Health(15%) + Maturity(10%)
#
# Creative:   CTR, CPC, CPM — universal across all objectives
# Efficiency: cost_per_result vs per-type baseline, or ROAS for purchases
# Health:     frequency (fatigue) + delivery consistency
# Maturity:   spend + result count confidence
#
# Verdicts: Scale (75+), Hold (55-74), Underperforming (35-54), Kill (<35)
# ─────────────────────────────────────────────────────────────────────────────

import math


def _sigmoid_score(value: float, baseline: float, invert: bool = False) -> float:
    """Sigmoid percentile: 0.0-1.0. For cost metrics (lower=better), invert=True."""
    if not baseline or baseline <= 0:
        return 0.5  # no data → neutral
    ratio = value / baseline
    if invert:
        ratio = 1.0 / ratio  # flip so higher = better
    return max(0.0, min(1.0, 1 / (1 + math.exp(-3 * (ratio - 1)))))


def evaluate_ad(
    ad: dict,
    baselines: AccountBaselines,
) -> dict:
    """
    Multi-factor scoring: evaluate ad across creative quality, efficiency,
    health, and maturity. Returns ad dict enriched with score (0-100),
    verdict, and component breakdown.
    """
    spend = ad.get("spend", 0)
    results = ad.get("results", 0)
    result_type = ad.get("result_type", "none")
    ctr = float(ad.get("ctr", 0))
    cpc = float(ad.get("cpc", 0))
    cpm = float(ad.get("cpm", 0))
    frequency = float(ad.get("frequency", 1))
    cost_per_result = ad.get("cost_per_result")
    roas = ad.get("roas")
    days_running = ad.get("days_running") or 1
    is_learning = ad.get("is_learning", False)
    clicks = ad.get("clicks", 0)
    impressions = ad.get("impressions", 0)
    reach = ad.get("reach", 0)
    if reach > 0 and impressions > 0:
        frequency = max(frequency, impressions / reach)

    # Compute CPC/CPM if not provided
    if not cpc and clicks > 0:
        cpc = round(spend / clicks, 2)
    if not cpm and impressions > 0:
        cpm = round(spend / impressions * 1000, 2)

    # ── Component 1: Creative Score (0-40) — per-objective baselines when available ──
    objective = ad.get("objective", "") or ""
    obj_bl = baselines.per_objective_creative.get(objective, {})
    bl_ctr = obj_bl.get("avg_ctr", baselines.avg_ctr)
    bl_cpc = obj_bl.get("avg_cpc", baselines.avg_cpc)
    bl_cpm = obj_bl.get("avg_cpm", baselines.avg_cpm)

    ctr_s = _sigmoid_score(ctr, bl_ctr) * 20
    cpc_s = _sigmoid_score(cpc, bl_cpc, invert=True) * 12 if cpc > 0 else 6
    cpm_s = _sigmoid_score(cpm, bl_cpm, invert=True) * 8 if cpm > 0 else 4
    creative = ctr_s + cpc_s + cpm_s

    # Quality ranking bonus/penalty from Meta
    qr = ad.get("quality_ranking")
    if qr == "ABOVE_AVERAGE":
        creative += 3
    elif qr in ("BELOW_AVERAGE_10", "BELOW_AVERAGE_20"):
        creative -= 3
    elif qr == "BELOW_AVERAGE_35":
        creative -= 5
    creative = max(0, min(40, creative))

    # ── Component 2: Efficiency Score (0-35) — per result type ────────────
    if result_type == "purchases" and roas is not None and baselines.avg_roas:
        efficiency = _sigmoid_score(roas, baselines.avg_roas) * 35
    elif cost_per_result and cost_per_result > 0:
        type_bl = baselines.per_type_baselines.get(result_type)
        if not type_bl:
            type_bl = baselines.avg_cpl or baselines.avg_cpa
        if type_bl and type_bl > 0:
            efficiency = _sigmoid_score(cost_per_result, type_bl, invert=True) * 35
        else:
            efficiency = 17.5  # neutral — no baseline available
    elif results == 0 and spend > 0:
        # No results — partial credit based on CTR (creative proxy)
        efficiency = _sigmoid_score(ctr, baselines.avg_ctr) * 10  # max 10/35
    else:
        efficiency = 17.5  # neutral

    # ── Component 3: Health Score (0-15) — fatigue + delivery ─────────────
    # Frequency: optimal 1-2, acceptable up to 3.4, bad above that
    if frequency <= 2.0:
        freq_s = 10
    elif frequency <= 3.4:
        freq_s = 10 - (frequency - 2.0) * 4
    else:
        freq_s = max(0, 4.4 - (frequency - 3.4) * 3)

    # Delivery: is the ad actually spending meaningfully?
    daily_spend = spend / max(days_running, 1)
    if daily_spend >= 5:
        delivery_s = 5
    elif daily_spend >= 1:
        delivery_s = 3
    else:
        delivery_s = 1
    health = freq_s + delivery_s

    # ── Component 4: Maturity (0-10) — confidence adjustment ─────────────
    spend_conf = min(1.0, max(0.2, spend / 500))
    result_conf = min(1.0, max(0.2 if results == 0 else 0.3, results / 50))
    maturity = (spend_conf * 0.5 + result_conf * 0.5) * 10

    # ── Final Score with maturity damping ─────────────────────────────────
    raw = creative + efficiency + health + maturity
    if maturity < 5:
        # Pull immature ads toward neutral (50) to avoid premature verdicts
        damping = maturity / 10
        final = 50 + (raw - 50) * damping
    else:
        final = raw

    score = max(0, min(100, round(final)))

    # ── Verdict ──────────────────────────────────────────────────────────
    if is_learning and results < 50 and days_running < 7:
        verdict = "learning"
    elif results == 0 and spend >= 200:
        verdict = "kill"
    elif results == 0 and spend > 0 and days_running < 7:
        verdict = "learning"
    elif score >= 75:
        verdict = "scale"
    elif score >= 55:
        verdict = "hold"
    elif score >= 35:
        verdict = "underperforming"
    else:
        verdict = "kill"

    components = {
        "creative": round(creative, 1),
        "efficiency": round(efficiency, 1),
        "health": round(health, 1),
        "maturity": round(maturity, 1),
    }

    diagnosis = diagnose_ad(ad, baselines, verdict)

    return {
        **ad,
        "score": score,
        "verdict": verdict,
        "diagnosis": diagnosis,
        "components": components,
        "evaluation": _build_evaluation(ad, baselines, verdict, score, components),
    }


def diagnose_ad(ad: dict, baselines: AccountBaselines, verdict: str = "") -> str:
    """Root-cause diagnosis: WHY is this ad underperforming?"""
    ctr = float(ad.get("ctr", 0))
    cpm = float(ad.get("cpm", 0))
    results = ad.get("results", 0)
    spend = ad.get("spend", 0)
    clicks = ad.get("clicks", 0)
    frequency = float(ad.get("frequency", 1))
    cost_per_result = ad.get("cost_per_result")
    quality_ranking = ad.get("quality_ranking")
    engagement_ranking = ad.get("engagement_rate_ranking")
    conversion_ranking = ad.get("conversion_rate_ranking")

    objective = ad.get("objective", "") or ""
    obj_bl = baselines.per_objective_creative.get(objective, {})
    bl_ctr = obj_bl.get("avg_ctr", baselines.avg_ctr)
    bl_cpm = obj_bl.get("avg_cpm", baselines.avg_cpm)

    issues = []

    # Pattern 1: Creative problem — low CTR
    if bl_ctr > 0 and ctr < bl_ctr * 0.7:
        if bl_cpm > 0 and cpm <= bl_cpm * 1.3:
            issues.append(f"CREATIVE: Low CTR ({ctr:.2f}% vs {bl_ctr:.2f}% baseline) with normal CPM — ad copy/visual isn't resonating")
        else:
            issues.append(f"CREATIVE + AUDIENCE: Low CTR ({ctr:.2f}% vs {bl_ctr:.2f}%) AND high CPM (${cpm:.0f} vs ${bl_cpm:.0f}) — both creative and targeting need work")

    # Pattern 2: Audience saturation — high CPM, decent CTR
    if bl_cpm > 0 and cpm > bl_cpm * 1.5 and (bl_ctr == 0 or ctr >= bl_ctr * 0.8):
        issues.append(f"AUDIENCE: High CPM (${cpm:.0f} vs ${bl_cpm:.0f} baseline) — audience saturated or too narrow, broaden targeting")

    # Pattern 3: Landing page problem — good CTR but no/poor conversions
    if bl_ctr > 0 and ctr >= bl_ctr * 0.9 and clicks > 20 and results == 0 and spend > 50:
        issues.append(f"LANDING PAGE: Strong CTR ({ctr:.2f}%) and {clicks} clicks but 0 conversions — check landing page or form")
    elif bl_ctr > 0 and ctr >= bl_ctr * 0.9 and cost_per_result and baselines.avg_cpl and cost_per_result > baselines.avg_cpl * 1.5:
        issues.append(f"FUNNEL LEAK: Good CTR ({ctr:.2f}%) but high cost/result (${cost_per_result:.0f} vs ${baselines.avg_cpl:.0f} baseline) — traffic quality or LP friction")

    # Pattern 4: Ad fatigue
    if frequency > 3.0:
        issues.append(f"FATIGUE: Frequency {frequency:.1f} (ideal < 2.5) — refresh creative or expand audience")

    # Pattern 5: Meta quality signals
    if quality_ranking in ("BELOW_AVERAGE_10", "BELOW_AVERAGE_20", "BELOW_AVERAGE_35"):
        issues.append(f"META QUALITY: Ranked '{quality_ranking}' — improve visual quality or relevance")
    if conversion_ranking in ("BELOW_AVERAGE_10", "BELOW_AVERAGE_20", "BELOW_AVERAGE_35"):
        issues.append(f"META CONVERSION: Ranked '{conversion_ranking}' — landing page or offer not compelling vs competitors")
    if engagement_ranking in ("BELOW_AVERAGE_10", "BELOW_AVERAGE_20", "BELOW_AVERAGE_35"):
        issues.append(f"META ENGAGEMENT: Ranked '{engagement_ranking}' — ad not generating engagement vs similar ads")

    # Pattern 6: Good creative, bad conversion — psychology/LP issue
    if bl_ctr > 0 and ctr >= bl_ctr * 1.2 and results > 0 and cost_per_result:
        avg_cpr = baselines.avg_cpl or baselines.avg_cpa
        if avg_cpr and cost_per_result > avg_cpr * 1.3:
            issues.append(f"PSYCHOLOGY: Strong ad engagement (CTR {ctr:.2f}%) but poor conversion — landing page may lack social proof, urgency, or clear value proposition")

    # Pattern 7: High spend, low results, decent metrics — wrong objective
    if spend > 100 and results == 0 and ctr > 1.0 and clicks > 50:
        issues.append(f"OBJECTIVE MISMATCH: {clicks} clicks with 0 conversions — campaign objective may not match the desired action, or conversion tracking isn't set up")

    if not issues:
        if verdict == "scale":
            return "HEALTHY: Performing above baseline across all metrics"
        elif verdict == "hold":
            return "STABLE: Within normal range, no critical issues"
        return ""

    return " | ".join(issues)


def _build_evaluation(ad: dict, baselines: AccountBaselines, verdict: str,
                       score: int = 0, components: dict | None = None) -> dict:
    """Build a diagnostic context object comparing ad metrics to baselines."""
    spend = ad.get("spend", 0)
    cpl = ad.get("cost_per_result")
    roas = ad.get("roas")
    ctr = float(ad.get("ctr", 0))
    impressions = ad.get("impressions", 0)
    cpm = round(spend / impressions * 1000, 2) if impressions > 0 else 0
    clicks = ad.get("clicks", 0)
    cpc = round(spend / clicks, 2) if clicks > 0 else 0

    evaluation: dict[str, Any] = {
        "verdict": verdict,
        "score": score,
        "components": components or {},
        "dominant_type": baselines.dominant_type,
        "baseline_source": baselines.source,
        "quality_ranking": ad.get("quality_ranking"),
        "engagement_rate_ranking": ad.get("engagement_rate_ranking"),
        "conversion_rate_ranking": ad.get("conversion_rate_ranking"),
    }

    # Primary metric comparison
    if baselines.dominant_type == "leads" and cpl is not None and baselines.avg_cpl:
        pct = round((cpl - baselines.avg_cpl) / baselines.avg_cpl * 100, 1)
        evaluation["primary"] = {
            "metric": "CPL",
            "value": cpl,
            "baseline": baselines.avg_cpl,
            "delta_pct": pct,
            "status": "above" if pct > 0 else "below",
        }
    elif roas is not None and baselines.avg_roas:
        pct = round((roas - baselines.avg_roas) / baselines.avg_roas * 100, 1)
        evaluation["primary"] = {
            "metric": "ROAS",
            "value": roas,
            "baseline": baselines.avg_roas,
            "delta_pct": pct,
            "status": "above" if pct > 0 else "below",
        }

    # Secondary metrics — use per-objective baselines when available
    objective = ad.get("objective", "") or ""
    obj_bl = baselines.per_objective_creative.get(objective, {})
    bl_ctr = obj_bl.get("avg_ctr", baselines.avg_ctr)
    bl_cpc = obj_bl.get("avg_cpc", baselines.avg_cpc)
    bl_cpm = obj_bl.get("avg_cpm", baselines.avg_cpm)

    secondaries = []
    if bl_ctr > 0:
        pct = round((ctr - bl_ctr) / bl_ctr * 100, 1)
        secondaries.append({"metric": "CTR", "value": ctr, "baseline": bl_ctr, "delta_pct": pct})
    if bl_cpm > 0 and cpm > 0:
        pct = round((cpm - bl_cpm) / bl_cpm * 100, 1)
        secondaries.append({"metric": "CPM", "value": cpm, "baseline": bl_cpm, "delta_pct": pct})
    if bl_cpc > 0 and cpc > 0:
        pct = round((cpc - bl_cpc) / bl_cpc * 100, 1)
        secondaries.append({"metric": "CPC", "value": cpc, "baseline": bl_cpc, "delta_pct": pct})

    evaluation["secondaries"] = secondaries
    return evaluation


def build_diagnostic_prompt(ad: dict, baselines: AccountBaselines) -> str:
    """
    Build a rich diagnostic string for an ad to inject into OpenAI prompts.
    Example: "CPL $45 (Avg $12, +275%). CTR 0.4% (Avg 1.5%, -73%). CPM $15 (Normal)."
    """
    parts = []
    ev = ad.get("evaluation", {})
    primary = ev.get("primary")

    if primary:
        delta = primary["delta_pct"]
        direction = "+" if delta > 0 else ""
        severity = ""
        abs_d = abs(delta)
        if abs_d > 100:
            severity = "severely "
        elif abs_d > 50:
            severity = "significantly "

        metric_name = primary["metric"]
        # For cost metrics: above baseline is bad. For ROAS: above is good
        if metric_name in ("CPL", "CPA", "CPC"):
            perf = f"{severity}underperforming" if delta > 0 else f"{severity}outperforming"
        else:
            perf = f"{severity}outperforming" if delta > 0 else f"{severity}underperforming"

        parts.append(
            f"{metric_name}: ${primary['value']:.2f} (Account Avg: ${primary['baseline']:.2f}, {direction}{delta}% — {perf})"
            if metric_name != "ROAS"
            else f"ROAS: {primary['value']:.2f}x (Account Avg: {primary['baseline']:.2f}x, {direction}{delta}% — {perf})"
        )

    for sec in ev.get("secondaries", []):
        delta = sec["delta_pct"]
        direction = "+" if delta > 0 else ""
        abs_d = abs(delta)
        if abs_d < 15:
            note = "Normal"
        elif abs_d < 40:
            note = "Slightly off"
        else:
            note = "Flagged"
        parts.append(f"{sec['metric']}: {sec['value']:.2f} (Avg: {sec['baseline']:.2f}, {direction}{delta}%) [{note}]")

    qr = ad.get("quality_ranking")
    if qr and qr != "UNKNOWN":
        parts.append(f"Quality: {qr}")
    er = ad.get("engagement_rate_ranking")
    if er and er != "UNKNOWN":
        parts.append(f"Engagement: {er}")
    cr = ad.get("conversion_rate_ranking")
    if cr and cr != "UNKNOWN":
        parts.append(f"Conversion: {cr}")

    return " | ".join(parts) if parts else "Insufficient data for comparison."
