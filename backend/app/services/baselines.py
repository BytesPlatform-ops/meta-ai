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
        }


# ── Calculator ───────────────────────────────────────────────────────────────

async def calculate_account_baselines(
    ad_account_id: str,
    access_token: str,
    user_id: str | None = None,
) -> AccountBaselines:
    """
    Query 30-day ad data via MCP and compute the account's unique baselines.
    Falls back to user-defined target_cost_per_result if no historical data.
    """
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

        ads: list[dict] = ad_data.get("ads", [])
        if not ads:
            return _fallback_baselines(user_id)

        total_spend = sum(a.get("spend", 0) for a in ads)
        total_impressions = sum(a.get("impressions", 0) for a in ads)
        total_clicks = sum(a.get("clicks", 0) for a in ads)
        total_leads = sum(a.get("leads", 0) for a in ads)
        total_purchases = sum(a.get("purchases", 0) for a in ads)
        dominant_type = ad_data.get("dominant_result_type", "purchases")

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

        logger.info(
            f"Baselines for {ad_account_id}: "
            f"CPL=${avg_cpl}, CPA=${avg_cpa}, ROAS={avg_roas}, "
            f"CTR={avg_ctr}%, CPC=${avg_cpc}, CPM=${avg_cpm} "
            f"(from {len(ads)} ads, {dominant_type})"
        )
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


# ── Evaluation helpers ───────────────────────────────────────────────────────

def evaluate_ad(
    ad: dict,
    baselines: AccountBaselines,
) -> dict:
    """
    Evaluate a single ad against account baselines.
    Returns the ad dict enriched with verdict, diagnostic context, and comparison data.
    """
    spend = ad.get("spend", 0)
    results = ad.get("results", 0)
    result_type = ad.get("result_type", "none")
    ctr = float(ad.get("ctr", 0))
    cpl = ad.get("cost_per_result")
    roas = ad.get("roas")

    # No results at all
    if results == 0 and spend > 0:
        verdict = "kill" if spend >= 2000 else "no_results"
        return {
            **ad,
            "verdict": verdict,
            "evaluation": _build_evaluation(ad, baselines, verdict),
        }

    # Determine primary metric comparison
    if result_type == "leads" or baselines.dominant_type == "leads":
        verdict = _evaluate_cost_metric(cpl, baselines, "cpl")
    elif result_type == "purchases" or baselines.dominant_type == "purchases":
        if roas is not None:
            verdict = _evaluate_value_metric(roas, baselines, "roas")
        else:
            verdict = _evaluate_cost_metric(cpl, baselines, "cpa")
    else:
        # Traffic / engagement — use CTR as primary
        verdict = _evaluate_value_metric(ctr, baselines, "ctr")

    return {
        **ad,
        "verdict": verdict,
        "evaluation": _build_evaluation(ad, baselines, verdict),
    }


def _evaluate_cost_metric(
    value: float | None,
    baselines: AccountBaselines,
    metric: str,
) -> str:
    """Evaluate a cost metric (lower is better): CPL, CPA, CPC."""
    if value is None or value <= 0:
        return "no_data"

    win = baselines.winning_threshold(metric)
    lose = baselines.losing_threshold(metric)

    if win is None or lose is None:
        # No baseline — can't evaluate properly
        return "hold"

    if value <= win:
        return "scale"
    if value >= lose:
        return "underperforming"
    return "hold"


def _evaluate_value_metric(
    value: float | None,
    baselines: AccountBaselines,
    metric: str,
) -> str:
    """Evaluate a value metric (higher is better): ROAS, CTR."""
    if value is None:
        return "no_data"

    win = baselines.winning_threshold(metric)
    lose = baselines.losing_threshold(metric)

    if win is None or lose is None:
        return "hold"

    if value >= win:
        return "scale"
    if value <= lose:
        return "underperforming"
    return "hold"


def _build_evaluation(ad: dict, baselines: AccountBaselines, verdict: str) -> dict:
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
        "dominant_type": baselines.dominant_type,
        "baseline_source": baselines.source,
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

    # Secondary metrics
    secondaries = []
    if baselines.avg_ctr > 0:
        pct = round((ctr - baselines.avg_ctr) / baselines.avg_ctr * 100, 1)
        secondaries.append({"metric": "CTR", "value": ctr, "baseline": baselines.avg_ctr, "delta_pct": pct})
    if baselines.avg_cpm > 0 and cpm > 0:
        pct = round((cpm - baselines.avg_cpm) / baselines.avg_cpm * 100, 1)
        secondaries.append({"metric": "CPM", "value": cpm, "baseline": baselines.avg_cpm, "delta_pct": pct})
    if baselines.avg_cpc > 0 and cpc > 0:
        pct = round((cpc - baselines.avg_cpc) / baselines.avg_cpc * 100, 1)
        secondaries.append({"metric": "CPC", "value": cpc, "baseline": baselines.avg_cpc, "delta_pct": pct})

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

    return " | ".join(parts) if parts else "Insufficient data for comparison."
