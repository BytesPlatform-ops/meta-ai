"""
WABA pre-publish validator.

When the publish path is about to stage a Click-to-WhatsApp ad, this module
checks Meta's view of the world: is the draft's ``whatsapp_number`` actually
registered as a WABA phone number AND assigned to the chosen Facebook Page?

Without this check the system flies blind — Meta accepts our publish, then
silently routes the ad to whatever number IT thinks is the Primary WABA on
the Page (or fails ad-set creation with an opaque error). The user sees a
mismatch they can't debug.

Required OAuth scope: ``whatsapp_business_management``. Without it Meta
returns HTTP 403 #200 on every WABA edge — the validator falls back to a
permissive "could not check" verdict so we don't block legitimate publishes
on a missing scope (the user will just have to re-authenticate to enable
strict validation).

Public API
----------
    await validate_waba_assignment(
        page_id=..., page_access_token=..., user_access_token=...,
        required_phone_e164=...,
    ) -> WABACheck
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..core.config import get_settings

logger = logging.getLogger(__name__)


# ── Result type ──────────────────────────────────────────────────────────────


@dataclass
class WABACheck:
    """The verdict on whether a phone number is a valid WABA on a Page.

    ``valid`` interpretation:
      - True  → number is recognised by Meta as a WABA assigned to this Page
      - False → number is NOT recognised; publish should be blocked
      - None  → could not check (missing scope / API error). Caller may
                choose to allow the publish but should log a warning.

    ``available_numbers`` lists every E.164 number Meta says is eligible
    for ads on this Page — useful for the error message so the user knows
    which numbers ARE valid.
    """

    valid: bool | None
    available_numbers: list[str] = field(default_factory=list)
    error_reason: str | None = None
    raw_responses: dict[str, Any] = field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────────


def normalise_e164(num: str | None) -> str:
    """Strip everything except digits and a leading +. Meta returns numbers
    in mixed formats (`+31 970 102 779 11`, `+3197010277911`, etc.) — we
    compare on the digits-only canonical form."""
    if not num:
        return ""
    s = num.strip()
    s = re.sub(r"[^\d+]", "", s)
    if not s.startswith("+") and s:
        s = "+" + s
    return s


def _digits(num: str | None) -> str:
    """Digits-only key for comparison (drops the +)."""
    return re.sub(r"[^\d]", "", (num or ""))


# ── Public API ───────────────────────────────────────────────────────────────


async def validate_waba_assignment(
    *,
    page_id: str,
    page_access_token: str,
    user_access_token: str | None = None,
    required_phone_e164: str,
) -> WABACheck:
    """Verify Meta recognises ``required_phone_e164`` as a WABA phone number
    assigned to the given Facebook Page.

    Strategy: probe several Graph edges, union the discovered phone numbers,
    then compare on E.164-digits. Accepts the publish if ANY discovery path
    confirms the number; rejects only if ALL probes succeed and none returned
    the number; returns ``None`` (could-not-check) if every probe failed.
    """
    if not page_id or not required_phone_e164:
        return WABACheck(valid=None, error_reason="missing page_id or phone")

    settings = get_settings()
    api_version = getattr(settings, "META_API_VERSION", "v22.0")
    target_digits = _digits(required_phone_e164)

    discovered: dict[str, str] = {}  # digits → display E.164
    raw: dict[str, Any] = {}
    soft_fail = False  # True if some probe got 403 (missing scope)
    hard_fail = True  # flips to False on first probe that returned 200

    async with httpx.AsyncClient(timeout=15.0) as client:

        # Probe 1: Page-level edge — newer Meta pages expose this.
        url = f"https://graph.facebook.com/{api_version}/{page_id}"
        params = {
            "fields": "connected_whatsapp_business_account{id,phone_numbers{id,display_phone_number,verified_name,status,code_verification_status}}",
            "access_token": page_access_token,
        }
        try:
            r = await client.get(url, params=params)
            raw["page.connected_whatsapp_business_account"] = {
                "status": r.status_code, "body": _safe_json(r),
            }
            if r.status_code == 200:
                hard_fail = False
                cwba = (r.json() or {}).get("connected_whatsapp_business_account") or {}
                for pn in (cwba.get("phone_numbers") or {}).get("data", []) if isinstance(cwba.get("phone_numbers"), dict) else (cwba.get("phone_numbers") or []):
                    if isinstance(pn, dict) and pn.get("display_phone_number"):
                        d = _digits(pn["display_phone_number"])
                        if d:
                            discovered[d] = pn["display_phone_number"]
            elif r.status_code == 403:
                soft_fail = True
        except Exception as e:
            raw["page.connected_whatsapp_business_account_error"] = str(e)

        # Probe 2: Page-level whatsapp_business_account (singular field).
        params2 = {
            "fields": "whatsapp_business_account{id,phone_numbers{display_phone_number,status}}",
            "access_token": page_access_token,
        }
        try:
            r = await client.get(url, params=params2)
            raw["page.whatsapp_business_account"] = {
                "status": r.status_code, "body": _safe_json(r),
            }
            if r.status_code == 200:
                hard_fail = False
                wba = (r.json() or {}).get("whatsapp_business_account") or {}
                pn_block = wba.get("phone_numbers") or {}
                pn_list = pn_block.get("data", []) if isinstance(pn_block, dict) else (pn_block if isinstance(pn_block, list) else [])
                for pn in pn_list:
                    if isinstance(pn, dict) and pn.get("display_phone_number"):
                        d = _digits(pn["display_phone_number"])
                        if d:
                            discovered[d] = pn["display_phone_number"]
            elif r.status_code == 403:
                soft_fail = True
        except Exception as e:
            raw["page.whatsapp_business_account_error"] = str(e)

        # Probe 3: User-businesses → owned/client WABAs → phone numbers.
        # This is the most reliable path when whatsapp_business_management
        # scope is granted. It returns every WABA the user has access to;
        # we then union all discovered numbers (cross-Page check).
        if user_access_token:
            try:
                r = await client.get(
                    f"https://graph.facebook.com/{api_version}/me/businesses",
                    params={"fields": "id,name", "access_token": user_access_token},
                )
                raw["me.businesses"] = {"status": r.status_code, "body": _safe_json(r)}
                if r.status_code == 200:
                    hard_fail = False
                    for biz in r.json().get("data", []):
                        bid = biz.get("id")
                        if not bid:
                            continue
                        for edge in ("owned_whatsapp_business_accounts", "client_whatsapp_business_accounts"):
                            try:
                                rb = await client.get(
                                    f"https://graph.facebook.com/{api_version}/{bid}/{edge}",
                                    params={
                                        "fields": "id,name,phone_numbers{display_phone_number,status,code_verification_status,verified_name}",
                                        "access_token": user_access_token,
                                    },
                                )
                                raw[f"biz.{biz.get('name','?')}.{edge}"] = {
                                    "status": rb.status_code, "body": _safe_json(rb),
                                }
                                if rb.status_code == 403:
                                    soft_fail = True
                                if rb.status_code != 200:
                                    continue
                                for waba in rb.json().get("data", []):
                                    pn_block = waba.get("phone_numbers") or {}
                                    pn_list = pn_block.get("data", []) if isinstance(pn_block, dict) else (pn_block if isinstance(pn_block, list) else [])
                                    for pn in pn_list:
                                        if isinstance(pn, dict) and pn.get("display_phone_number"):
                                            d = _digits(pn["display_phone_number"])
                                            if d:
                                                discovered[d] = pn["display_phone_number"]
                            except Exception as e:
                                raw[f"biz.{edge}_error"] = str(e)
            except Exception as e:
                raw["me.businesses_error"] = str(e)

    available = list(discovered.values())

    if hard_fail:
        return WABACheck(
            valid=None,
            available_numbers=[],
            error_reason=(
                "Meta WABA endpoints all returned no data. Cannot validate "
                "the number — proceeding without strict check."
            ),
            raw_responses=raw,
        )
    if soft_fail and not discovered:
        return WABACheck(
            valid=None,
            available_numbers=[],
            error_reason=(
                "OAuth token is missing the whatsapp_business_management scope "
                "— skipping strict WABA validation. Reconnect Meta to enable."
            ),
            raw_responses=raw,
        )

    if target_digits in discovered:
        return WABACheck(
            valid=True, available_numbers=available, raw_responses=raw,
        )

    # Discovered some numbers but the target isn't among them → block.
    return WABACheck(
        valid=False,
        available_numbers=available,
        error_reason=(
            f"Number {required_phone_e164} is not assigned as a WABA phone "
            f"number on this Page (Meta returned: "
            f"{', '.join(available) if available else 'no eligible numbers'}). "
            f"Assign it via Business Settings → WhatsApp Accounts → Phone numbers, "
            f"or pick a number from the list above."
        ),
        raw_responses=raw,
    )


def _safe_json(r: httpx.Response) -> Any:
    try:
        return r.json()
    except Exception:
        return r.text[:500]
