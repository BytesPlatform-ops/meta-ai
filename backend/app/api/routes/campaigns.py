"""
Campaign management routes — proxies requests through the MCP client
to the Meta Marketing API MCP server.
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from ...api.deps import get_current_user_id
from ...services.mcp_client import mcp_client, MCPError
from ...db.supabase_client import get_supabase
from ...core.config import get_settings

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


def _get_account_token(user_id: str, ad_account_id: str) -> str:
    """Fetch the access token for a given ad account, scoped to the user."""
    supabase = get_supabase()
    result = (
        supabase.table("ad_accounts")
        .select("access_token")
        .eq("user_id", user_id)
        .eq("meta_account_id", ad_account_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Ad account not found")
    return result.data["access_token"]


def _get_first_account(user_id: str) -> tuple[str, str]:
    """Return (meta_account_id, access_token) for the user's first active ad account."""
    supabase = get_supabase()
    result = (
        supabase.table("ad_accounts")
        .select("meta_account_id, access_token")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(1)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="No active ad account found. Connect your Meta account first.")
    return result.data["meta_account_id"], result.data["access_token"]


# ── Page Posts ─────────────────────────────────────────────────────────────────

async def _get_user_pages(access_token: str) -> list[dict]:
    """Call /me/accounts to discover the user's Facebook Pages + page access tokens."""
    settings = get_settings()
    base = f"https://graph.facebook.com/{settings.META_API_VERSION}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{base}/me/accounts",
            params={"fields": "id,name,access_token", "access_token": access_token},
        )
        resp.raise_for_status()
        return resp.json().get("data", [])


@router.get("/posts/default")
async def get_default_posts(
    user_id: str = Depends(get_current_user_id),
):
    """Fetch recent posts from the user's first Facebook Page."""
    _, user_token = _get_first_account(user_id)
    try:
        pages = await _get_user_pages(user_token)
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch Facebook Pages")

    if not pages:
        return {"posts": [], "count": 0, "page_id": None, "page_name": None}

    page = pages[0]
    page_id = page["id"]
    page_token = page["access_token"]
    page_name = page.get("name", "")

    try:
        result = await mcp_client.get_page_posts(page_id, page_token)
        result["page_name"] = page_name
        return result
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Account Overview ──────────────────────────────────────────────────────────

@router.get("/{ad_account_id}/overview")
async def get_account_overview(
    ad_account_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """High-level health snapshot: account info, active campaigns, 30d spend/ROAS."""
    token = _get_account_token(user_id, ad_account_id)
    try:
        return await mcp_client.get_account_overview(ad_account_id, token)
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Time-Series Analytics ─────────────────────────────────────────────────────

@router.get("/time-series/default")
async def get_default_time_series(
    date_preset: str = Query("last_30d", pattern="^(last_7d|last_14d|last_30d)$"),
    user_id: str = Depends(get_current_user_id),
):
    """Daily time-series + campaign breakdown using the user's first active ad account."""
    account_id, token = _get_first_account(user_id)
    try:
        return await mcp_client.get_time_series_insights(account_id, token, date_preset)
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{ad_account_id}/time-series")
async def get_time_series(
    ad_account_id: str,
    date_preset: str = Query("last_30d", pattern="^(last_7d|last_14d|last_30d)$"),
    user_id: str = Depends(get_current_user_id),
):
    """Daily time-series + campaign breakdown for a specific ad account."""
    token = _get_account_token(user_id, ad_account_id)
    try:
        return await mcp_client.get_time_series_insights(ad_account_id, token, date_preset)
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/overview/default")
async def get_default_overview(
    user_id: str = Depends(get_current_user_id),
):
    """Account overview using the user's first active ad account."""
    account_id, token = _get_first_account(user_id)
    try:
        result = await mcp_client.get_account_overview(account_id, token)
        result["ad_account_id"] = account_id
        return result
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Campaign List ─────────────────────────────────────────────────────────────

@router.get("/{ad_account_id}/list")
async def list_campaigns(
    ad_account_id: str,
    status_filter: str = Query("all", regex="^(all|active|paused|archived)$"),
    limit: int = Query(25, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
):
    """List campaigns with status, budget, and 7-day performance metrics."""
    token = _get_account_token(user_id, ad_account_id)
    try:
        return await mcp_client.list_campaigns(
            ad_account_id, token, status_filter=status_filter, limit=limit
        )
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Campaign Insights ─────────────────────────────────────────────────────────

@router.get("/{ad_account_id}/insights/{campaign_id}")
async def get_insights(
    ad_account_id: str,
    campaign_id: str,
    date_preset: str = Query("last_7d"),
    user_id: str = Depends(get_current_user_id),
):
    """Detailed performance insights for a specific campaign."""
    token = _get_account_token(user_id, ad_account_id)
    try:
        return await mcp_client.get_campaign_insights(
            campaign_id, token, date_preset=date_preset
        )
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Campaign Detail (full analytics) ──────────────────────────────────────────

@router.get("/{ad_account_id}/detail/{campaign_id}")
async def get_campaign_detail(
    ad_account_id: str,
    campaign_id: str,
    date_preset: str = Query("last_7d", pattern="^(last_7d|last_14d|last_30d)$"),
    user_id: str = Depends(get_current_user_id),
):
    """Full campaign detail: summary metrics, daily time-series, ads, and breakdowns."""
    token = _get_account_token(user_id, ad_account_id)
    try:
        return await mcp_client.get_campaign_detail(
            campaign_id, token, date_preset=date_preset
        )
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Ads within a Campaign ─────────────────────────────────────────────────────

@router.get("/{ad_account_id}/ads/{campaign_id}")
async def list_ads(
    ad_account_id: str,
    campaign_id: str,
    date_preset: str = Query("last_7d"),
    status_filter: str = Query("all", regex="^(all|active|paused)$"),
    user_id: str = Depends(get_current_user_id),
):
    """List all ads in a campaign with individual performance and ROAS verdicts."""
    token = _get_account_token(user_id, ad_account_id)
    try:
        return await mcp_client.list_ads(
            campaign_id, token, date_preset=date_preset, status_filter=status_filter
        )
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Pause Campaign ────────────────────────────────────────────────────────────

class PauseCampaignRequest(BaseModel):
    campaign_id: str


@router.post("/{ad_account_id}/pause")
async def pause_campaign(
    ad_account_id: str,
    body: PauseCampaignRequest,
    user_id: str = Depends(get_current_user_id),
):
    token = _get_account_token(user_id, ad_account_id)
    try:
        result = await mcp_client.pause_campaign(body.campaign_id, token)
        # Log the action
        get_supabase().table("campaign_logs").insert({
            "user_id": user_id,
            "action": "campaign_paused",
            "meta_campaign_id": body.campaign_id,
            "result": result,
            "status": "success",
        }).execute()
        return result
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))
