"""
Content Drafts routes — AI-generated content awaiting user approval.

GET    /api/v1/drafts              → list drafts (filterable by status)
GET    /api/v1/drafts/{draft_id}   → get single draft
POST   /api/v1/drafts              → create a draft (used by AI agent / seed)
PATCH  /api/v1/drafts/{draft_id}/approve   → approve & schedule
PATCH  /api/v1/drafts/{draft_id}/reject    → reject / request regeneration
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from typing import Optional

from ...api.deps import get_current_user_id
from ...db.supabase_client import get_supabase
from ...services.ad_executor import execute_approved_ad, execute_organic_post

router = APIRouter(prefix="/drafts", tags=["Content Drafts"])


class CreateDraftPayload(BaseModel):
    ad_account_id: Optional[str] = None
    draft_type: str = "organic"          # organic | paid
    headline: Optional[str] = None
    body_text: str
    image_url: Optional[str] = None
    cta_type: Optional[str] = None
    proposed_budget: Optional[float] = None
    targeting: Optional[dict] = None
    ai_reasoning: Optional[str] = None
    scheduled_for: Optional[str] = None


# ── List drafts ───────────────────────────────────────────────────────────────

@router.get("")
async def list_drafts(
    draft_status: Optional[str] = Query(None, alias="status"),
    user_id: str = Depends(get_current_user_id),
):
    """List drafts for the current user, optionally filtered by status."""
    supabase = get_supabase()
    query = (
        supabase.table("content_drafts")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
    )
    if draft_status:
        query = query.eq("status", draft_status)
    result = query.execute()
    return result.data


# ── Get single draft ──────────────────────────────────────────────────────────

@router.get("/{draft_id}")
async def get_draft(draft_id: str, user_id: str = Depends(get_current_user_id)):
    supabase = get_supabase()
    result = (
        supabase.table("content_drafts")
        .select("*")
        .eq("id", draft_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    return result.data[0]


# ── Create draft (AI agent or seed) ──────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_draft(
    payload: CreateDraftPayload,
    user_id: str = Depends(get_current_user_id),
):
    supabase = get_supabase()
    data = {
        "user_id": user_id,
        "draft_type": payload.draft_type,
        "headline": payload.headline,
        "body_text": payload.body_text,
        "image_url": payload.image_url,
        "cta_type": payload.cta_type,
        "proposed_budget": payload.proposed_budget,
        "targeting": payload.targeting or {},
        "ai_reasoning": payload.ai_reasoning,
        "scheduled_for": payload.scheduled_for,
        "status": "pending",
    }
    if payload.ad_account_id:
        data["ad_account_id"] = payload.ad_account_id
    result = supabase.table("content_drafts").insert(data).execute()
    return result.data[0] if result.data else data


# ── Update draft (attach creative, etc.) ─────────────────────────────────────

class UpdateDraftPayload(BaseModel):
    headline: Optional[str] = None
    body_text: Optional[str] = None
    image_url: Optional[str] = None
    cta_type: Optional[str] = None
    proposed_budget: Optional[float] = None
    draft_type: Optional[str] = None
    targeting: Optional[dict] = None
    pixel_id: Optional[str] = None
    conversion_event: Optional[str] = None
    thumbnail_url: Optional[str] = None


@router.patch("/{draft_id}")
async def update_draft(
    draft_id: str,
    payload: UpdateDraftPayload,
    user_id: str = Depends(get_current_user_id),
):
    """Update a pending draft — edit any field before approving."""
    supabase = get_supabase()
    existing = (
        supabase.table("content_drafts")
        .select("id, status")
        .eq("id", draft_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    if existing.data[0]["status"] != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only pending drafts can be updated")

    updates = {}
    for field in ("headline", "body_text", "image_url", "cta_type", "proposed_budget", "draft_type", "targeting", "pixel_id", "conversion_event", "thumbnail_url"):
        val = getattr(payload, field)
        if val is not None:
            updates[field] = val

    if not updates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")

    result = (
        supabase.table("content_drafts")
        .update(updates)
        .eq("id", draft_id)
        .eq("user_id", user_id)
        .execute()
    )
    return result.data[0] if result.data else {"id": draft_id, **updates}


# ── Approve & Schedule ────────────────────────────────────────────────────────

@router.patch("/{draft_id}/approve")
async def approve_draft(
    draft_id: str,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
):
    """
    Mark a draft as approved.
    For paid ads, this triggers the autonomous MCP execution pipeline
    (targeting research → payload assembly → Meta API calls) in the background.
    """
    supabase = get_supabase()

    # Verify ownership and current status
    existing = (
        supabase.table("content_drafts")
        .select("id, status, draft_type")
        .eq("id", draft_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    if existing.data[0]["status"] != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Draft is not in pending status")

    result = (
        supabase.table("content_drafts")
        .update({"status": "approved"})
        .eq("id", draft_id)
        .eq("user_id", user_id)
        .execute()
    )

    # Trigger the appropriate execution pipeline in the background
    draft_type = existing.data[0]["draft_type"]
    if draft_type == "paid":
        background_tasks.add_task(execute_approved_ad, draft_id)
    elif draft_type == "organic":
        background_tasks.add_task(execute_organic_post, draft_id)

    draft_data = result.data[0] if result.data else {"id": draft_id, "status": "approved"}
    return {
        **draft_data,
        "execution_triggered": True,
    }


# ── Reject / Regenerate ──────────────────────────────────────────────────────

@router.patch("/{draft_id}/reject")
async def reject_draft(draft_id: str, user_id: str = Depends(get_current_user_id)):
    """Reject a draft — marks it for regeneration."""
    supabase = get_supabase()

    existing = (
        supabase.table("content_drafts")
        .select("id, status")
        .eq("id", draft_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    if existing.data[0]["status"] != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Draft is not in pending status")

    result = (
        supabase.table("content_drafts")
        .update({"status": "rejected"})
        .eq("id", draft_id)
        .eq("user_id", user_id)
        .execute()
    )
    return result.data[0] if result.data else {"id": draft_id, "status": "rejected"}
