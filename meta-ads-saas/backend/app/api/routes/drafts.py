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

from ...api.deps import get_current_user_id, get_workspace_id
from ...db.supabase_client import get_supabase
from ...services.ad_executor import execute_approved_ad, execute_organic_post, validate_ab_drafts, execute_ab_test
from ...services.mcp_client import MCPClient

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
    workspace_id: str = Depends(get_workspace_id),
):
    """List drafts for the current workspace, optionally filtered by status."""
    supabase = get_supabase()
    query = (
        supabase.table("content_drafts")
        .select("*")
        .eq("workspace_id", workspace_id)
        .order("created_at", desc=True)
    )
    if draft_status:
        query = query.eq("status", draft_status)
    result = query.execute()
    return result.data


# ── Get single draft ──────────────────────────────────────────────────────────

@router.get("/{draft_id}")
async def get_draft(
    draft_id: str,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    supabase = get_supabase()
    result = (
        supabase.table("content_drafts")
        .select("*")
        .eq("id", draft_id)
        .eq("workspace_id", workspace_id)
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
    workspace_id: str = Depends(get_workspace_id),
):
    supabase = get_supabase()
    data = {
        "user_id": user_id,
        "workspace_id": workspace_id,
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
    destination_type: Optional[str] = None
    whatsapp_number: Optional[str] = None
    media_items: Optional[list] = None
    lead_form_id: Optional[str] = None
    selected_messaging_apps: Optional[list] = None
    call_phone_number: Optional[str] = None
    # Per-draft destination URL override — used when the user wants the ad to
    # link to a specific page (e.g. /onboarding/sign-up?tab=signup) instead of
    # the workspace/product default. Empty string clears the override.
    destination_url: Optional[str] = None
    # Multi-country support: comma-separated country codes (e.g. "US,GB").
    # Highest-priority geo signal — overrides workspace + product + targeting JSON.
    target_country: Optional[str] = None
    # Explicit campaign-level objective override. When set (e.g. "OUTCOME_LEADS"),
    # ad_executor uses this verbatim instead of inferring from destination_type.
    # Without this declaration, Pydantic silently drops the UI's selection.
    campaign_objective: Optional[str] = None
    # Carousel toggle. When true and the draft has 2+ media_items, the publish
    # pipeline builds ONE carousel ad (swipeable child_attachments) instead of
    # N separate A/B ads.
    is_carousel: Optional[bool] = None
    # Retry-from-failed support: client may set status="pending" + error_message=null
    # to recover a failed draft after attaching a missing creative. Validated below.
    status: Optional[str] = None
    error_message: Optional[str] = None


@router.patch("/{draft_id}")
async def update_draft(
    draft_id: str,
    payload: UpdateDraftPayload,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Update a pending draft — edit any field before approving."""
    supabase = get_supabase()
    existing = (
        supabase.table("content_drafts")
        .select("id, status")
        .eq("id", draft_id)
        .eq("workspace_id", workspace_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    current_status = existing.data[0]["status"]
    if current_status not in ("pending", "failed"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only pending or failed drafts can be updated")

    updates = {}
    for field in ("headline", "body_text", "image_url", "cta_type", "proposed_budget", "draft_type", "targeting", "pixel_id", "conversion_event", "thumbnail_url", "destination_type", "whatsapp_number", "media_items", "lead_form_id", "selected_messaging_apps", "call_phone_number", "target_country", "destination_url", "campaign_objective", "is_carousel"):
        val = getattr(payload, field)
        if val is not None:
            updates[field] = val
    # Allow explicit clearing of target_country / destination_url (None vs not-supplied)
    if payload.target_country is None and "target_country" in payload.model_fields_set:
        updates["target_country"] = None
    if payload.destination_url is None and "destination_url" in payload.model_fields_set:
        updates["destination_url"] = None

    # Allow recovering a failed draft by transitioning it back to pending. The only
    # status transition accepted via this endpoint is failed → pending; anything else
    # would let users force drafts into approved/active without going through the
    # publish pipeline.
    if payload.status is not None:
        if current_status == "failed" and payload.status == "pending":
            updates["status"] = "pending"
            updates["error_message"] = None  # always clear stale error on recovery
        elif payload.status == current_status:
            pass  # no-op
        else:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Status transition {current_status} → {payload.status} not allowed via this endpoint",
            )
    elif payload.error_message is None and "error_message" in payload.model_fields_set:
        # Client explicitly cleared error_message without changing status
        updates["error_message"] = None

    if not updates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")

    result = (
        supabase.table("content_drafts")
        .update(updates)
        .eq("id", draft_id)
        .eq("workspace_id", workspace_id)
        .execute()
    )
    return result.data[0] if result.data else {"id": draft_id, **updates}


# ── Approve & Schedule ────────────────────────────────────────────────────────

@router.patch("/{draft_id}/approve")
async def approve_draft(
    draft_id: str,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
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
        .eq("workspace_id", workspace_id)
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
        .eq("workspace_id", workspace_id)
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


# ── A/B Test Launch ──────────────────────────────────────────────────────────

class LaunchAbBody(BaseModel):
    draft_ids: list[str]


@router.post("/launch-ab")
async def launch_ab_test(
    body: LaunchAbBody,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """
    Launch multiple drafts as an A/B test under a single Campaign + Ad Set.
    All drafts must share the same product_id and destination_type.
    """
    if len(body.draft_ids) < 2:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A/B test requires at least 2 drafts")

    supabase = get_supabase()

    # Load all drafts and verify ownership
    drafts = []
    for did in body.draft_ids:
        result = (
            supabase.table("content_drafts")
            .select("*")
            .eq("id", did)
            .eq("workspace_id", workspace_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Draft {did} not found")
        drafts.append(result.data[0])

    # Validate compatibility
    error = validate_ab_drafts(drafts)
    if error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, error)

    # Execute in background
    background_tasks.add_task(execute_ab_test, body.draft_ids)

    return {
        "draft_ids": body.draft_ids,
        "draft_count": len(body.draft_ids),
        "execution_triggered": True,
        "message": f"A/B test with {len(body.draft_ids)} variants is being launched",
    }


# ── Reject / Regenerate ──────────────────────────────────────────────────────

@router.patch("/{draft_id}/reject")
async def reject_draft(
    draft_id: str,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Reject a draft — marks it for regeneration."""
    supabase = get_supabase()

    existing = (
        supabase.table("content_drafts")
        .select("id, status")
        .eq("id", draft_id)
        .eq("workspace_id", workspace_id)
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
        .eq("workspace_id", workspace_id)
        .execute()
    )
    return result.data[0] if result.data else {"id": draft_id, "status": "rejected"}


# ── Pause & Reset to Pending ─────────────────────────────────────────────────

@router.patch("/{draft_id}/pause")
async def pause_draft(
    draft_id: str,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Pause a live ad on Meta and reset the draft back to pending for editing."""
    supabase = get_supabase()

    existing = (
        supabase.table("content_drafts")
        .select("id, status, meta_ad_id, ad_account_id, user_id")
        .eq("id", draft_id)
        .eq("workspace_id", workspace_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")

    draft = existing.data[0]
    if draft["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only active drafts can be paused")

    # Pause the ad on Meta if we have an ad ID
    if draft.get("meta_ad_id") and draft.get("ad_account_id"):
        token_row = (
            supabase.table("ad_accounts")
            .select("access_token")
            .eq("ad_account_id", draft["ad_account_id"])
            .eq("user_id", user_id)
            .eq("workspace_id", workspace_id)
            .execute()
        )
        if token_row.data:
            mcp = MCPClient()
            await mcp.update_entity_status(
                draft["meta_ad_id"], "PAUSED", token_row.data[0]["access_token"]
            )

    # Reset draft to pending
    result = (
        supabase.table("content_drafts")
        .update({"status": "pending"})
        .eq("id", draft_id)
        .eq("workspace_id", workspace_id)
        .execute()
    )
    return result.data[0] if result.data else {"id": draft_id, "status": "pending"}
