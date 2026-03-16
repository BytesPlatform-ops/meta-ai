"""
Optimization Co-Pilot routes — AI-powered proposal generation and execution.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from ...api.deps import get_current_user_id
from ...db.supabase_client import get_supabase
from ...services.optimization_copilot import analyze_account, analyze_specific_ad, apply_proposal

router = APIRouter(prefix="/optimize", tags=["optimization"])


@router.post("/analyze")
async def trigger_analysis(
    user_id: str = Depends(get_current_user_id),
    ad_account_id: str | None = None,
):
    """Analyze ad account performance and generate optimization proposals."""
    try:
        proposals = await analyze_account(user_id, ad_account_id)
        return {"proposals": proposals, "count": len(proposals)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")


class AnalyzeAdBody(BaseModel):
    ad_id: str
    campaign_id: str | None = None
    ad_name: str | None = None


@router.post("/analyze/ad")
async def trigger_ad_analysis(
    body: AnalyzeAdBody,
    user_id: str = Depends(get_current_user_id),
):
    """Analyze a specific ad and generate focused optimization proposals."""
    try:
        proposals = await analyze_specific_ad(
            user_id, body.ad_id, campaign_id=body.campaign_id, ad_name=body.ad_name,
        )
        return {"proposals": proposals, "count": len(proposals)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ad analysis failed: {e}")


@router.get("/proposals")
async def list_proposals(
    status: str = Query("pending", pattern="^(pending|approved|applied|rejected|failed|all)$"),
    user_id: str = Depends(get_current_user_id),
):
    """List optimization proposals for the current user."""
    supabase = get_supabase()
    query = (
        supabase.table("optimization_proposals")
        .select("*")
        .eq("user_id", user_id)
        .order("impact_score", desc=True)
    )
    if status != "all":
        query = query.eq("status", status)
    result = query.limit(50).execute()
    return {"proposals": result.data or []}


class UpdateStatusBody(BaseModel):
    status: str  # approved, rejected
    proposed_value: dict | None = None  # optional override (e.g. user-edited budget)


@router.patch("/proposals/{proposal_id}")
async def update_proposal_status(
    proposal_id: str,
    body: UpdateStatusBody,
    user_id: str = Depends(get_current_user_id),
):
    """Update a proposal's status (approve or reject), optionally overriding proposed_value."""
    if body.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Status must be 'approved' or 'rejected'")
    supabase = get_supabase()
    update_data: dict = {"status": body.status}
    if body.proposed_value is not None:
        update_data["proposed_value"] = body.proposed_value
    result = (
        supabase.table("optimization_proposals")
        .update(update_data)
        .eq("id", proposal_id)
        .eq("user_id", user_id)
        .eq("status", "pending")
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Proposal not found or not in pending status")
    return result.data[0]


@router.post("/apply/{proposal_id}")
async def apply_single_proposal(
    proposal_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Execute a single optimization proposal via Meta API."""
    try:
        result = await apply_proposal(user_id, proposal_id)
        if not result["success"]:
            raise HTTPException(status_code=502, detail=result.get("error", "Execution failed"))
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/apply-all")
async def apply_all_approved(
    user_id: str = Depends(get_current_user_id),
):
    """Execute all approved proposals."""
    supabase = get_supabase()
    proposals = (
        supabase.table("optimization_proposals")
        .select("id")
        .eq("user_id", user_id)
        .eq("status", "approved")
        .execute()
    )
    results = []
    for p in (proposals.data or []):
        try:
            r = await apply_proposal(user_id, p["id"])
            results.append(r)
        except Exception as e:
            results.append({"success": False, "proposal_id": p["id"], "error": str(e)})
    return {"results": results, "applied": sum(1 for r in results if r.get("success")), "failed": sum(1 for r in results if not r.get("success"))}
