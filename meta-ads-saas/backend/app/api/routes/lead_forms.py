"""
Lead Forms routes — AI-generate, create, and list Meta Lead Gen Forms.

POST   /api/v1/lead-forms/generate-draft  → AI drafts optimal form fields from ad context
POST   /api/v1/lead-forms                 → create a new lead form via Meta + optionally save
GET    /api/v1/lead-forms                 → list saved lead forms for current user
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from ...api.deps import get_current_user_id
from ...db.supabase_client import get_supabase
from ...services.mcp_client import MCPClient
from ...services.lead_form_generator import generate_lead_form_draft, generate_lead_form_from_draft

router = APIRouter(prefix="/lead-forms", tags=["Lead Forms"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class GenerateLeadFormDraftPayload(BaseModel):
    """Context for AI to generate optimal lead form fields."""
    draft_id: Optional[str] = None          # If provided, pulls context from the draft
    product_name: Optional[str] = None
    product_description: Optional[str] = None
    ad_text: Optional[str] = None
    target_country: Optional[str] = None


class CreateLeadFormPayload(BaseModel):
    page_id: str
    form_name: str
    questions: list = []
    save_form: bool = True


# ── AI Lead Form Drafter ─────────────────────────────────────────────────────


@router.post("/generate-draft")
async def generate_form_draft(
    payload: GenerateLeadFormDraftPayload,
    user_id: str = Depends(get_current_user_id),
):
    """
    AI-generate an optimal lead form schema based on ad/product context.

    If draft_id is provided, the AI pulls all context from that draft and its
    linked product automatically. Otherwise, pass ad_text / product_name directly.

    Returns:
        {"form_name": str, "questions": [...], "reasoning": str}
    """
    if payload.draft_id:
        result = await generate_lead_form_from_draft(payload.draft_id, user_id)
    else:
        # Fetch business description for extra context
        biz_desc = ""
        supabase = get_supabase()
        pref_res = (
            supabase.table("user_preferences")
            .select("business_description")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if pref_res.data:
            biz_desc = pref_res.data[0].get("business_description", "")

        result = await generate_lead_form_draft(
            product_name=payload.product_name or "",
            product_description=payload.product_description or "",
            ad_text=payload.ad_text or "",
            target_country=payload.target_country or "",
            business_description=biz_desc,
        )

    return result


# ── Create Form on Meta ──────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_lead_form(
    payload: CreateLeadFormPayload,
    user_id: str = Depends(get_current_user_id),
):
    """Create a lead form on Meta and optionally save for reuse."""
    supabase = get_supabase()

    # Get access token
    account = (
        supabase.table("ad_accounts")
        .select("access_token")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not account.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No ad account connected")
    access_token = account.data[0]["access_token"]

    import json
    mcp = MCPClient()
    result = await mcp.call_tool(
        "create_lead_form",
        {
            "page_id": payload.page_id,
            "form_name": payload.form_name,
            "questions_json": json.dumps(payload.questions),
        },
        access_token,
    )

    # Parse MCP response
    mcp_data = {}
    if isinstance(result, dict):
        content = result.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "")
            try:
                mcp_data = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                mcp_data = {"raw": text}
        else:
            mcp_data = result

    if mcp_data.get("error"):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, mcp_data["error"])

    form_id = mcp_data.get("form_id")
    if not form_id:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "No form_id returned from Meta")

    # Save to DB if requested
    if payload.save_form:
        supabase.table("lead_forms").insert({
            "user_id": user_id,
            "page_id": payload.page_id,
            "meta_form_id": form_id,
            "form_name": payload.form_name,
            "questions": payload.questions,
        }).execute()

    return {"form_id": form_id, "form_name": payload.form_name, "saved": payload.save_form}


# ── List Saved Forms ─────────────────────────────────────────────────────────


@router.get("")
async def list_lead_forms(user_id: str = Depends(get_current_user_id)):
    """List saved lead forms for the current user."""
    supabase = get_supabase()
    result = (
        supabase.table("lead_forms")
        .select("id, page_id, meta_form_id, form_name, questions, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data
