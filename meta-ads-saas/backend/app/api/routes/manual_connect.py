"""
Manual Meta API connection — alternative to OAuth flow.

POST /api/v1/auth/manual-connect
  Accepts access_token + ad_account_id, validates against Graph API,
  fetches account details, and upserts into ad_accounts table.
"""
import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ...api.deps import get_current_user_id
from ...core.config import get_settings
from ...services.meta_oauth import fetch_ad_accounts, upsert_ad_accounts
from ...services.account_auditor import run_audit

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/auth", tags=["Manual Connect"])

META_BASE = f"https://graph.facebook.com/{settings.META_API_VERSION}"


class ManualConnectRequest(BaseModel):
    access_token: str = Field(..., min_length=10)
    ad_account_id: str = Field(..., min_length=1)


@router.post("/manual-connect")
async def manual_connect(
    body: ManualConnectRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
):
    """
    Validate a manually-provided Meta access token, then save the
    specified ad account exactly like the OAuth flow does.
    """
    # Normalize: add act_ prefix if missing
    if not body.ad_account_id.startswith("act_"):
        body.ad_account_id = f"act_{body.ad_account_id}"
    # 1. Validate token against Graph API
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{META_BASE}/me",
            params={"access_token": body.access_token},
        )

    if resp.is_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Meta Access Token. Please check and try again.",
        )

    # 2. Fetch all ad accounts the token has access to
    try:
        all_accounts = await fetch_ad_accounts(body.access_token)
    except Exception:
        logger.exception("Failed to fetch ad accounts with manual token")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token is valid but failed to fetch ad accounts. Ensure the token has ads_read permission.",
        )

    # 3. Find the requested ad account
    matched = [a for a in all_accounts if a["id"] == body.ad_account_id]
    if not matched:
        available = [a["id"] for a in all_accounts[:5]]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ad account {body.ad_account_id} not found for this token. "
                   f"Available accounts: {', '.join(available) or 'none'}",
        )

    # 4. Upsert — manual tokens don't have a known expiry, assume 60 days
    expires_at = datetime.now(tz=timezone.utc) + timedelta(days=60)
    saved = upsert_ad_accounts(
        user_id=user_id,
        long_token=body.access_token,
        expires_at=expires_at,
        ad_accounts=matched,
    )

    # 5. Background audit
    background_tasks.add_task(_run_audit_safe, user_id)

    return {
        "message": "Ad account connected successfully.",
        "accounts": [
            {
                "meta_account_id": a.get("meta_account_id"),
                "account_name": a.get("account_name"),
            }
            for a in saved
        ],
    }


async def _run_audit_safe(user_id: str):
    try:
        await run_audit(user_id)
    except Exception:
        logger.exception(f"Background audit failed for user {user_id}")
