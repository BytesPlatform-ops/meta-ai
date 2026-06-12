"""
Workspace CRUD routes.

GET    /api/v1/workspaces                  → list all workspaces for current user
POST   /api/v1/workspaces                  → create a new workspace
GET    /api/v1/workspaces/{workspace_id}   → get single workspace (with auth check)
PUT    /api/v1/workspaces/{workspace_id}   → update workspace config / Meta credentials
DELETE /api/v1/workspaces/{workspace_id}   → delete workspace (prevents deleting last one)
GET    /api/v1/workspaces/page-intel       → fetch FB page details for auto-fill
"""
import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ...api.deps import get_current_user_id, get_workspace_id
from ...db.supabase_client import get_supabase
from ...core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


# ── Pydantic Schemas ─────────────────────────────────────────────

class WorkspaceCreate(BaseModel):
    name: str = "My Business"
    meta_ad_account_id: str | None = None
    meta_page_id: str | None = None
    meta_pixel_id: str | None = None
    meta_ig_actor_id: str | None = None
    meta_access_token: str | None = None
    business_name: str | None = None
    business_description: str | None = None
    target_audience: str | None = None
    website_url: str | None = None
    target_country: str = "PK"
    industry_niche: str | None = None
    tracking_mode: str = "whatsapp_cod"


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    meta_ad_account_id: str | None = None
    meta_page_id: str | None = None
    meta_pixel_id: str | None = None
    meta_ig_actor_id: str | None = None
    meta_access_token: str | None = None
    business_name: str | None = None
    business_description: str | None = None
    target_audience: str | None = None
    website_url: str | None = None
    target_country: str | None = None
    industry_niche: str | None = None
    tracking_mode: str | None = None
    website_intel: dict | None = None
    is_active: bool | None = None


class WorkspaceResponse(BaseModel):
    id: str
    user_id: str
    name: str
    meta_ad_account_id: str | None = None
    meta_page_id: str | None = None
    meta_pixel_id: str | None = None
    meta_ig_actor_id: str | None = None
    meta_access_token: str | None = None
    business_name: str | None = None
    business_description: str | None = None
    target_audience: str | None = None
    website_url: str | None = None
    target_country: str | None = None
    industry_niche: str | None = None
    tracking_mode: str | None = None
    website_intel: dict | None = None
    website_scraped_at: str | None = None
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None


# ── Helpers ──────────────────────────────────────────────────────

def _verify_ownership(workspace: dict | None, user_id: str) -> dict:
    """Raise 404 if workspace doesn't exist or doesn't belong to user."""
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found.",
        )
    if workspace.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found.",
        )
    return workspace


# ── Routes ───────────────────────────────────────────────────────

@router.get("/")
async def list_workspaces(user_id: str = Depends(get_current_user_id)):
    """List all workspaces belonging to the current user."""
    supabase = get_supabase()
    result = (
        supabase.table("workspaces")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at")
        .execute()
    )
    return {"workspaces": result.data or []}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreate,
    user_id: str = Depends(get_current_user_id),
):
    """Create a new workspace linked to the current user."""
    supabase = get_supabase()
    payload = {"user_id": user_id, **body.model_dump(exclude_none=True)}
    result = supabase.table("workspaces").insert(payload).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create workspace.",
        )
    return result.data[0]


@router.get("/page-intel")
async def get_page_intel(
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """
    Fetch Facebook Page details for auto-filling workspace fields.
    Uses the workspace's meta_page_id + access token from ad_accounts.
    Returns structured business intel from the page's Graph API data.
    """
    supabase = get_supabase()
    settings = get_settings()

    # Get workspace's page_id
    ws_result = (
        supabase.table("workspaces")
        .select("meta_page_id, meta_access_token")
        .eq("id", workspace_id)
        .eq("user_id", user_id)
        .limit(1)
        .maybe_single()
        .execute()
    )
    if not ws_result.data or not ws_result.data.get("meta_page_id"):
        return {"intel": None, "error": "No page linked to this workspace"}

    page_id = ws_result.data["meta_page_id"]
    access_token = ws_result.data.get("meta_access_token")

    # Fallback to ad_accounts token if workspace doesn't have one
    if not access_token:
        aa_result = (
            supabase.table("ad_accounts")
            .select("access_token")
            .eq("workspace_id", workspace_id)
            .eq("is_active", True)
            .limit(1)
            .maybe_single()
            .execute()
        )
        access_token = aa_result.data.get("access_token") if aa_result.data else None

    if not access_token:
        return {"intel": None, "error": "No access token available"}

    # Fetch page details from Graph API
    base = f"https://graph.facebook.com/{settings.META_API_VERSION}"
    fields = "name,about,description,category,category_list,website,phone,emails,location,bio,fan_count"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{base}/{page_id}",
                params={"fields": fields, "access_token": access_token},
            )
            resp.raise_for_status()
            page_data = resp.json()
    except Exception as e:
        logger.warning(f"Failed to fetch page details for {page_id}: {e}")
        return {"intel": None, "error": f"Failed to fetch page details: {e}"}

    # Map page data to workspace fields
    categories = page_data.get("category_list", [])
    category_names = [c.get("name", "") for c in categories if c.get("name")]
    primary_category = page_data.get("category", "")

    # Build niche from categories
    niche = ", ".join(category_names[:3]) if category_names else primary_category

    intel = {
        "business_name": page_data.get("name", ""),
        "business_description": page_data.get("about") or page_data.get("description") or page_data.get("bio") or "",
        "industry_niche": niche,
        "website_url": page_data.get("website", ""),
        "phone": page_data.get("phone", ""),
        "location": page_data.get("location", {}),
        "fan_count": page_data.get("fan_count", 0),
        "category": primary_category,
        "categories": category_names,
    }

    return {"intel": intel}


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Get a single workspace by ID. Verifies ownership."""
    supabase = get_supabase()
    result = (
        supabase.table("workspaces")
        .select("*")
        .eq("id", workspace_id)
        .limit(1)
        .execute()
    )
    ws = result.data[0] if result.data else None
    _verify_ownership(ws, user_id)
    return ws


@router.put("/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    body: WorkspaceUpdate,
    user_id: str = Depends(get_current_user_id),
):
    """Update workspace config (Meta credentials, business info, etc.)."""
    supabase = get_supabase()

    # Verify ownership first
    existing = (
        supabase.table("workspaces")
        .select("id, user_id")
        .eq("id", workspace_id)
        .limit(1)
        .execute()
    )
    _verify_ownership(
        existing.data[0] if existing.data else None,
        user_id,
    )

    # Only send fields that were explicitly set
    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update.",
        )

    result = (
        supabase.table("workspaces")
        .update(update_data)
        .eq("id", workspace_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Update failed.",
        )

    # Mirror Page / IG identity onto the workspace's ad_account rows. The
    # ad executor reads ``ad_accounts.facebook_page_id`` (NOT
    # ``workspaces.meta_page_id``) when staging campaigns, so the two need
    # to stay in sync. Without this mirror, picking a Page in the
    # PagePickerModal silently leaves the ad set running from whichever
    # stale Page was first stored on the ad_account row — and the
    # WhatsApp/Instagram identities the modal showed don't match what
    # actually goes live.
    page_changes: dict = {}
    if "meta_page_id" in update_data and update_data["meta_page_id"]:
        page_changes["facebook_page_id"] = update_data["meta_page_id"]
    if "meta_ig_actor_id" in update_data:
        # IG actor can legitimately be set to None to clear it.
        page_changes["instagram_actor_id"] = update_data["meta_ig_actor_id"]
    if page_changes:
        try:
            supabase.table("ad_accounts").update(page_changes).eq(
                "workspace_id", workspace_id
            ).execute()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "Could not mirror page identity to ad_accounts: %s", e
            )

    return result.data[0]


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    Delete a workspace. Prevents deleting the user's last workspace
    so they always have at least one.
    """
    supabase = get_supabase()

    # Verify ownership
    existing = (
        supabase.table("workspaces")
        .select("id, user_id")
        .eq("id", workspace_id)
        .limit(1)
        .execute()
    )
    _verify_ownership(
        existing.data[0] if existing.data else None,
        user_id,
    )

    # Prevent deleting the last workspace
    count_result = (
        supabase.table("workspaces")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .execute()
    )
    if count_result.count is not None and count_result.count <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your only workspace. Create another one first.",
        )

    supabase.table("workspaces").delete().eq("id", workspace_id).execute()
    return {"success": True, "message": "Workspace deleted."}
