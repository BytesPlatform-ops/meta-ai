"""
Special Ad Category — post-publish reconciliation.

When we publish an ad set under a SAC, Meta silently strips any targeting
options that aren't allowed. Our system would otherwise store what we *sent*,
not what Meta *accepted* — leading to stale targeting in the UI and the same
bad interests being suggested again on the next draft.

This service closes that loop:

  1. ``reconcile_after_publish(draft_id, ad_set_id, access_token, sac_categories)``
     — call this after every successful adset creation under a SAC. It:
         a. Fetches the live targeting from Meta's Graph API
         b. Diffs it against the targeting we sent (stored on the draft)
         c. Persists rejected interest IDs to ``sac_blocked_interests`` so
            future drafts (for any business in this SAC) skip them
         d. Updates the draft with ``actual_targeting`` + ``targeting_diff``

  2. ``get_blocked_interest_ids(sac_categories)`` — read the persisted
     blocklist for a SAC. Used by the targeting engine to pre-filter
     interest candidates before sending to Meta.

Design principles
-----------------
- **Generic.** No business-specific or category-specific logic — works for
  any SAC (HEC, Financial, etc.) and any vertical.
- **Eventually-consistent friendly.** Meta's strip can take a few seconds
  after adset creation. The caller should delay (~30s) before invoking, or
  the reconciler can be invoked again later for re-checking.
- **Idempotent.** Calling reconcile twice on the same ad set is safe —
  blocklist uses upsert semantics, draft update is overwrite.
- **Service-role auth only.** All DB writes use the service-role client so
  RLS doesn't block updates from the publisher pipeline.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ..core.config import get_settings
from ..db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────


async def reconcile_after_publish(
    *,
    draft_id: str,
    ad_set_id: str,
    access_token: str,
    sac_categories: list[str] | None = None,
    delay_seconds: float = 30.0,
    mcp_final_targeting: dict | None = None,
) -> dict[str, Any] | None:
    """Reconcile the published ad set against what we sent.

    Args:
        draft_id: UUID of the content_drafts row.
        ad_set_id: Meta ad set ID returned by stage_advanced_campaign.
        access_token: workspace's Meta access token (ads_read scope).
        sac_categories: list of SAC category codes attached to the campaign,
            e.g. ``["FINANCIAL_PRODUCTS_SERVICES"]``. Pass None or [] for
            non-SAC drafts — the function will no-op (no diff to learn from).
        delay_seconds: how long to wait before fetching live targeting. Meta's
            strip is eventually consistent; default 30s is conservative.
        mcp_final_targeting: targeting object the MCP server actually POSTed
            to Meta (after SAC strips, auto-retries, nuclear strip). When
            provided, the diff is computed against THIS — not the draft's
            original targeting. Critical for accuracy: without it, MCP-side
            strips would be falsely attributed to Meta and blocklisted.

    Returns:
        Dict summarising the reconciliation, or None if skipped.
    """
    if not sac_categories:
        return None  # nothing to reconcile — no SAC, no silent strip happens
    if not draft_id or not ad_set_id or not access_token:
        logger.warning(
            "reconcile_after_publish: missing args (draft_id=%s, ad_set_id=%s)",
            draft_id, ad_set_id,
        )
        return None

    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)

    supabase = get_supabase()

    # 1. Determine what we actually sent to Meta. Prefer the MCP-confirmed
    # final_targeting (post all internal strips); fall back to the draft's
    # stored targeting only when the MCP didn't tell us what it sent.
    if isinstance(mcp_final_targeting, dict):
        sent_interests = _extract_interests(mcp_final_targeting)
    else:
        draft_row = (
            supabase.table("content_drafts")
            .select("id, targeting, targeting_spec")
            .eq("id", draft_id)
            .limit(1)
            .execute()
        )
        if not draft_row.data:
            logger.warning("reconcile: draft %s not found", draft_id)
            return None
        draft = draft_row.data[0]
        sent_interests = _extract_sent_interests(draft)

    # 2. Fetch live targeting from Meta.
    live_targeting = await _fetch_live_targeting(ad_set_id, access_token)
    if not live_targeting:
        logger.warning("reconcile: could not fetch live targeting for adset %s", ad_set_id)
        return None
    live_interests = _extract_interests(live_targeting)

    # 3. Diff.
    diff = _build_diff(sent_interests, live_interests, live_targeting)

    # 4. Persist any newly-discovered rejected interests to the global blocklist.
    rejected = diff.get("stripped_interests") or []
    if rejected and sac_categories:
        await _persist_blocklist_entries(rejected, sac_categories)

    # 5. Write actual_targeting + targeting_diff back to the draft.
    try:
        supabase.table("content_drafts").update({
            "actual_targeting": live_targeting,
            "targeting_diff": diff,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", draft_id).execute()
    except Exception as e:
        logger.warning("reconcile: failed to persist diff on draft %s: %s", draft_id, e)

    logger.info(
        "reconcile: draft %s adset %s — sent %d interests, Meta kept %d, stripped %d (severity=%s)",
        draft_id, ad_set_id, len(sent_interests), len(live_interests),
        len(rejected), diff.get("severity"),
    )

    # 6. Phase B — auto-recovery. When Meta strips most or all interests,
    # ask the LLM for SAC-safe replacements and PATCH the live ad set so
    # the campaign isn't running with degraded or empty targeting. Bounded
    # by attempts; surfaces status to UI via auto_recovery_status. We
    # delay-import to avoid a circular at module-load time.
    if diff.get("severity") in ("heavy", "total_strip"):
        try:
            from .sac_recovery import schedule_recovery
            schedule_recovery(
                draft_id=draft_id,
                ad_set_id=ad_set_id,
                access_token=access_token,
                sac_categories=sac_categories,
                diff=diff,
                delay_seconds=10.0,
            )
        except Exception as e:
            logger.exception("reconcile: failed to schedule recovery: %s", e)

    return diff


def schedule_reconciliation(
    *,
    draft_id: str,
    ad_set_id: str,
    access_token: str,
    sac_categories: list[str] | None,
    delay_seconds: float = 30.0,
    mcp_final_targeting: dict | None = None,
) -> None:
    """Fire-and-forget: schedule the reconciler as a background asyncio task.

    Use this from publish flows that shouldn't block on the 30s delay.
    Errors are logged but never propagate to the caller. When the MCP
    server returns ``final_targeting`` in its response, pass it through
    so the diff isn't polluted by our own MCP-side strips.
    """
    if not sac_categories:
        return  # nothing to do for non-SAC drafts

    async def _run() -> None:
        try:
            await reconcile_after_publish(
                draft_id=draft_id,
                ad_set_id=ad_set_id,
                access_token=access_token,
                sac_categories=sac_categories,
                delay_seconds=delay_seconds,
                mcp_final_targeting=mcp_final_targeting,
            )
        except Exception as e:
            logger.exception("reconcile background task failed: %s", e)

    try:
        asyncio.create_task(_run())
    except RuntimeError:
        # No running event loop — caller is sync. Run synchronously instead
        # (will block on the delay; only matters in non-async contexts).
        asyncio.run(_run())


def get_blocked_interest_ids(sac_categories: list[str] | None) -> set[str]:
    """Return the set of Meta interest IDs the system has learned are
    rejected under any of the given SAC categories. Used by the targeting
    engine to pre-filter candidates before sending to Meta.

    Cheap query — small table, single roundtrip. Caller can cache if needed.
    """
    if not sac_categories:
        return set()
    try:
        supabase = get_supabase()
        rows = (
            supabase.table("sac_blocked_interests")
            .select("interest_id, sac_category")
            .in_("sac_category", sac_categories)
            .execute()
        )
        return {str(r["interest_id"]) for r in (rows.data or []) if r.get("interest_id")}
    except Exception as e:
        logger.warning("get_blocked_interest_ids failed: %s", e)
        return set()


# ── Internals ────────────────────────────────────────────────────────────────


def _extract_sent_interests(draft: dict) -> list[dict]:
    """Pull the interests we sent to Meta from the draft's stored targeting.

    The draft stores both ``targeting`` (full Meta payload) and
    ``targeting_spec`` (validated_interests summary). Prefer ``targeting``
    since it's the authoritative payload — fall back to ``targeting_spec``.
    """
    targeting = draft.get("targeting") or {}
    if isinstance(targeting, str):
        try:
            import json
            targeting = json.loads(targeting)
        except Exception:
            targeting = {}
    interests = _extract_interests(targeting)
    if interests:
        return interests

    # Fallback: targeting_spec.validated_interests
    spec = draft.get("targeting_spec") or {}
    if isinstance(spec, str):
        try:
            import json
            spec = json.loads(spec)
        except Exception:
            spec = {}
    return list(spec.get("validated_interests") or [])


def _extract_interests(targeting: dict) -> list[dict]:
    """Pull interests out of any Meta targeting object, regardless of whether
    they're stored under flexible_spec[*].interests or top-level interests."""
    out: list[dict] = []
    if not isinstance(targeting, dict):
        return out
    seen_ids: set[str] = set()

    def _add(items: list) -> None:
        for it in items or []:
            if not isinstance(it, dict):
                continue
            iid = str(it.get("id") or "")
            if not iid or iid in seen_ids:
                continue
            seen_ids.add(iid)
            out.append({"id": iid, "name": it.get("name") or ""})

    _add(targeting.get("interests"))
    for spec in (targeting.get("flexible_spec") or []):
        if isinstance(spec, dict):
            _add(spec.get("interests"))
    return out


async def _fetch_live_targeting(ad_set_id: str, access_token: str) -> dict | None:
    """Fetch the targeting Meta is actually using on the live ad set."""
    settings = get_settings()
    api_version = getattr(settings, "META_API_VERSION", "v22.0")
    url = f"https://graph.facebook.com/{api_version}/{ad_set_id}"
    params = {
        # ``targeting_automation`` lives inside the targeting object, not as
        # a sibling field. Asking for it at the top level returns Meta error
        # #100 "nonexisting field". Just ask for ``targeting`` and read the
        # nested automation block from there.
        "fields": "targeting,effective_status",
        "access_token": access_token,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning(
                    "_fetch_live_targeting: HTTP %d from Meta for adset %s — %s",
                    resp.status_code, ad_set_id, resp.text[:300],
                )
                return None
            data = resp.json()
            targeting = data.get("targeting")
            if not isinstance(targeting, dict):
                return None
            return targeting
    except Exception as e:
        logger.warning("_fetch_live_targeting failed for %s: %s", ad_set_id, e)
        return None


def _build_diff(
    sent: list[dict], live: list[dict], live_targeting: dict
) -> dict[str, Any]:
    """Produce a structured diff describing what Meta did to our targeting."""
    sent_ids = {str(i.get("id")): (i.get("name") or "") for i in sent}
    live_ids = {str(i.get("id")) for i in live}

    stripped = [
        {"id": iid, "name": name}
        for iid, name in sent_ids.items()
        if iid and iid not in live_ids
    ]
    kept = [
        {"id": iid, "name": name}
        for iid, name in sent_ids.items()
        if iid and iid in live_ids
    ]

    sent_total = len(sent_ids)
    stripped_count = len(stripped)
    if sent_total == 0:
        severity = "no_interests_sent"
    elif stripped_count == 0:
        severity = "clean"
    elif stripped_count == sent_total:
        severity = "total_strip"
    elif stripped_count / sent_total >= 0.5:
        severity = "heavy"
    else:
        severity = "partial"

    return {
        "severity": severity,
        "sent_count": sent_total,
        "kept_count": len(kept),
        "stripped_count": stripped_count,
        "stripped_interests": stripped,
        "kept_interests": kept,
        "advantage_audience_active": (
            (live_targeting.get("targeting_automation") or {}).get("advantage_audience") == 1
        ),
        "reconciled_at": datetime.now(timezone.utc).isoformat(),
    }


async def _persist_blocklist_entries(
    rejected: list[dict], sac_categories: list[str]
) -> None:
    """Upsert each (interest_id, sac_category) pair into the blocklist.

    Uses one POST per pair so the upsert "increment on conflict" semantics
    work. Total payload is tiny (<10 inserts typical). PostgREST handles the
    on-conflict update via the unique index on (interest_id, sac_category).
    """
    if not rejected or not sac_categories:
        return
    settings = get_settings()
    base_url = settings.SUPABASE_URL.rstrip("/")
    headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    url = f"{base_url}/rest/v1/sac_blocked_interests?on_conflict=interest_id,sac_category"
    rows: list[dict] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for cat in sac_categories:
        for r in rejected:
            iid = str(r.get("id") or "").strip()
            name = (r.get("name") or "").strip()
            if not iid:
                continue
            rows.append({
                "interest_id": iid,
                "interest_name": name or iid,
                "sac_category": cat,
                "last_blocked_at": now_iso,
                "block_count": 1,  # the merge-duplicates path overwrites; we
                                   # bump count via a separate increment below.
                "source": "reconciliation",
            })
    if not rows:
        return
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # First: ensure the row exists (upsert, no count change for new rows).
            resp = await client.post(url, headers=headers, json=rows)
            if resp.status_code not in (200, 201, 204):
                logger.warning(
                    "_persist_blocklist_entries: upsert HTTP %d — %s",
                    resp.status_code, resp.text[:300],
                )
                return
            # Second: increment block_count + bump last_blocked_at via RPC-style
            # patch per (interest_id, sac_category). One PATCH per row keeps it
            # straightforward; volume is low.
            for r in rows:
                patch_url = (
                    f"{base_url}/rest/v1/sac_blocked_interests"
                    f"?interest_id=eq.{r['interest_id']}"
                    f"&sac_category=eq.{r['sac_category']}"
                )
                # Read-then-write to bump the counter atomically enough for our
                # purposes (race conditions just under-count by 1, which is fine
                # for a learning signal).
                read = await client.get(
                    patch_url + "&select=block_count",
                    headers={"apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
                             "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}"},
                )
                current = 1
                if read.status_code == 200 and read.json():
                    current = int(read.json()[0].get("block_count") or 1)
                await client.patch(
                    patch_url,
                    headers=headers,
                    json={"block_count": current + 1, "last_blocked_at": now_iso},
                )
    except Exception as e:
        logger.warning("_persist_blocklist_entries: %s", e)
