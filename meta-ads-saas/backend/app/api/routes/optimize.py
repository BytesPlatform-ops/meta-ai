"""
Optimization Co-Pilot routes — AI-powered proposal generation and execution.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from ...api.deps import get_current_user_id, get_workspace_id
from ...db.supabase_client import get_supabase
from ...services.optimization_copilot import analyze_account, analyze_specific_ad, apply_proposal, generate_diagnosis_fix

router = APIRouter(prefix="/optimize", tags=["optimization"])


@router.post("/analyze")
async def trigger_analysis(
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
    ad_account_id: str | None = None,
):
    """Analyze ad account performance and generate optimization proposals."""
    print(f"[ROUTE] /optimize/analyze called: user={user_id}, ws={workspace_id}, ad_account={ad_account_id}", flush=True)
    try:
        proposals = await analyze_account(user_id, ad_account_id, workspace_id=workspace_id)
        print(f"[ROUTE] analyze_account returned {len(proposals)} proposals", flush=True)
        return {"proposals": proposals, "count": len(proposals)}
    except ValueError as e:
        print(f"[ROUTE] ValueError: {e}", flush=True)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"[ROUTE] Exception: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")


class AnalyzeAdBody(BaseModel):
    ad_id: str
    campaign_id: str | None = None
    ad_name: str | None = None


@router.post("/analyze/ad")
async def trigger_ad_analysis(
    body: AnalyzeAdBody,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Analyze a specific ad and generate focused optimization proposals."""
    try:
        proposals = await analyze_specific_ad(
            user_id, body.ad_id, campaign_id=body.campaign_id, ad_name=body.ad_name,
            workspace_id=workspace_id,
        )
        return {"proposals": proposals, "count": len(proposals)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ad analysis failed: {e}")


class BridgeAuditBody(BaseModel):
    ad_id: str
    ad_name: str = ""
    adset_id: str = ""
    diagnosis: str
    campaign_id: str = ""


@router.post("/bridge-audit")
async def bridge_audit_diagnosis(
    body: BridgeAuditBody,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Generate a targeted fix proposal from an audit diagnosis."""
    try:
        proposals = await generate_diagnosis_fix(
            user_id, body.ad_id, body.diagnosis,
            ad_name=body.ad_name, adset_id=body.adset_id,
            campaign_id=body.campaign_id, workspace_id=workspace_id,
        )
        return {"proposals": proposals, "count": len(proposals)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bridge failed: {e}")


@router.get("/proposals")
async def list_proposals(
    status: str = Query("pending", pattern="^(pending|approved|applied|rejected|failed|all)$"),
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """List optimization proposals for the current user."""
    supabase = get_supabase()
    query = (
        supabase.table("optimization_proposals")
        .select("*")
        .eq("workspace_id", workspace_id)
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
    workspace_id: str = Depends(get_workspace_id),
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
        .eq("workspace_id", workspace_id)
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
    workspace_id: str = Depends(get_workspace_id),
):
    """Execute a single optimization proposal via Meta API."""
    try:
        result = await apply_proposal(user_id, proposal_id)
        if not result["success"]:
            raise HTTPException(status_code=502, detail=result.get("error", "Execution failed"))
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/generate-copy/{proposal_id}")
async def generate_copy_for_proposal(
    proposal_id: str,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Generate ad copy for a creative proposal using the content generator with full product/brand context."""
    supabase = get_supabase()

    # Fetch the proposal
    result = (
        supabase.table("optimization_proposals")
        .select("*")
        .eq("id", proposal_id)
        .eq("workspace_id", workspace_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Proposal not found")

    proposal = result.data
    if proposal["action_type"] not in ("refresh_creative", "mutate_winner"):
        raise HTTPException(status_code=400, detail="Not a creative proposal")

    proposed = proposal["proposed_value"] or {}
    creative_direction = proposed.get("creative_direction", "")
    current_hook = proposed.get("current_hook", "")
    target_hook = proposed.get("target_hook", "")
    new_cta = proposed.get("new_cta", "")

    # Build guidance from creative direction
    guidance = f"CREATIVE DIRECTION FROM AI COPILOT:\n"
    if creative_direction:
        guidance += f"{creative_direction}\n"
    if current_hook and target_hook:
        guidance += f"Current ad uses {current_hook} hook — write copy using {target_hook} hook instead.\n"
    if new_cta:
        guidance += f"CTA: {new_cta}\n"
    guidance += "Generate exactly 1 ad variation following this direction."

    try:
        from ...services.content_generator import generate_drafts
        drafts = await generate_drafts(
            user_id=user_id,
            count=1,
            user_guidance=guidance,
            workspace_id=workspace_id,
        )

        if not drafts:
            raise HTTPException(status_code=500, detail="Content generator returned no drafts")

        draft = drafts[0]
        new_body_text = draft.get("body_text", "")
        new_headline = draft.get("headline", "")

        # Update the proposal's proposed_value with the generated copy
        updated_proposed = {
            **proposed,
            "new_body_text": new_body_text,
            "new_headline": new_headline,
            "copy_source": "content_generator",
        }
        supabase.table("optimization_proposals").update({
            "proposed_value": updated_proposed,
        }).eq("id", proposal_id).execute()

        return {
            "new_body_text": new_body_text,
            "new_headline": new_headline,
            "creative_direction": creative_direction,
            "proposal_id": proposal_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Copy generation failed: {e}")


@router.post("/apply-all")
async def apply_all_approved(
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Execute all approved proposals."""
    supabase = get_supabase()
    proposals = (
        supabase.table("optimization_proposals")
        .select("id")
        .eq("workspace_id", workspace_id)
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
