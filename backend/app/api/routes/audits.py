"""
Account Audit routes — trigger and retrieve AI account health reports.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from ...api.deps import get_current_user_id
from ...db.supabase_client import get_supabase
from ...services.account_auditor import run_audit, generate_audit_proposals

router = APIRouter(prefix="/audits", tags=["audits"])


@router.post("/sync")
async def trigger_audit(
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
    ad_account_id: str | None = None,
):
    """Trigger a new account audit. Runs in background and returns the audit ID."""
    supabase = get_supabase()

    # Check for active ad account
    accounts = supabase.table("ad_accounts").select("id").eq("user_id", user_id).eq("is_active", True).limit(1).execute()
    if not accounts.data:
        raise HTTPException(status_code=400, detail="No active ad account found. Connect Meta first.")

    # Run audit (not in background so we can return the result directly for better UX)
    try:
        audit = await run_audit(user_id, ad_account_id)
        return audit
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audit failed: {e}")


@router.get("/latest")
async def get_latest_audit(
    user_id: str = Depends(get_current_user_id),
):
    """Get the most recent completed audit for the user."""
    supabase = get_supabase()
    result = (
        supabase.table("account_audits")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]


@router.post("/generate-actions")
async def generate_actions(
    user_id: str = Depends(get_current_user_id),
):
    """Generate executable optimization proposals from the latest completed audit."""
    supabase = get_supabase()

    # Find latest completed audit
    result = (
        supabase.table("account_audits")
        .select("id")
        .eq("user_id", user_id)
        .eq("status", "completed")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=400, detail="No completed audit found. Run an audit first.")

    audit_id = result.data[0]["id"]
    try:
        proposals = await generate_audit_proposals(user_id, audit_id)
        return {"proposals": proposals, "count": len(proposals)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Action generation failed: {e}")
