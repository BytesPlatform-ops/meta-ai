"""
Automated Rules routes — manage kill/scale rules via MCP.

GET    /api/v1/rules/{ad_account_id}         → list rules
POST   /api/v1/rules/kill                     → create kill rule
POST   /api/v1/rules/scale                    → create scale rule
PATCH  /api/v1/rules/{rule_id}/toggle         → toggle rule on/off
DELETE /api/v1/rules/{rule_id}                → delete rule
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ...api.deps import get_current_user_id
from ...db.supabase_client import get_supabase
from ...services.mcp_client import mcp_client, MCPError

router = APIRouter(prefix="/rules", tags=["Automated Rules"])


class KillRuleCreate(BaseModel):
    ad_account_id: str
    campaign_id: str
    spend_threshold: float


class ScaleRuleCreate(BaseModel):
    ad_account_id: str
    campaign_id: str
    roas_threshold: float
    scale_percent: float


async def _get_access_token(user_id: str, ad_account_id: str | None = None) -> tuple[str, str]:
    """Resolve access token and meta_account_id for the user."""
    supabase = get_supabase()
    query = supabase.table("ad_accounts").select("*").eq("user_id", user_id).eq("is_active", True)
    if ad_account_id:
        query = query.eq("meta_account_id", ad_account_id)
    result = query.limit(1).execute()
    if not result.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active ad account found")
    account = result.data[0]
    return account["access_token"], account["meta_account_id"]


@router.get("/{ad_account_id}")
async def list_rules(
    ad_account_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """List automated rules for an ad account."""
    access_token, meta_id = await _get_access_token(user_id, ad_account_id)
    try:
        result = await mcp_client.call_tool(
            "list_automated_rules",
            {"ad_account_id": meta_id},
            access_token,
        )
        return result
    except MCPError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))


@router.post("/kill", status_code=201)
async def create_kill_rule(
    body: KillRuleCreate,
    user_id: str = Depends(get_current_user_id),
):
    """Create a kill rule that pauses a campaign when spend exceeds threshold."""
    access_token, meta_id = await _get_access_token(user_id, body.ad_account_id)
    try:
        result = await mcp_client.call_tool(
            "create_kill_rule",
            {
                "ad_account_id": meta_id,
                "campaign_id": body.campaign_id,
                "spend_threshold": body.spend_threshold,
            },
            access_token,
        )
        return result
    except MCPError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))


@router.post("/scale", status_code=201)
async def create_scale_rule(
    body: ScaleRuleCreate,
    user_id: str = Depends(get_current_user_id),
):
    """Create a scale rule that increases budget when ROAS exceeds threshold."""
    access_token, meta_id = await _get_access_token(user_id, body.ad_account_id)
    try:
        result = await mcp_client.call_tool(
            "create_scale_rule",
            {
                "ad_account_id": meta_id,
                "campaign_id": body.campaign_id,
                "roas_threshold": body.roas_threshold,
                "scale_percent": body.scale_percent,
            },
            access_token,
        )
        return result
    except MCPError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))


@router.patch("/{rule_id}/toggle")
async def toggle_rule(
    rule_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Toggle an automated rule on/off."""
    access_token, _ = await _get_access_token(user_id)
    try:
        result = await mcp_client.call_tool(
            "toggle_automated_rule",
            {"rule_id": rule_id},
            access_token,
        )
        return result
    except MCPError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Delete an automated rule."""
    access_token, _ = await _get_access_token(user_id)
    try:
        await mcp_client.call_tool(
            "delete_automated_rule",
            {"rule_id": rule_id},
            access_token,
        )
    except MCPError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
