"""
Lead Forms routes — AI-generate, create, list, and download leads from Meta Lead Gen Forms.

POST   /api/v1/lead-forms/generate-draft       → AI drafts optimal form fields from ad context
POST   /api/v1/lead-forms                       → create a new lead form via Meta + optionally save
GET    /api/v1/lead-forms                       → list saved lead forms for current user
GET    /api/v1/lead-forms/{form_id}/leads/csv   → download leads as CSV
GET    /api/v1/lead-forms/{form_id}/leads       → fetch leads as JSON
"""
import csv
import io
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from ...api.deps import get_current_user_id, get_workspace_id
from ...db.supabase_client import get_supabase
from ...services.mcp_client import MCPClient
from ...services.lead_form_generator import generate_lead_form_draft, generate_lead_form_from_draft

logger = logging.getLogger(__name__)

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
    workspace_id: str = Depends(get_workspace_id),
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
    workspace_id: str = Depends(get_workspace_id),
):
    """Create a lead form on Meta and optionally save for reuse."""
    supabase = get_supabase()

    # Get access token
    account = (
        supabase.table("ad_accounts")
        .select("access_token")
        .eq("workspace_id", workspace_id)
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
            "workspace_id": workspace_id,
            "page_id": payload.page_id,
            "meta_form_id": form_id,
            "form_name": payload.form_name,
            "questions": payload.questions,
        }).execute()

    return {"form_id": form_id, "form_name": payload.form_name, "saved": payload.save_form}


# ── List Saved Forms ─────────────────────────────────────────────────────────


@router.get("")
async def list_lead_forms(
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """
    List lead forms — merges DB-saved forms with live Meta forms.
    Returns both so user can download leads from any form, even ones not saved locally.
    """
    supabase = get_supabase()

    # DB forms
    db_result = (
        supabase.table("lead_forms")
        .select("id, page_id, meta_form_id, form_name, questions, created_at")
        .eq("workspace_id", workspace_id)
        .order("created_at", desc=True)
        .execute()
    )
    db_forms = db_result.data or []
    db_form_ids = {f["meta_form_id"] for f in db_forms if f.get("meta_form_id")}

    # Fetch live forms from Meta (via page_id)
    meta_forms: list[dict] = []
    warning: Optional[str] = None
    try:
        access_token = None
        page_id = None

        # Resolve from workspace
        if workspace_id:
            ws_res = (
                supabase.table("workspaces")
                .select("meta_page_id, meta_access_token")
                .eq("id", workspace_id)
                .limit(1)
                .execute()
            )
            if ws_res.data:
                page_id = ws_res.data[0].get("meta_page_id")
                access_token = ws_res.data[0].get("meta_access_token")

        # Fallback to ad_accounts
        # Also resolve ad_account_id
        ad_account_id = None
        if not access_token:
            aa_res = (
                supabase.table("ad_accounts")
                .select("access_token, facebook_page_id, meta_account_id")
                .eq("workspace_id", workspace_id)
                .limit(1)
                .execute()
            )
            if aa_res.data:
                access_token = aa_res.data[0].get("access_token")
                page_id = page_id or aa_res.data[0].get("facebook_page_id")
                ad_account_id = aa_res.data[0].get("meta_account_id")
        else:
            # Still need ad_account_id even if we got token from workspace
            aa_res2 = (
                supabase.table("ad_accounts")
                .select("meta_account_id")
                .eq("workspace_id", workspace_id)
                .limit(1)
                .execute()
            )
            if aa_res2.data:
                ad_account_id = aa_res2.data[0].get("meta_account_id")

        if not access_token:
            warning = "no_token"
        elif not (page_id or ad_account_id):
            warning = "no_account"
        else:
            mcp = MCPClient()
            result = await mcp.list_leadgen_forms(
                access_token,
                page_id=page_id or "",
                ad_account_id=ad_account_id or "",
            )
            # Parse MCP response
            forms_data = result
            if isinstance(result, dict):
                content = result.get("content", [])
                if content and isinstance(content, list):
                    text = content[0].get("text", "{}")
                    try:
                        forms_data = json.loads(text)
                    except Exception:
                        forms_data = result

            # Check for permission errors in the response
            if isinstance(forms_data, dict) and forms_data.get("error"):
                err = str(forms_data["error"])
                if "permission" in err.lower() or "OAuthException" in err:
                    warning = "missing_permissions"

            for f in forms_data.get("forms", []):
                if f["id"] not in db_form_ids:
                    meta_forms.append({
                        "id": None,
                        "page_id": page_id,
                        "meta_form_id": f["id"],
                        "form_name": f.get("name", "Unnamed Form"),
                        "questions": [],
                        "created_at": f.get("created_time", ""),
                        "leads_count": f.get("leads_count", 0),
                        "status": f.get("status", "ACTIVE"),
                        "campaign_name": f.get("campaign_name", ""),
                        "campaign_status": f.get("campaign_status", ""),
                        "source": "meta",
                    })

            # No blanket assumption — 0 forms is valid when there are simply no lead campaigns
    except Exception as e:
        logger.warning("Failed to fetch Meta lead forms: %s", e)
        if "permission" in str(e).lower():
            warning = "missing_permissions"

    # Tag DB forms
    for f in db_forms:
        f["source"] = "saved"

    return {"data": db_forms + meta_forms, "warning": warning}


# ── Fetch & Download Leads ──────────────────────────────────────────────────


async def _fetch_leads(form_id: str, workspace_id: str) -> list[dict]:
    """Internal helper: fetch leads from Meta via MCP."""
    supabase = get_supabase()
    account = (
        supabase.table("ad_accounts")
        .select("access_token")
        .eq("workspace_id", workspace_id)
        .limit(1)
        .execute()
    )
    if not account.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No ad account connected")
    access_token = account.data[0]["access_token"]

    mcp = MCPClient()
    result = await mcp.get_leadgen_leads(form_id, access_token)

    # Parse MCP response
    leads_data = result
    if isinstance(result, dict):
        content = result.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "{}")
            try:
                leads_data = json.loads(text)
            except Exception:
                leads_data = result

    if leads_data.get("error"):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, leads_data["error"])

    return leads_data.get("leads", [])


@router.get("/{form_id}/leads")
async def get_leads(
    form_id: str,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Fetch leads from a Meta Lead Gen Form as JSON."""
    leads = await _fetch_leads(form_id, workspace_id)
    return {"form_id": form_id, "leads": leads, "total": len(leads)}


@router.get("/{form_id}/leads/csv")
async def download_leads_csv(
    form_id: str,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Download leads from a Meta Lead Gen Form as CSV."""
    leads = await _fetch_leads(form_id, workspace_id)

    if not leads:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No leads found for this form")

    # Collect all unique field names across all leads
    all_keys: list[str] = []
    seen: set[str] = set()
    # Ensure id and created_time come first
    for key in ["id", "created_time"]:
        all_keys.append(key)
        seen.add(key)
    for lead in leads:
        for key in lead:
            if key not in seen:
                all_keys.append(key)
                seen.add(key)

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=all_keys, extrasaction="ignore")
    writer.writeheader()
    for lead in leads:
        writer.writerow(lead)

    output.seek(0)
    filename = f"leads_{form_id}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
