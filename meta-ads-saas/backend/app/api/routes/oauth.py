"""
Meta OAuth 2.0 routes.

GET  /api/v1/oauth/meta/authorize   → build + return Meta consent URL
GET  /api/v1/oauth/meta/callback    → Meta redirects here with ?code=&state=
GET  /api/v1/oauth/meta/accounts    → list connected ad accounts for current user
DELETE /api/v1/oauth/meta/accounts/{account_id}  → disconnect an account
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from ...core.config import get_settings
from ...core.state_token import generate_state, verify_state
from ...services.meta_oauth import build_authorization_url, handle_oauth_callback
from ...services.account_auditor import run_audit
from ...api.deps import get_current_user_id
from ...db.supabase_client import get_supabase

settings = get_settings()
router = APIRouter(prefix="/oauth/meta", tags=["Meta OAuth"])


# ── 1. Authorize ──────────────────────────────────────────────────────────────

@router.get("/authorize")
async def authorize(user_id: str = Depends(get_current_user_id)):
    """
    Returns the Meta consent-screen URL.

    The `state` value is an HMAC-signed token that embeds the user_id —
    no server-side session required, and it's tamper-proof.
    Frontend should redirect the browser to `authorization_url`.
    """
    # Guard: ensure Meta credentials are actually configured
    if not settings.META_APP_ID or settings.META_APP_ID.startswith("<"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meta OAuth is not configured. Set META_APP_ID and META_APP_SECRET in your backend .env file.",
        )
    state = generate_state(user_id)
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
        user_id = verify_state(state)
    except ValueError:
        # Tampered state = possible CSRF attack — hard error, no redirect
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state — request may have been tampered with.",
        )

    # ── Full OAuth pipeline ───────────────────────────────────────────────────
    try:
        await handle_oauth_callback(code=code, user_id=user_id)
        # Auto-trigger account audit in background
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
    if prefs.data and prefs.data[0].get("setup_completed_at"):
        return RedirectResponse(
            url=f"{settings.ALLOWED_ORIGINS[0]}/dashboard/settings?connected=true",
            status_code=status.HTTP_302_FOUND,
        )
    # First-time connect → strategy wizard
    return RedirectResponse(
        url=f"{settings.ALLOWED_ORIGINS[0]}/dashboard/setup?connected=true",
        status_code=status.HTTP_302_FOUND,
    )


# ── 3. List connected ad accounts ─────────────────────────────────────────────

@router.get("/accounts")
async def list_accounts(user_id: str = Depends(get_current_user_id)):
    """
    Returns all ad accounts linked to the authenticated user.
    Access tokens are intentionally excluded from the response.
    """
    supabase = get_supabase()
    result = (
        supabase.table("ad_accounts")
        .select(
            "id, meta_account_id, account_name, currency, timezone, "
            "is_active, token_expires_at, created_at"
        )
        .eq("user_id", user_id)
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


async def _run_audit_safe(user_id: str):
    """Run audit in background, swallow errors so OAuth flow isn't affected."""
    import logging
    try:
        await run_audit(user_id)
    except Exception:
        logging.getLogger(__name__).exception(f"Background audit failed for user {user_id}")
