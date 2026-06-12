"""
Special Ad Category targeting policy.

When a campaign declares ``special_ad_categories``, Meta enforces strict rules
on what the ad set's ``targeting`` payload may contain. Sending a disallowed
field doesn't get silently ignored — Meta rejects the entire ad set with one
of:

  - #2909034  geo countries don't match special_ad_category_country
  - #2909035  age/gender narrowing not allowed
  - #2909049  detailed-targeting option not allowed under SAC
  - #2069038  Lookalike audiences not allowed under SAC

This module is the system's authoritative knowledge of what each category
allows. ``apply_sac_policy`` returns a sanitised ``targeting`` object plus a
report of what was stripped, so the publisher can show the user what changed
and we don't depend on Meta's silent post-creation strip.

Sources kept in sync with:
  - Meta Transparency Center (Financial / Credit / Housing / Employment policy)
  - Meta Business Help — Special Ad Categories (Mar 2026 update: detailed
    targeting exclusions removed, BNPL + crypto lending → Credit, financial
    advertiser verification mandatory in 38 countries)
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)


# ── Category strictness tiers ────────────────────────────────────────────────

# HEC (Housing/Employment/Credit) — strict bucket. Age/gender stripped, brand
# interests stripped, detailed exclusions removed entirely (Mar 2026), 25 km
# minimum geo radius, Lookalikes disabled.
_HEC = {"HOUSING", "EMPLOYMENT", "CREDIT"}

# Soft bucket — same restrictions as HEC EXCEPT age narrowing allowed (>=18)
# and gender narrowing partially allowed in some regions.
_SOFT = {"FINANCIAL_PRODUCTS_SERVICES"}

# Authorization-required tier — beyond automatic stripping; needs verification
# flow Meta-side. We log a warning but don't try to fix.
_AUTH = {"ISSUES_ELECTIONS_POLITICS", "ONLINE_GAMBLING_AND_GAMING"}


# ── Per-category brand & instrument blocklists ───────────────────────────────
#
# These are regex patterns matched against the lower-cased interest *name*
# Meta returned. We strip on match so Meta doesn't reject the whole ad set
# at POST. The lists are deliberately conservative — we'd rather lose 1
# targetable interest than 100% of the ad set.

# Anything that looks like a brand name (specific company / publication /
# platform / exchange / instrument). The Mar 2026 Meta update collapsed many
# such interests, so this list is a safety net.
_FINANCIAL_BLOCKED_PATTERNS = [
    # Brokers / exchanges (specific platforms)
    r"\binteractive brokers\b",
    r"\bcharles schwab\b",
    r"\btd ameritrade\b",
    r"\brobinhood\b",
    r"\bwebull\b",
    r"\bfidelity\b",
    r"\bvanguard\b",
    r"\be[*\s\-]?trade\b",
    r"\betoro\b",
    r"\bplus500\b",
    r"\bsaxo bank\b",
    r"\bibkr\b",
    # Crypto exchanges & platforms (heavily restricted under Financial SAC)
    r"\bcoinbase\b",
    r"\bbinance\b",
    r"\bbybit\b",
    r"\bkraken\b",
    r"\bgemini\b",
    r"\bkucoin\b",
    r"\bcrypto\.com\b",
    # Trading software / data terminals
    r"\bmetatrader\b",
    r"\bmetaquotes\b",
    r"\bninjatrader\b",
    r"\bthinkorswim\b",
    r"\btradingview\b",
    r"\bbloomberg\b",
    r"\brefinitiv\b",
    # Financial publications
    r"\binvesting\.com\b",
    r"\bcnbc\b",
    r"\bfinancial times\b",
    r"\bthe economist\b",
    r"\bwall street journal\b",
    r"\breuters\b",
    r"\bmorningstar\b",
    r"\bseeking alpha\b",
    # Instrument-specific (Meta strips these under Financial SAC)
    r"\boptions trading\b",
    r"\bmargin trading\b",
    r"\bderivatives\b",
    r"\balgorithmic trading\b",
    r"\bquant trading\b",
    r"\bquantitative trading\b",
    r"\bautomated trading\b",
    r"\btrading bots?\b",
    r"\bcopy trading\b",
    r"\btrading signals?\b",
    r"\bbinary options?\b",
    r"\bfutures trading\b",
    r"\betf trading\b",
    # Crypto-instrument interests (varies by region — strip under Financial)
    r"\bcryptocurrency\b",
    r"\bbitcoin\b",
    r"\bethereum\b",
    r"\bblockchain\b",
    r"\bnft\b",
    r"\bdefi\b",
    r"\bweb3\b",
]

# HEC bans almost all detailed targeting beyond broad categories. Lifestyle
# interests survive only at the top level (Investing, Stock market, Personal
# finance). Brand interests are stripped harder than under Financial.
_HEC_BLOCKED_PATTERNS = list(_FINANCIAL_BLOCKED_PATTERNS) + [
    # Income / wealth / education-for-finance demographics (when surfaced as
    # interest names — defensive, also caught by demographics strip below)
    r"\bhigh income\b",
    r"\bnet worth\b",
    r"\baffluent\b",
]

# Generic ".com" detector — almost any interest name ending in a domain is
# a brand reference and gets stripped under SAC.
_DOMAIN_RE = re.compile(r"\b[\w\-]+\.(com|net|io|co|app|exchange)\b", re.IGNORECASE)


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


_FIN_RE = _compile(_FINANCIAL_BLOCKED_PATTERNS)
_HEC_RE = _compile(_HEC_BLOCKED_PATTERNS)


def _interest_blocked(name: str, category: str) -> str | None:
    """Return the matching pattern if the interest is blocked under the given
    SAC, else None. ``name`` is the human-readable Meta interest name."""
    if not name:
        return None
    if _DOMAIN_RE.search(name):
        return f"domain-pattern: {_DOMAIN_RE.search(name).group(0)}"
    rules = _HEC_RE if category in _HEC else _FIN_RE
    for pat in rules:
        if pat.search(name):
            return pat.pattern
    return None


# ── Geo policy ───────────────────────────────────────────────────────────────


def _normalise_geo(geo: dict, category: str, removed: list[str]) -> dict:
    """Apply SAC geo restrictions.

    HEC: ZIPs stripped, regions stripped if too narrow, cities forced to
    minimum 25 km radius. Financial: same but cities can keep their radius.
    """
    if not isinstance(geo, dict):
        return geo

    # ZIP codes are NEVER allowed under any SAC.
    if geo.get("zips"):
        removed.append(f"geo.zips ({len(geo['zips'])} stripped)")
        geo.pop("zips", None)

    if category in _HEC:
        # Regions are too narrow for HEC.
        if geo.get("regions"):
            removed.append(f"geo.regions ({len(geo['regions'])} stripped)")
            geo.pop("regions", None)
        # Cities: enforce 25 km minimum radius. Meta's distance_unit is
        # usually "kilometer" but could be "mile" (15 mi == 25 km).
        cities = geo.get("cities") or []
        for c in cities:
            if not isinstance(c, dict):
                continue
            unit = (c.get("distance_unit") or "kilometer").lower()
            min_radius = 15 if unit.startswith("mile") else 25
            r = c.get("radius")
            if not r or r < min_radius:
                c["radius"] = min_radius
                c["distance_unit"] = unit
                removed.append(f"geo.cities[{c.get('name', '?')}] radius -> {min_radius}{unit[:2]}")

    return geo


# ── Demographics / behaviors / income strip ──────────────────────────────────


def _strip_specs_in_place(
    spec: dict, category: str, removed: list[str], path: str
) -> dict | None:
    """Strip disallowed taxonomy entries inside one flexible_spec/exclusions
    object. Returns the cleaned spec or None if nothing useful remains."""
    if not isinstance(spec, dict):
        return spec

    # Demographics (income, wealth, education-for-finance, relationship,
    # generations) — banned under all SAC.
    if "demographics" in spec:
        removed.append(f"{path}.demographics ({len(spec['demographics'])} stripped)")
        spec.pop("demographics", None)

    # Behaviors — purchase/financial behaviors banned. Some general behaviors
    # OK, but distinguishing requires Meta-side metadata we don't have. Strip
    # all behaviors under HEC; allow under Financial only if there's no
    # finance-related keyword.
    if "behaviors" in spec:
        if category in _HEC:
            removed.append(f"{path}.behaviors ({len(spec['behaviors'])} stripped)")
            spec.pop("behaviors", None)
        else:
            kept = []
            for b in spec["behaviors"]:
                name = (b.get("name") or "").lower() if isinstance(b, dict) else ""
                if _interest_blocked(name, category):
                    removed.append(f"{path}.behaviors.{name}")
                else:
                    kept.append(b)
            if kept:
                spec["behaviors"] = kept
            else:
                spec.pop("behaviors", None)

    # Interests — strip brand/instrument names per category blocklist.
    if "interests" in spec:
        kept = []
        for i in spec["interests"]:
            if not isinstance(i, dict):
                continue
            name = i.get("name") or ""
            why = _interest_blocked(name, category)
            if why:
                removed.append(f"{path}.interests.'{name}' ({why})")
            else:
                kept.append(i)
        if kept:
            spec["interests"] = kept
        else:
            spec.pop("interests", None)

    # Life events — stripped under HEC.
    if "life_events" in spec and category in _HEC:
        removed.append(f"{path}.life_events ({len(spec['life_events'])} stripped)")
        spec.pop("life_events", None)

    # Income (Meta sometimes surfaces this as a separate taxonomy key).
    if "income" in spec:
        removed.append(f"{path}.income ({len(spec['income'])} stripped)")
        spec.pop("income", None)

    return spec if any(spec.get(k) for k in spec) else None


def _strip_lookalikes(spec: dict, removed: list[str], path: str) -> None:
    """Remove Lookalike audiences — never allowed under SAC. Standard custom
    audiences are fine; Special Ad Audiences must be used in place of LALs."""
    for key in ("custom_audiences",):
        items = spec.get(key) or []
        kept = []
        for a in items:
            # Meta encodes lookalikes as audiences with subtype "LOOKALIKE".
            # We don't always have subtype here — so as a heuristic, the
            # audience name often contains "lookalike" / "lal".
            name = (a.get("name") or "").lower() if isinstance(a, dict) else ""
            subtype = (a.get("subtype") or "").upper() if isinstance(a, dict) else ""
            if subtype == "LOOKALIKE" or "lookalike" in name or " lal " in f" {name} ":
                removed.append(f"{path}.{key}.'{name or a}' (lookalike not allowed under SAC)")
                continue
            kept.append(a)
        if kept:
            spec[key] = kept
        elif key in spec:
            spec.pop(key, None)


# ── Public API ───────────────────────────────────────────────────────────────


def derive_sac_countries(targeting_obj: dict) -> list[str]:
    """Pull the list of countries this ad will target. Used for the
    campaign-level ``special_ad_category_country`` field. Meta requires
    this list to be a SUPERSET of the geo_locations countries."""
    if not isinstance(targeting_obj, dict):
        return []
    geo = targeting_obj.get("geo_locations") or {}
    countries = list(geo.get("countries") or [])
    # Derive from cities/regions if no top-level countries set.
    if not countries:
        for c in (geo.get("cities") or []):
            cc = c.get("country") if isinstance(c, dict) else None
            if cc and cc not in countries:
                countries.append(cc)
        for r in (geo.get("regions") or []):
            cc = r.get("country") if isinstance(r, dict) else None
            if cc and cc not in countries:
                countries.append(cc)
    return [c.upper() for c in countries if isinstance(c, str)]


def apply_sac_policy(
    targeting_obj: dict,
    special_ad_categories: list[str],
) -> tuple[dict, list[str]]:
    """Sanitise a targeting payload for the given SAC list.

    Returns ``(cleaned_targeting, removed_log)``. The cleaned targeting can be
    POSTed to Meta with a much higher chance of acceptance. ``removed_log``
    is a human-readable list of every stripped/modified field so callers can
    show the user what changed and audit the decision later.

    The function is idempotent and side-effect free on the input (operates on
    a deep copy).
    """
    if not special_ad_categories or not isinstance(targeting_obj, dict):
        return targeting_obj, []

    # Pick the strictest applicable category for stripping (Mar 2026 enforces
    # the strictest set when multiple are declared).
    category = "FINANCIAL_PRODUCTS_SERVICES"
    for cat in special_ad_categories:
        if cat in _HEC:
            category = cat
            break
    if any(c in _AUTH for c in special_ad_categories):
        log.warning(
            "SAC policy: %s requires advertiser authorization — stripping is "
            "best-effort, the ad will likely still need manual Meta verification.",
            special_ad_categories,
        )

    import copy
    t = copy.deepcopy(targeting_obj)
    removed: list[str] = []

    # 1. Age — Meta error #2909037 proves Financial Products *also* rejects
    # ANY custom age selection (even age_min=18, age_max=65 explicitly set
    # is treated as "custom" and rejected). The only accepted state is the
    # fields being absent entirely — Meta then applies its forced default
    # of 18–65+. So under any SAC we strip both age_min and age_max.
    if "age_min" in t:
        removed.append(f"age_min ({t['age_min']}) — SAC forces default 18+")
        t.pop("age_min", None)
    if "age_max" in t:
        removed.append(f"age_max ({t['age_max']}) — SAC forces default 65+")
        t.pop("age_max", None)

    # 2. Genders — same story as age. Meta blocks any explicit gender
    # narrowing under both HEC and Financial categories. Strip entirely.
    if "genders" in t:
        removed.append(f"genders ({t['genders']}) — SAC forces all genders")
        t.pop("genders", None)

    # 3. Other narrow demographic fields — strip under HEC.
    if category in _HEC:
        for k in ("relationship_statuses", "education_statuses", "interested_in",
                  "family_statuses", "income", "user_adclusters", "generations"):
            if k in t:
                removed.append(f"{k}")
                t.pop(k, None)

    # 4. Geo restrictions.
    if "geo_locations" in t:
        t["geo_locations"] = _normalise_geo(t["geo_locations"], category, removed)

    # 5. Top-level interests/behaviors/demographics (legacy field shape).
    cleaned = _strip_specs_in_place(t, category, removed, path="targeting")
    if cleaned is None:
        # _strip_specs_in_place returns None if every taxonomy was stripped;
        # but the top-level dict has more than just taxonomies, so keep it.
        pass

    # 6. flexible_spec[*] — Meta's preferred shape.
    if isinstance(t.get("flexible_spec"), list):
        kept_specs = []
        for idx, spec in enumerate(t["flexible_spec"]):
            cleaned_spec = _strip_specs_in_place(
                spec, category, removed, path=f"flexible_spec[{idx}]"
            )
            if cleaned_spec:
                kept_specs.append(cleaned_spec)
        if kept_specs:
            t["flexible_spec"] = kept_specs
        else:
            removed.append("flexible_spec (entire array empty after strip)")
            t.pop("flexible_spec", None)

    # 7. Exclusions — Mar 2026 update: removed entirely from SAC campaigns.
    if "exclusions" in t:
        removed.append("exclusions (Mar 2026: detailed exclusions banned under SAC)")
        t.pop("exclusions", None)

    # 8. Lookalike audiences — banned under all SAC. Special Ad Audiences only.
    _strip_lookalikes(t, removed, "targeting")
    if isinstance(t.get("flexible_spec"), list):
        for idx, spec in enumerate(t["flexible_spec"]):
            _strip_lookalikes(spec, removed, f"flexible_spec[{idx}]")

    # 9. Force Advantage+ Audience expansion — Meta forces this server-side
    # for SAC anyway, so set it explicitly to avoid a silent mismatch with
    # what we have stored.
    automation = t.get("targeting_automation") or {}
    if automation.get("advantage_audience") != 1:
        automation["advantage_audience"] = 1
        removed.append("targeting_automation.advantage_audience -> 1 (forced under SAC)")
    t["targeting_automation"] = automation

    if removed:
        log.info(
            "SAC policy applied (%s): %d field(s) sanitised — %s",
            category, len(removed), "; ".join(removed[:8]) + (" ..." if len(removed) > 8 else ""),
        )
    return t, removed


def strip_all_detailed_targeting(targeting_obj: dict) -> tuple[dict, int]:
    """Last-resort fallback used by the retry loop when Meta still rejects
    targeting after policy stripping. Removes every detailed-targeting
    interest/behavior/demographic/life_event from both ``flexible_spec`` and
    the legacy top-level keys, leaving geo + age + Advantage+ to fill the
    audience.

    Returns ``(cleaned_targeting, count_removed)``.
    """
    if not isinstance(targeting_obj, dict):
        return targeting_obj, 0
    import copy
    t = copy.deepcopy(targeting_obj)
    count = 0
    for k in ("interests", "behaviors", "demographics", "life_events", "income"):
        if k in t:
            count += len(t[k]) if isinstance(t[k], list) else 1
            t.pop(k, None)
    if isinstance(t.get("flexible_spec"), list):
        for spec in t["flexible_spec"]:
            for k in ("interests", "behaviors", "demographics", "life_events", "income"):
                if k in spec:
                    count += len(spec[k]) if isinstance(spec[k], list) else 1
                    spec.pop(k, None)
        # Drop empty specs.
        t["flexible_spec"] = [s for s in t["flexible_spec"] if any(s.values())]
        if not t["flexible_spec"]:
            t.pop("flexible_spec", None)
    # Force Advantage+ on so Meta can fill the audience.
    automation = t.get("targeting_automation") or {}
    automation["advantage_audience"] = 1
    t["targeting_automation"] = automation
    return t, count
