"""
Campaign management routes — proxies requests through the MCP client
to the Meta Marketing API MCP server.
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from ...api.deps import get_current_user_id, get_workspace_id
from ...services.mcp_client import mcp_client, MCPError
from ...db.supabase_client import get_supabase
from ...core.config import get_settings

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


def _get_account_token(workspace_id: str, ad_account_id: str) -> str:
    """Fetch the access token for a given ad account, scoped to the workspace."""
    supabase = get_supabase()
    result = (
        supabase.table("ad_accounts")
        .select("access_token")
        .eq("workspace_id", workspace_id)
        .eq("meta_account_id", ad_account_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Ad account not found")
    return result.data["access_token"]


def _get_first_account(workspace_id: str) -> tuple[str, str]:
    """Return (meta_account_id, access_token) for the workspace's first active ad account."""
    supabase = get_supabase()
    result = (
        supabase.table("ad_accounts")
        .select("meta_account_id, access_token")
        .eq("workspace_id", workspace_id)
        .eq("is_active", True)
        .limit(1)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="No active ad account found. Connect your Meta account first.")
    return result.data["meta_account_id"], result.data["access_token"]


def _get_workspace_page_id(workspace_id: str) -> str | None:
    """Return the workspace's meta_page_id (or None if not set)."""
    supabase = get_supabase()
    result = (
        supabase.table("workspaces")
        .select("meta_page_id")
        .eq("id", workspace_id)
        .limit(1)
        .maybe_single()
        .execute()
    )
    return result.data.get("meta_page_id") if result.data else None


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
    workspace_id: str = Depends(get_workspace_id),
):
    """Fetch recent posts from the workspace's Facebook Page."""
    _, user_token = _get_first_account(workspace_id)
    ws_page_id = _get_workspace_page_id(workspace_id)

    try:
        pages = await _get_user_pages(user_token)
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch Facebook Pages")

    if not pages:
        return {"posts": [], "count": 0, "page_id": None, "page_name": None}

    # Use workspace's page_id if set, otherwise fall back to first page
    page = None
    if ws_page_id:
        page = next((p for p in pages if p["id"] == ws_page_id), None)
    if not page:
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
    workspace_id: str = Depends(get_workspace_id),
):
    """High-level health snapshot: account info, active campaigns, 30d spend/ROAS."""
    token = _get_account_token(workspace_id, ad_account_id)
    try:
        return await mcp_client.get_account_overview(ad_account_id, token)
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Time-Series Analytics ─────────────────────────────────────────────────────

@router.get("/time-series/default")
async def get_default_time_series(
    date_preset: str = Query("maximum"),
    since: str | None = Query(None),
    until: str | None = Query(None),
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Daily time-series + campaign breakdown using the workspace's first active ad account."""
    account_id, token = _get_first_account(workspace_id)
    try:
        return await mcp_client.get_time_series_insights(
            account_id, token, date_preset, since=since, until=until,
        )
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{ad_account_id}/time-series")
async def get_time_series(
    ad_account_id: str,
    date_preset: str = Query("maximum"),
    since: str | None = Query(None),
    until: str | None = Query(None),
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Daily time-series + campaign breakdown for a specific ad account."""
    token = _get_account_token(workspace_id, ad_account_id)
    try:
        return await mcp_client.get_time_series_insights(
            ad_account_id, token, date_preset, since=since, until=until,
        )
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/overview/default")
async def get_default_overview(
    since: str | None = Query(None),
    until: str | None = Query(None),
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Account overview using the workspace's first active ad account."""
    account_id, token = _get_first_account(workspace_id)
    try:
        result = await mcp_client.get_account_overview(account_id, token, since=since, until=until)
        result["ad_account_id"] = account_id
        return result
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/dashboard/metrics")
async def get_dashboard_metrics(
    date_preset: str = Query("maximum"),
    since: str | None = Query(None),
    until: str | None = Query(None),
    status_filter: str = Query("active"),
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """
    Dashboard metrics returning two datasets:
      - total_account_metrics: overall ad account spend
      - workspace_page_metrics: filtered to the workspace's meta_page_id
    """
    account_id, token = _get_first_account(workspace_id)
    page_id = _get_workspace_page_id(workspace_id)

    try:
        result = await mcp_client.get_dashboard_metrics(
            account_id, token, page_id=page_id, date_preset=date_preset, since=since, until=until,
            status_filter=status_filter,
        )
        result["ad_account_id"] = account_id
        result["page_id"] = page_id
        return result
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Campaign List ─────────────────────────────────────────────────────────────

@router.get("/{ad_account_id}/list")
async def list_campaigns(
    ad_account_id: str,
    status_filter: str = Query("all", regex="^(all|active|paused|archived)$"),
    limit: int = Query(25, ge=1, le=100),
    since: str | None = Query(None),
    until: str | None = Query(None),
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """List campaigns with status, budget, and 30-day performance metrics.
    Automatically filters to workspace's page if one is linked."""
    token = _get_account_token(workspace_id, ad_account_id)
    page_id = _get_workspace_page_id(workspace_id)
    # Compute baselines for dynamic verdicts
    from ...services.baselines import calculate_account_baselines
    try:
        bl = await calculate_account_baselines(ad_account_id.replace("act_", ""), token, user_id=user_id)
        bl_dict = bl.to_dict()
    except Exception:
        bl_dict = None
    try:
        return await mcp_client.list_campaigns(
            ad_account_id, token, status_filter=status_filter, limit=limit,
            since=since, until=until, page_id=page_id, baselines=bl_dict,
        )
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Campaign Insights ─────────────────────────────────────────────────────────

@router.get("/{ad_account_id}/insights/{campaign_id}")
async def get_insights(
    ad_account_id: str,
    campaign_id: str,
    date_preset: str = Query("maximum"),
    since: str | None = Query(None),
    until: str | None = Query(None),
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Detailed performance insights for a specific campaign."""
    token = _get_account_token(workspace_id, ad_account_id)
    try:
        return await mcp_client.get_campaign_insights(
            campaign_id, token, date_preset=date_preset, since=since, until=until,
        )
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Campaign Detail (full analytics) ──────────────────────────────────────────

@router.get("/{ad_account_id}/detail/{campaign_id}")
async def get_campaign_detail(
    ad_account_id: str,
    campaign_id: str,
    date_preset: str = Query("maximum"),
    since: str | None = Query(None),
    until: str | None = Query(None),
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Full campaign detail: summary metrics, daily time-series, ads, and breakdowns."""
    token = _get_account_token(workspace_id, ad_account_id)
    try:
        return await mcp_client.get_campaign_detail(
            campaign_id, token, date_preset=date_preset, since=since, until=until,
        )
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── Ads within a Campaign ─────────────────────────────────────────────────────

@router.get("/{ad_account_id}/ads/{campaign_id}")
async def list_ads(
    ad_account_id: str,
    campaign_id: str,
    date_preset: str = Query("maximum"),
    status_filter: str = Query("all", regex="^(all|active|paused)$"),
    since: str | None = Query(None),
    until: str | None = Query(None),
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """List all ads in a campaign with individual performance and verdicts."""
    token = _get_account_token(workspace_id, ad_account_id)
    from ...services.baselines import calculate_account_baselines
    try:
        bl = await calculate_account_baselines(ad_account_id.replace("act_", ""), token, user_id=user_id)
        bl_dict = bl.to_dict()
    except Exception:
        bl_dict = None
    try:
        return await mcp_client.list_ads(
            campaign_id, token, date_preset=date_preset, status_filter=status_filter,
            since=since, until=until, baselines=bl_dict,
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
    workspace_id: str = Depends(get_workspace_id),
):
    token = _get_account_token(workspace_id, ad_account_id)
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
