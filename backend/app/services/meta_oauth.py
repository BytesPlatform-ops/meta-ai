"""
Meta (Facebook) OAuth 2.0 service.

Flow:
  1. /authorize  → build_authorization_url()  → user sent to Meta consent screen
  2. Meta redirects to /callback?code=...&state=...
  3. exchange_code_for_token()      → short-lived token  (~1 hour)
  4. exchange_for_long_lived_token() → long-lived token  (~60 days)
  5. fetch_ad_accounts()            → list user's ad accounts from Graph API
  6. upsert_ad_accounts()           → persist tokens + accounts to Supabase

Security:
  - META_APP_SECRET is read exclusively from environment variables (never hardcoded).
  - The OAuth `state` param is a signed HMAC token (see core/state_token.py).
  - Long-lived token expiry is stored as an absolute timestamp in `token_expires_at`.
"""
from __future__ import annotations

import httpx
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from ..core.config import get_settings
from ..db.supabase_client import get_supabase

settings = get_settings()

META_BASE = f"https://graph.facebook.com/{settings.META_API_VERSION}"
OAUTH_AUTHORIZE_URL = "https://www.facebook.com/dialog/oauth"
OAUTH_SCOPES = "ads_management,ads_read,business_management,pages_read_engagement,pages_manage_posts"


# ── 1. Build authorization URL ────────────────────────────────────────────────

def build_authorization_url(state: str) -> str:
    """
    Returns the Facebook consent-screen URL.
    `state` must be a signed HMAC token (see core/state_token.py).
    """
    params = {
        "client_id": settings.META_APP_ID,
        "redirect_uri": settings.META_REDIRECT_URI,
        "scope": OAUTH_SCOPES,
        "response_type": "code",
        "state": state,
    }
    return f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


# ── 2. Exchange code → short-lived token ─────────────────────────────────────

async def exchange_code_for_token(code: str) -> str:
    """
    Exchange the authorization code for a SHORT-LIVED user access token.
    Returns the access_token string.
    Raises httpx.HTTPStatusError with Meta's error body on failure.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{META_BASE}/oauth/access_token",
            params={
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,   # from env only
                "redirect_uri": settings.META_REDIRECT_URI,
                "code": code,
            },
        )
        _raise_for_meta_error(resp)
        return resp.json()["access_token"]


# ── 3. Exchange short-lived → long-lived token (~60 days) ────────────────────

async def exchange_for_long_lived_token(short_token: str) -> tuple[str, datetime]:
    """
    Exchange a short-lived token for a LONG-LIVED token.
    Returns (access_token, expires_at) where expires_at is timezone-aware UTC.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{META_BASE}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,   # from env only
                "fb_exchange_token": short_token,
            },
        )
        _raise_for_meta_error(resp)
        data = resp.json()

    token = data["access_token"]
    # expires_in is in seconds; default to 59 days if Meta omits it
    expires_in: int = data.get("expires_in", 59 * 24 * 3600)
    expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=expires_in)
    return token, expires_at


# ── 4. Fetch ad accounts ──────────────────────────────────────────────────────

async def fetch_ad_accounts(access_token: str) -> list[dict]:
    """
    Return the ad accounts the token has access to.
    Each item: { id, name, currency, timezone_name }
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{META_BASE}/me/adaccounts",
            params={
                "fields": "id,name,currency,timezone_name,account_status",
                "access_token": access_token,
            },
        )
        _raise_for_meta_error(resp)
        return resp.json().get("data", [])


# ── 5. Upsert into Supabase ───────────────────────────────────────────────────

def upsert_ad_accounts(
    user_id: str,
    long_token: str,
    expires_at: datetime,
    ad_accounts: list[dict],
) -> list[dict]:
    """
    Save (or update) each ad account record in the `ad_accounts` table.
    Returns the upserted rows.
    """
    import httpx as _httpx
    from ..core.config import get_settings as _get_settings
    _settings = _get_settings()
    base = _settings.SUPABASE_URL.rstrip("/")
    key = _settings.SUPABASE_SERVICE_ROLE_KEY
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation,resolution=merge-duplicates",
    }

    saved = []
    for account in ad_accounts:
        row = {
            "user_id": user_id,
            "meta_account_id": account["id"],
            "account_name": account.get("name"),
            "access_token": long_token,
            "token_expires_at": expires_at.isoformat(),
            "currency": account.get("currency", "USD"),
            "timezone": account.get("timezone_name", "UTC"),
            "is_active": True,
        }
        resp = _httpx.post(
            f"{base}/rest/v1/ad_accounts?on_conflict=user_id,meta_account_id",
            headers=headers,
            json=row,
            timeout=10,
        )
        if resp.status_code in (200, 201):
            saved.extend(resp.json())
        else:
            import logging
            logging.getLogger(__name__).error(
                f"Failed to upsert ad account: {resp.status_code} {resp.text}"
            )
    return saved


# ── 6. Full pipeline ──────────────────────────────────────────────────────────

async def handle_oauth_callback(code: str, user_id: str) -> list[dict]:
    """
    Orchestrates the full OAuth callback:
      code → short token → long token → ad accounts → Supabase upsert
    Returns the list of saved ad account rows.
    """
    short_token = await exchange_code_for_token(code)
    long_token, expires_at = await exchange_for_long_lived_token(short_token)
    ad_accounts = await fetch_ad_accounts(long_token)
    return upsert_ad_accounts(user_id, long_token, expires_at, ad_accounts)


# ── Helper ────────────────────────────────────────────────────────────────────

def _raise_for_meta_error(resp: httpx.Response) -> None:
    """
    Raise a descriptive RuntimeError when Meta's Graph API returns an error,
    instead of a raw httpx.HTTPStatusError with a cryptic message.
    """
    if resp.is_error:
        try:
            body = resp.json()
            err = body.get("error", {})
            msg = err.get("message") or resp.text
            code = err.get("code", resp.status_code)
            raise RuntimeError(f"Meta API error {code}: {msg}")
        except (ValueError, KeyError):
            resp.raise_for_status()
