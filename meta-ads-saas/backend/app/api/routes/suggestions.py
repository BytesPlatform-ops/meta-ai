"""
Campaign Suggestions routes — HITL Co-Pilot endpoints.

POST /api/v1/suggestions/analyze-now   → trigger fresh optimization
GET  /api/v1/suggestions               → list PENDING suggestions
POST /api/v1/suggestions/resolve       → approve or reject a suggestion
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ...api.deps import get_current_user_id
from ...db.supabase_client import get_supabase
from ...services.optimization_engine import run_optimization, execute_suggestion
from ...services.mcp_client import MCPError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/suggestions", tags=["Campaign Suggestions"])


# ── Analyze Now ───────────────────────────────────────────────────────────────

@router.post("/analyze-now")
async def analyze_now(user_id: str = Depends(get_current_user_id)):
    """
    Manually trigger the AI optimization engine.
    Fetches fresh data via MCP, generates LLM suggestions, saves as PENDING.
    """
    try:
        suggestions = await run_optimization(user_id)
        return {
            "success": True,
            "suggestions_count": len(suggestions),
            "suggestions": suggestions,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Analyze-now failed for user %s", user_id)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")


# ── List Pending Suggestions ──────────────────────────────────────────────────

@router.get("")
async def list_suggestions(
    status_filter: str = "PENDING",
    user_id: str = Depends(get_current_user_id),
):
    """List suggestions for the current user, filtered by status."""
    supabase = get_supabase()
    query = (
        supabase.table("campaign_suggestions")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
    )
    if status_filter != "all":
        query = query.eq("status", status_filter)
    result = query.limit(50).execute()
    return result.data or []


# ── Resolve Suggestion ────────────────────────────────────────────────────────

class ResolveSuggestionRequest(BaseModel):
    suggestion_id: str
    resolution: str  # "APPROVE" or "REJECT"


@router.post("/resolve")
async def resolve_suggestion(
    body: ResolveSuggestionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Approve or reject a suggestion.
    APPROVE → execute the action via MCP, then mark as APPROVED.
    REJECT  → mark as REJECTED, no action taken.
    """
    if body.resolution not in ("APPROVE", "REJECT"):
        raise HTTPException(
            status_code=400,
            detail="resolution must be 'APPROVE' or 'REJECT'",
        )

    supabase = get_supabase()

    # Fetch the suggestion
    result = (
        supabase.table("campaign_suggestions")
        .select("*, ad_accounts!campaign_suggestions_ad_account_id_fkey(access_token, meta_account_id)")
        .eq("id", body.suggestion_id)
        .eq("user_id", user_id)
        .eq("status", "PENDING")
        .execute()
    )
    if not result.data:
        # Fallback: try without join
        result = (
            supabase.table("campaign_suggestions")
            .select("*")
            .eq("id", body.suggestion_id)
            .eq("user_id", user_id)
            .eq("status", "PENDING")
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Suggestion not found or already resolved")

    suggestion = result.data[0]

    # REJECT — just update status
    if body.resolution == "REJECT":
        supabase.table("campaign_suggestions").update({
            "status": "REJECTED",
        }).eq("id", body.suggestion_id).execute()
        return {"success": True, "status": "REJECTED", "suggestion_id": body.suggestion_id}

    # APPROVE — execute via MCP, then update status
    # Get access token from ad_accounts
    access_token = None
    joined = suggestion.get("ad_accounts")
    if joined and isinstance(joined, dict):
        access_token = joined.get("access_token")

    if not access_token and suggestion.get("ad_account_id"):
        acct_result = (
            supabase.table("ad_accounts")
            .select("access_token")
            .eq("id", suggestion["ad_account_id"])
            .execute()
        )
        if acct_result.data:
            access_token = acct_result.data[0]["access_token"]

    if not access_token:
        raise HTTPException(status_code=400, detail="No access token found for ad account")

    try:
        exec_result = await execute_suggestion(suggestion, access_token)
        supabase.table("campaign_suggestions").update({
            "status": "APPROVED",
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", body.suggestion_id).execute()

        # Log the action
        try:
            supabase.table("campaign_logs").insert({
                "user_id": user_id,
                "ad_account_id": suggestion.get("ad_account_id"),
                "action": "ai_recommendation",
                "meta_campaign_id": suggestion["campaign_id"],
                "payload": {
                    "suggested_action": suggestion["suggested_action"],
                    "action_payload": suggestion.get("action_payload"),
                },
                "ai_reasoning": suggestion["analysis_reasoning"],
                "status": "success",
            }).execute()
        except Exception:
            pass  # logging is best-effort

        return {
            "success": True,
            "status": "APPROVED",
            "suggestion_id": body.suggestion_id,
            "execution_result": exec_result,
        }

    except (MCPError, ValueError) as e:
        # Mark as FAILED so user can retry
        supabase.table("campaign_suggestions").update({
            "status": "FAILED",
        }).eq("id", body.suggestion_id).execute()
        raise HTTPException(status_code=502, detail=f"Execution failed: {e}")
