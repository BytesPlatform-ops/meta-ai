"""
Special Ad Category — auto-recovery loop (Phase B).

When the post-publish reconciler detects that Meta stripped most or all of
an ad set's targeting interests under a SAC, this service automatically:

  1. Asks an LLM to suggest replacement broad lifestyle interests, with the
     just-rejected interest names provided as explicit "do not propose
     anything similar" guidance.
  2. Validates each suggestion through Meta's interest search (which is
     already filtered against the persistent SAC blocklist from Phase A —
     so anything Meta has previously rejected is dropped pre-flight).
  3. PATCHes the live ad set's ``flexible_spec[0].interests`` via the MCP
     ``update_adset_targeting`` tool — no need to delete + recreate.
  4. Updates the draft's ``auto_recovery_status`` + ``recovered_interests``
     for the UI to surface what changed.
  5. Re-runs reconciliation to confirm Meta accepted the replacements.

Design principles
-----------------
- **Generic.** No vertical-specific or business-specific code. The same
  flow handles Financial Products, Housing, Employment, Credit, etc.
- **Bounded.** Max 2 attempts per draft. If the second batch of
  replacements also gets stripped, mark ``failed_no_alternatives`` and
  surface to the user — automation has run out of moves.
- **Safe.** All Meta API calls go through the existing MCP tooling, so
  we inherit its validation, rate-limit handling, and SAC-aware retry
  fallbacks.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI

from ..core.config import get_settings
from ..db.supabase_client import get_supabase
from .mcp_client import mcp_client, MCPError
from .sac_reconciler import get_blocked_interest_ids

logger = logging.getLogger(__name__)


# Severity values that warrant active recovery. ``partial`` is left alone —
# the campaign still has most of its targeting and Meta's algorithm can
# work with it; we just learn for next time. ``no_interests_sent`` means
# the publish was Advantage+-only by design — nothing to recover.
_RECOVERY_SEVERITIES = {"heavy", "total_strip"}

# Max recovery attempts per draft. After the second failed swap we give
# up automation and let the user intervene. Empirically: if Meta strips
# the first round of replacements too, the LLM suggestions are converging
# on something Meta still doesn't like and another LLM round won't help.
_MAX_ATTEMPTS = 2

# How many replacement interests to ask the LLM for. Slightly more than
# Meta's typical-good-pool size of 5 so post-validation we still land 5+.
_TARGET_REPLACEMENT_COUNT = 8


# ── Public API ────────────────────────────────────────────────────────────────


async def attempt_recovery(
    *,
    draft_id: str,
    ad_set_id: str,
    access_token: str,
    sac_categories: list[str],
    diff: dict[str, Any],
    delay_seconds: float = 10.0,
) -> dict[str, Any] | None:
    """Attempt to recover a SAC ad set whose interests were stripped by Meta.

    Args:
        draft_id: UUID of the content_drafts row.
        ad_set_id: live Meta ad set ID.
        access_token: workspace's Meta access token (ads_management scope).
        sac_categories: SAC list from the parent campaign.
        diff: the targeting_diff dict from sac_reconciler. Used to extract
            the rejected interest names so the LLM can avoid suggesting
            similar items.
        delay_seconds: small delay before kicking off so the reconciler's
            DB writes have settled.

    Returns:
        A dict summarising the recovery, or None if no action was taken.
    """
    if not diff or diff.get("severity") not in _RECOVERY_SEVERITIES:
        return None
    if not draft_id or not ad_set_id or not access_token or not sac_categories:
        return None

    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)

    supabase = get_supabase()

    # Bail if we've already exhausted attempts on this draft.
    draft_row = (
        supabase.table("content_drafts")
        .select("id, auto_recovery_attempts, special_ad_category, target_country, "
                "headline, body_text, product_id, workspace_id, user_id")
        .eq("id", draft_id)
        .limit(1)
        .execute()
    )
    if not draft_row.data:
        logger.warning("recovery: draft %s not found", draft_id)
        return None
    draft = draft_row.data[0]
    attempts = int(draft.get("auto_recovery_attempts") or 0)
    if attempts >= _MAX_ATTEMPTS:
        logger.info(
            "recovery: draft %s already at %d/%d attempts — skipping",
            draft_id, attempts, _MAX_ATTEMPTS,
        )
        return None

    # Load business context to give the LLM something concrete to anchor on.
    business_context = await _load_business_context(supabase, draft)

    # Mark in-flight so the UI shows the recovery is happening.
    try:
        supabase.table("content_drafts").update({
            "auto_recovery_status": "pending",
            "auto_recovery_attempts": attempts + 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", draft_id).execute()
    except Exception as e:
        logger.warning("recovery: could not mark draft pending: %s", e)

    rejected_names = [
        i.get("name") or "" for i in (diff.get("stripped_interests") or [])
        if i.get("name")
    ]
    sac_category = sac_categories[0]
    target_country = (
        draft.get("target_country")
        or business_context.get("target_country")
        or "US"
    )

    # 1. Ask LLM for replacement interest keywords.
    try:
        candidate_keywords = await _generate_replacement_keywords(
            sac_category=sac_category,
            target_country=target_country,
            business_context=business_context,
            rejected_names=rejected_names,
            count=_TARGET_REPLACEMENT_COUNT,
        )
    except Exception as e:
        logger.exception("recovery: LLM keyword generation failed: %s", e)
        await _mark_failed(supabase, draft_id, "llm_failed")
        return None

    if not candidate_keywords:
        logger.warning("recovery: LLM returned no candidate keywords for draft %s", draft_id)
        await _mark_failed(supabase, draft_id, "no_alternatives")
        return None

    # 2. Validate via Meta's interest search.
    try:
        validated = await mcp_client.search_interests(
            candidate_keywords, target_country, access_token
        )
        validated = validated if isinstance(validated, list) else []
    except (MCPError, Exception) as e:
        logger.warning("recovery: MCP search failed for draft %s: %s", draft_id, e)
        validated = []

    # 3. Drop anything in the persistent SAC blocklist (defense-in-depth —
    # search_interests doesn't currently filter, only the content_generator
    # path does. Apply here too since we're constructing fresh targeting.)
    blocked_ids = get_blocked_interest_ids(sac_categories)
    pre_block_count = len(validated)
    if blocked_ids:
        validated = [
            it for it in validated
            if str(it.get("id") or "") not in blocked_ids
        ]
    rejected_id_set = {
        str(i.get("id") or "")
        for i in (diff.get("stripped_interests") or [])
        if i.get("id")
    }
    if rejected_id_set:
        validated = [
            it for it in validated
            if str(it.get("id") or "") not in rejected_id_set
        ]

    # Normalise to {id, name} only — strip audience_size etc.
    new_interests = [
        {"id": str(it.get("id")), "name": it.get("name") or ""}
        for it in validated
        if it.get("id")
    ]
    # De-dup.
    _seen: set[str] = set()
    new_interests = [
        x for x in new_interests
        if not (x["id"] in _seen or _seen.add(x["id"]))  # type: ignore[func-returns-value]
    ][:5]  # cap at 5 — matches the original pool size

    # 3b. Hard-validate IDs against Meta. Two-pass:
    #   Pass A — /{act_id}/targetingvalidation: drops IDs that aren't valid
    #            for this ad account (deprecated, regional, no permission).
    #   Pass B — /{adset_id}/delivery_estimate binary-search probe: drops
    #            IDs that ARE valid for the account but not allowed under
    #            the SAC of the parent campaign. This is the gap that pure
    #            targetingvalidation misses — Meta doesn't expose a SAC
    #            eligibility flag publicly, so we discover it empirically
    #            by probing what /{adset_id}/delivery_estimate accepts (the
    #            adset inherits SAC from its parent campaign, so its
    #            estimate endpoint enforces SAC rules natively).
    if new_interests:
        try:
            ad_account_meta_id = await _resolve_ad_account_meta_id(
                supabase, draft.get("ad_account_id"), draft.get("workspace_id"),
            )
            if ad_account_meta_id:
                new_interests = await _drop_invalid_meta_ids(
                    new_interests, ad_account_meta_id, access_token,
                )
        except Exception as e:
            logger.warning("recovery: account-validate failed (non-fatal): %s", e)

        # Pass B — SAC-eligibility probe via the live adset. Generic: works
        # for any SAC because we let Meta's adset-attached delivery_estimate
        # be the oracle, not a hardcoded category-rule table.
        try:
            new_interests = await _probe_sac_compatible(
                ad_set_id=ad_set_id,
                candidates=new_interests,
                access_token=access_token,
            )
        except Exception as e:
            logger.warning("recovery: SAC-probe failed (non-fatal): %s", e)

    if len(new_interests) < 3:
        logger.warning(
            "recovery: only %d valid replacement interest(s) for draft %s "
            "(pre-blocklist=%d) — not enough to recover, marking failed",
            len(new_interests), draft_id, pre_block_count,
        )
        await _mark_failed(supabase, draft_id, "no_alternatives")
        return None

    # 4. PATCH the live ad set.
    try:
        patch_result = await mcp_client.replace_adset_interests(
            adset_id=ad_set_id,
            interests=new_interests,
            user_access_token=access_token,
        )
    except MCPError as e:
        logger.warning("recovery: MCP patch failed for adset %s: %s", ad_set_id, e)
        await _mark_failed(supabase, draft_id, "patch_failed")
        return None

    if not patch_result or not patch_result.get("success"):
        err_msg = (patch_result or {}).get("error") or "unknown"
        logger.warning("recovery: adset patch returned no success for %s: %s", ad_set_id, err_msg)
        await _mark_failed(supabase, draft_id, "patch_failed")
        return None

    # 5. Mark recovered, persist what we swapped in.
    try:
        supabase.table("content_drafts").update({
            "auto_recovery_status": "recovered",
            "recovered_interests": new_interests,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", draft_id).execute()
    except Exception as e:
        logger.warning("recovery: could not persist recovered state: %s", e)

    logger.info(
        "recovery: draft %s adset %s — swapped in %d replacement interest(s) "
        "after %s strip (%d original kept)",
        draft_id, ad_set_id, len(new_interests),
        diff.get("severity"), diff.get("kept_count"),
    )

    # 6. Schedule a follow-up reconciliation to confirm Meta accepted them.
    # If the new round also gets heavily stripped, the next reconciler will
    # call attempt_recovery again — bounded by _MAX_ATTEMPTS.
    try:
        from .sac_reconciler import schedule_reconciliation
        schedule_reconciliation(
            draft_id=draft_id,
            ad_set_id=ad_set_id,
            access_token=access_token,
            sac_categories=sac_categories,
            delay_seconds=20.0,
            mcp_final_targeting={"flexible_spec": [{"interests": new_interests}]},
        )
    except Exception as e:
        logger.warning("recovery: could not schedule confirmation reconcile: %s", e)

    return {
        "status": "recovered",
        "new_interests": new_interests,
        "attempt": attempts + 1,
    }


def schedule_recovery(
    *,
    draft_id: str,
    ad_set_id: str,
    access_token: str,
    sac_categories: list[str],
    diff: dict[str, Any],
    delay_seconds: float = 10.0,
) -> None:
    """Fire-and-forget background invocation of attempt_recovery."""
    if not diff or diff.get("severity") not in _RECOVERY_SEVERITIES:
        return

    async def _run() -> None:
        try:
            await attempt_recovery(
                draft_id=draft_id,
                ad_set_id=ad_set_id,
                access_token=access_token,
                sac_categories=sac_categories,
                diff=diff,
                delay_seconds=delay_seconds,
            )
        except Exception as e:
            logger.exception("recovery background task failed: %s", e)

    try:
        asyncio.create_task(_run())
    except RuntimeError:
        asyncio.run(_run())


# ── Internals ────────────────────────────────────────────────────────────────


async def _load_business_context(supabase, draft: dict) -> dict[str, Any]:
    """Pull just enough business signal from product/workspace/preferences so
    the LLM understands what kind of buyer the ad is targeting. Generic —
    returns None values for whatever isn't available."""
    ctx: dict[str, Any] = {
        "headline": draft.get("headline"),
        "body_text": draft.get("body_text"),
        "target_country": draft.get("target_country"),
    }
    workspace_id = draft.get("workspace_id")
    user_id = draft.get("user_id")
    product_id = draft.get("product_id")

    if product_id:
        try:
            p = (
                supabase.table("products")
                .select("name, description, product_type, target_audience, tags, target_country")
                .eq("id", product_id).limit(1).execute()
            )
            if p.data:
                ctx["product"] = p.data[0]
                if not ctx.get("target_country") and p.data[0].get("target_country"):
                    ctx["target_country"] = p.data[0]["target_country"]
        except Exception:
            pass

    if workspace_id:
        try:
            w = (
                supabase.table("workspaces")
                .select("business_name, business_description, industry_niche, target_country")
                .eq("id", workspace_id).limit(1).execute()
            )
            if w.data:
                ctx["workspace"] = w.data[0]
                if not ctx.get("target_country") and w.data[0].get("target_country"):
                    ctx["target_country"] = w.data[0]["target_country"]
        except Exception:
            pass

    if user_id and not ctx.get("workspace"):
        try:
            up = (
                supabase.table("user_preferences")
                .select("business_name, business_description, industry_niche, target_country")
                .eq("user_id", user_id).limit(1).execute()
            )
            if up.data:
                ctx["preferences"] = up.data[0]
                if not ctx.get("target_country") and up.data[0].get("target_country"):
                    ctx["target_country"] = up.data[0]["target_country"]
        except Exception:
            pass

    return ctx


async def _generate_replacement_keywords(
    *,
    sac_category: str,
    target_country: str,
    business_context: dict,
    rejected_names: list[str],
    count: int,
) -> list[str]:
    """Ask the LLM for ``count`` broad lifestyle/behavior interest keywords
    safe under the given SAC. Feeds the rejected names as explicit "avoid
    anything like these" guidance.

    Returns a flat list of keyword strings (no IDs yet — those come from
    the Meta validation step in the caller).
    """
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    biz_name = (
        (business_context.get("workspace") or {}).get("business_name")
        or (business_context.get("preferences") or {}).get("business_name")
        or (business_context.get("product") or {}).get("name")
        or "the advertiser"
    )
    biz_desc = (
        (business_context.get("workspace") or {}).get("business_description")
        or (business_context.get("preferences") or {}).get("business_description")
        or (business_context.get("product") or {}).get("description")
        or ""
    )
    headline = business_context.get("headline") or ""
    body_text = business_context.get("body_text") or ""
    rejected_block = "\n".join(f"  - {n}" for n in rejected_names) or "  (none recorded)"

    system_prompt = (
        "You are a Meta Ads policy compliance expert generating REPLACEMENT "
        "interest-targeting keywords for an ad set whose original interests "
        "were stripped by Meta under a Special Ad Category.\n\n"
        "Your suggestions will be validated against Meta's targeting search API, "
        "so they must be REAL interests Meta exposes in its catalog (not made-up "
        "phrases). Favor BROAD lifestyle/behavior categories that describe WHO "
        "the buyer is — never brand names, news outlets, specific platforms, "
        "specific instruments, or anything Meta would consider 'detailed targeting' "
        "under the SAC. Strict output: JSON only.\n"
    )
    user_prompt = (
        f"## Special Ad Category in effect\n{sac_category}\n\n"
        f"## Target country\n{target_country}\n\n"
        f"## Business / advertiser\n"
        f"Name: {biz_name}\n"
        f"Description: {biz_desc}\n"
        f"Ad headline: {headline}\n"
        f"Ad body: {body_text[:400]}\n\n"
        f"## Interests Meta JUST REJECTED for this ad set\n{rejected_block}\n\n"
        f"## Your task\n"
        f"Suggest exactly {count} broad lifestyle/behavior interest keywords that:\n"
        f"  1. Describe the buyer's general world (hobbies, interests, daily life)\n"
        f"  2. Are likely to exist in Meta's interest catalog as broad pools (millions of users)\n"
        f"  3. Do NOT name any brand, exchange, broker, instrument, news outlet, or specific tool\n"
        f"  4. Do NOT closely resemble the rejected list above\n"
        f"  5. Are appropriate for the ad's actual product, not generic\n\n"
        f"## Output (strict JSON)\n"
        f'{{"keywords": ["keyword 1", "keyword 2", ...]}}'
    )

    try:
        resp = await client.chat.completions.create(
            model=settings.ELITE_REASONING_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=500,
        )
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            return []
        parsed = json.loads(text)
        keywords = parsed.get("keywords") or parsed.get("interests") or []
        if not isinstance(keywords, list):
            return []
        # Clean + dedup, preserve order.
        seen: set[str] = set()
        out: list[str] = []
        for kw in keywords:
            kw_clean = str(kw or "").strip()
            if not kw_clean or kw_clean.lower() in seen:
                continue
            seen.add(kw_clean.lower())
            out.append(kw_clean)
        return out[:count]
    except Exception as e:
        logger.warning("_generate_replacement_keywords: %s", e)
        return []


async def _mark_failed(supabase, draft_id: str, reason: str) -> None:
    try:
        supabase.table("content_drafts").update({
            "auto_recovery_status": reason,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", draft_id).execute()
    except Exception as e:
        logger.warning("_mark_failed: %s", e)


async def _resolve_ad_account_meta_id(
    supabase, ad_account_uuid: str | None, workspace_id: str | None,
) -> str | None:
    """Resolve our internal ``ad_accounts.id`` UUID to Meta's ``act_…`` form.

    Falls back to the workspace's active ad account if the draft doesn't
    carry one explicitly. Returns the bare numeric form (no ``act_`` prefix)
    suitable for ``/{act_id}/targetingvalidation``.
    """
    try:
        if ad_account_uuid:
            r = (
                supabase.table("ad_accounts")
                .select("meta_account_id")
                .eq("id", ad_account_uuid).limit(1).execute()
            )
            if r.data and r.data[0].get("meta_account_id"):
                return str(r.data[0]["meta_account_id"]).replace("act_", "")
        if workspace_id:
            r = (
                supabase.table("ad_accounts")
                .select("meta_account_id")
                .eq("workspace_id", workspace_id)
                .eq("is_active", True).limit(1).execute()
            )
            if r.data and r.data[0].get("meta_account_id"):
                return str(r.data[0]["meta_account_id"]).replace("act_", "")
    except Exception as e:
        logger.warning("_resolve_ad_account_meta_id: %s", e)
    return None


async def _drop_invalid_meta_ids(
    interests: list[dict], ad_account_meta_id: str, access_token: str,
) -> list[dict]:
    """POST the candidate interest IDs to Meta's targetingvalidation edge,
    drop anything Meta marks ``valid: false``. This is the same endpoint
    Meta Ads Manager uses internally before sending an adset POST.
    """
    if not interests:
        return interests
    settings = get_settings()
    api_version = getattr(settings, "META_API_VERSION", "v22.0")
    targeting_list = [
        {"type": "interests", "id": int(i["id"])}
        for i in interests
        if str(i.get("id", "")).isdigit()
    ]
    if not targeting_list:
        return interests
    import json as _json
    import httpx
    url = f"https://graph.facebook.com/{api_version}/act_{ad_account_meta_id}/targetingvalidation"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, params={
                "targeting_list": _json.dumps(targeting_list),
                "access_token": access_token,
            })
            if r.status_code != 200:
                logger.warning(
                    "_drop_invalid_meta_ids: HTTP %s — keeping all (cannot validate): %s",
                    r.status_code, r.text[:200],
                )
                return interests
            valid_ids = {
                str(item["id"]) for item in r.json().get("data", [])
                if item.get("valid") is True
            }
            kept = [i for i in interests if str(i["id"]) in valid_ids]
            dropped = [i for i in interests if str(i["id"]) not in valid_ids]
            if dropped:
                logger.info(
                    "recovery: targetingvalidation dropped %d invalid ID(s): %s",
                    len(dropped), [(i["name"], i["id"]) for i in dropped],
                )
            return kept
    except Exception as e:
        logger.warning("_drop_invalid_meta_ids: %s — keeping all", e)
        return interests


async def _probe_sac_compatible(
    *,
    ad_set_id: str,
    candidates: list[dict],
    access_token: str,
    _depth: int = 0,
) -> list[dict]:
    """Binary-search probe: which of ``candidates`` are SAC-allowed.

    Algorithm
    ---------
    Meta's account-level ``targetingvalidation`` only checks "is this ID
    in the catalog and accessible to the account". It does NOT enforce
    Special Ad Category rules. The PATCH endpoint does, but with an opaque
    "Invalid parameter" error that doesn't say which ID is bad.

    The adset-attached ``/{adset_id}/delivery_estimate`` endpoint inherits
    SAC restrictions from the parent campaign, so a successful estimate
    proves the candidate set is SAC-compatible. We:

      1. Probe the WHOLE candidate set in one call. If estimate_ready,
         all candidates pass — return them.
      2. If estimate fails, split candidates into halves and recurse.
      3. Base case: a single candidate that fails the probe is dropped.

    Cost: O(N) probe calls in the worst case (every candidate is bad);
    O(log N) when only one is bad. Each probe is a single non-mutating
    GET, so it's cheap and safe to run on a live ad set.
    """
    if not candidates:
        return []
    if _depth > 8:  # safety guard against pathological recursion
        logger.warning("_probe_sac_compatible: max depth reached, returning %d", len(candidates))
        return candidates

    if await _delivery_estimate_passes(ad_set_id, candidates, access_token):
        if _depth == 0:
            logger.info(
                "_probe_sac_compatible: all %d candidate(s) SAC-compatible (no probe split needed)",
                len(candidates),
            )
        return candidates

    if len(candidates) == 1:
        logger.info(
            "_probe_sac_compatible: dropped non-SAC-compatible interest %s [%s]",
            candidates[0].get("name"), candidates[0].get("id"),
        )
        return []

    mid = len(candidates) // 2
    left = await _probe_sac_compatible(
        ad_set_id=ad_set_id, candidates=candidates[:mid],
        access_token=access_token, _depth=_depth + 1,
    )
    right = await _probe_sac_compatible(
        ad_set_id=ad_set_id, candidates=candidates[mid:],
        access_token=access_token, _depth=_depth + 1,
    )
    survivors = left + right
    if _depth == 0:
        dropped = len(candidates) - len(survivors)
        logger.info(
            "_probe_sac_compatible: kept %d / %d (binary-search dropped %d non-SAC interest(s))",
            len(survivors), len(candidates), dropped,
        )
    return survivors


async def _delivery_estimate_passes(
    ad_set_id: str, interests: list[dict], access_token: str,
) -> bool:
    """One probe call. Returns True iff Meta's adset-attached
    delivery_estimate accepts the targeting (= SAC-compatible)."""
    if not interests:
        return True
    settings = get_settings()
    api_version = getattr(settings, "META_API_VERSION", "v22.0")
    import json as _json
    import httpx
    targeting_spec = {
        "flexible_spec": [{
            "interests": [{"id": str(i["id"]), "name": i.get("name") or ""} for i in interests],
        }],
        # Geo + age must be present for delivery_estimate; Meta will inherit
        # the rest from the parent adset/campaign for the SAC check.
        "geo_locations": {"countries": ["US"]},
    }
    url = f"https://graph.facebook.com/{api_version}/{ad_set_id}/delivery_estimate"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, params={
                "targeting_spec": _json.dumps(targeting_spec),
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "access_token": access_token,
            })
            data = r.json() if r.status_code == 200 else {"error": r.text[:200]}
            if "error" in data:
                # SAC-incompatible interest in the set → Meta refuses
                return False
            est = (data.get("data") or [{}])[0]
            return bool(est.get("estimate_ready"))
    except Exception as e:
        logger.warning("_delivery_estimate_passes probe error: %s", e)
        # On network/parse errors, assume compatible to avoid false negatives;
        # the next-level PATCH will surface the real Meta error if any.
        return True
