"""
Meta OAuth 2.0 routes.

GET  /api/v1/oauth/meta/authorize   → build + return Meta consent URL
GET  /api/v1/oauth/meta/callback    → Meta redirects here with ?code=&state=
GET  /api/v1/oauth/meta/accounts    → list connected ad accounts for current user
DELETE /api/v1/oauth/meta/accounts/{account_id}  → disconnect an account
"""
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

from ...core.config import get_settings
from ...core.state_token import generate_state, verify_state
from ...services.meta_oauth import build_authorization_url, handle_oauth_callback
from ...services.account_auditor import run_audit
from ...api.deps import get_current_user_id, get_workspace_id
from ...db.supabase_client import get_supabase

settings = get_settings()
router = APIRouter(prefix="/oauth/meta", tags=["Meta OAuth"])


# ── 1. Authorize ──────────────────────────────────────────────────────────────

@router.get("/authorize")
async def authorize(
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """
    Returns the Meta consent-screen URL.

    The `state` value is an HMAC-signed token that embeds user_id + workspace_id —
    no server-side session required, and it's tamper-proof.
    Frontend should redirect the browser to `authorization_url`.
    """
    # Guard: ensure Meta credentials are actually configured
    if not settings.META_APP_ID or settings.META_APP_ID.startswith("<"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meta OAuth is not configured. Set META_APP_ID and META_APP_SECRET in your backend .env file.",
        )
    state = generate_state(user_id, workspace_id)
    url = build_authorization_url(state=state)
    return {"authorization_url": url, "state": state}


# ── 2. Callback ───────────────────────────────────────────────────────────────

@router.get("/callback")
async def callback(
    background_tasks: BackgroundTasks,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    """
    Meta redirects here after user grants/denies permission.

    Security checklist:
    ✓ `state` is verified against HMAC signature before trusting user_id
    ✓ user_id is extracted from the verified state (not from query params)
    ✓ META_APP_SECRET is never exposed — used only inside meta_oauth service
    ✓ On error, redirect to frontend with error param (never expose raw Meta errors)
    """
    # User denied access on Meta's side
    if error:
        return RedirectResponse(
            url=f"{settings.ALLOWED_ORIGINS[0]}/dashboard/settings"
                f"?meta_error={error_description or error}",
            status_code=status.HTTP_302_FOUND,
        )

    if not code or not state:
        return RedirectResponse(
            url=f"{settings.ALLOWED_ORIGINS[0]}/dashboard/settings?meta_error=missing_params",
            status_code=status.HTTP_302_FOUND,
        )

    # ── CSRF verification ─────────────────────────────────────────────────────
    try:
        user_id, workspace_id = verify_state(state)
    except ValueError:
        # Tampered state = possible CSRF attack — hard error, no redirect
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state — request may have been tampered with.",
        )

    # ── Full OAuth pipeline ───────────────────────────────────────────────────
    try:
        await handle_oauth_callback(code=code, user_id=user_id, workspace_id=workspace_id)
        # Token is saved to workspace by handle_oauth_callback
        # Account linking happens via the account picker UI
        background_tasks.add_task(_run_audit_safe, user_id)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("OAuth callback failed")
        return RedirectResponse(
            url=f"{settings.ALLOWED_ORIGINS[0]}/dashboard/settings?meta_error=token_exchange_failed",
            status_code=status.HTTP_302_FOUND,
        )

    # Check if user has completed strategy setup
    sb = get_supabase()
    prefs = (
        sb.table("user_preferences")
        .select("setup_completed_at")
        .eq("user_id", user_id)
        .execute()
    )
    # Always redirect to settings with account picker
    return RedirectResponse(
        url=f"{settings.ALLOWED_ORIGINS[0]}/dashboard/settings?connected=true&choose_accounts=true",
        status_code=status.HTTP_302_FOUND,
    )


# ── 3. List connected ad accounts ─────────────────────────────────────────────

@router.get("/accounts")
async def list_accounts(
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """
    Returns all ad accounts linked to the current workspace.
    Access tokens are intentionally excluded from the response.
    """
    supabase = get_supabase()
    result = (
        supabase.table("ad_accounts")
        .select(
            "id, meta_account_id, account_name, currency, timezone, "
            "is_active, token_expires_at, created_at"
        )
        .eq("workspace_id", workspace_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data


# ── 4. Disconnect an ad account ───────────────────────────────────────────────

@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_account(
    account_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    Soft-deletes (deactivates) a connected ad account.
    The token is cleared so it can't be used accidentally.
    """
    supabase = get_supabase()
    result = (
        supabase.table("ad_accounts")
        .update({"is_active": False, "access_token": ""})
        .eq("id", account_id)
        .eq("user_id", user_id)   # ownership check — users can only touch their own rows
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")


# ── 5. Available accounts (from Meta, not yet linked) ─────────────────────────

@router.get("/available-accounts")
async def available_accounts(
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """
    Fetch all ad accounts from Meta using the workspace's stored token.
    Returns both the full list and which are already linked to this workspace.
    """
    from ...services.meta_oauth import fetch_ad_accounts
    supabase = get_supabase()

    # Get workspace token
    ws = supabase.table("workspaces").select("meta_access_token").eq("id", workspace_id).limit(1).execute()
    if not ws.data or not ws.data[0].get("meta_access_token"):
        raise HTTPException(status_code=400, detail="No Meta token found for this workspace. Connect Meta first.")

    token = ws.data[0]["meta_access_token"]

    try:
        meta_accounts = await fetch_ad_accounts(token)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch accounts from Meta: {e}")

    # Check which are already linked to this workspace. We do NOT filter by
    # is_active here — a row that exists but is currently inactive (e.g. flagged
    # after a token expiry) still counts as "linked" so the modal pre-checks
    # it. Re-selecting + clicking Link runs the upsert+reactivation path,
    # which flips is_active back on with the fresh token.
    linked = supabase.table("ad_accounts").select("meta_account_id").eq("workspace_id", workspace_id).execute()
    linked_ids = {r["meta_account_id"] for r in (linked.data or [])}

    return {
        "accounts": [
            {
                "id": a["id"],
                "name": a.get("name", "Unnamed"),
                "currency": a.get("currency", "USD"),
                "timezone_name": a.get("timezone_name", "UTC"),
                "already_linked": a["id"] in linked_ids,
            }
            for a in meta_accounts
        ]
    }


# ── 6. Link selected accounts to workspace ────────────────────────────────────

from pydantic import BaseModel as _BaseModel


class LinkAccountsRequest(_BaseModel):
    account_ids: list[str]


@router.post("/link-accounts")
async def link_accounts(
    body: LinkAccountsRequest,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """
    Link selected Meta ad accounts to the current workspace.
    Creates new ad_account rows without affecting other workspaces.
    """
    from datetime import datetime, timedelta, timezone
    from ...services.meta_oauth import fetch_ad_accounts, link_accounts_to_workspace
    supabase = get_supabase()

    # Get workspace token
    ws = supabase.table("workspaces").select("meta_access_token").eq("id", workspace_id).limit(1).execute()
    if not ws.data or not ws.data[0].get("meta_access_token"):
        raise HTTPException(status_code=400, detail="No Meta token for this workspace.")

    token = ws.data[0]["meta_access_token"]

    # Fetch all accounts from Meta to get full details
    try:
        all_accounts = await fetch_ad_accounts(token)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch from Meta: {e}")

    # Filter to only the selected ones
    selected = [a for a in all_accounts if a["id"] in body.account_ids]
    if not selected:
        raise HTTPException(status_code=400, detail="None of the selected accounts were found on Meta.")

    # Default expiry: 60 days from now (token was already long-lived)
    expires_at = datetime.now(tz=timezone.utc) + timedelta(days=60)

    saved = link_accounts_to_workspace(
        user_id=user_id,
        workspace_id=workspace_id,
        long_token=token,
        expires_at=expires_at,
        ad_accounts=selected,
    )

    # Also update workspace with the first account's Meta ID + page/IG identities
    if saved:
        try:
            first = saved[0]
            ws_update: dict = {
                "meta_ad_account_id": first.get("meta_account_id"),
            }
            # Fetch social identities (page + IG) and sync to workspace
            try:
                from ...services.mcp_client import mcp_client
                identities = await mcp_client.call_tool("fetch_social_identities", {"access_token": token})
                pages = identities.get("content", [{}])
                if pages:
                    import json as _json
                    text = pages[0].get("text", "{}") if isinstance(pages[0], dict) else str(pages[0])
                    parsed = _json.loads(text) if isinstance(text, str) else text
                    page_list = parsed.get("pages", []) if isinstance(parsed, dict) else []
                    if page_list:
                        p = page_list[0]
                        ws_update["meta_page_id"] = p.get("page_id")
                        ws_update["meta_ig_actor_id"] = p.get("instagram_actor_id")
                        # Also update ad_account rows with page/IG IDs
                        for s in saved:
                            supabase.table("ad_accounts").update({
                                "facebook_page_id": p.get("page_id"),
                                "instagram_actor_id": p.get("instagram_actor_id"),
                            }).eq("id", s.get("id")).execute()
            except Exception as e:
                logger.warning("Failed to fetch social identities during link: %s", e)
            supabase.table("workspaces").update(ws_update).eq("id", workspace_id).execute()
        except Exception:
            pass

    return {
        "linked": len(saved),
        "accounts": [
            {"meta_account_id": a.get("meta_account_id"), "account_name": a.get("account_name")}
            for a in saved
        ],
    }


async def _run_audit_safe(user_id: str):
    """Run audit in background, swallow errors so OAuth flow isn't affected."""
    import logging
    try:
        await run_audit(user_id)
    except Exception:
        logging.getLogger(__name__).exception(f"Background audit failed for user {user_id}")
