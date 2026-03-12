"""
Standalone test script for the targeting engine.

Usage:
    META_ACCESS_TOKEN=your_token python test_validate_interests.py
"""
import asyncio
import os
import sys

# Allow imports from the app package
sys.path.insert(0, os.path.dirname(__file__))

from app.services.targeting_engine import (
    validate_meta_interests,
    generate_campaign_strategy,
    build_adset_payload,
)


async def main():
    token = os.environ.get("META_ACCESS_TOKEN", "")
    if not token:
        print("Set META_ACCESS_TOKEN env var to run this test.")
        sys.exit(1)

    # ── Test 1: validate_meta_interests ───────────────────────────────────────
    print("=" * 60)
    print("Test 1: validate_meta_interests")
    print("=" * 60)
    keywords = ["fitness", "organic food", "honey", "supplements"]
    results = await validate_meta_interests(keywords, token)
    for r in results:
        print(f"  {r['name']:30s}  id={r['id']}  audience={r['audience_size']:,}")
    if not results:
        print("  (no results — check token permissions)")

    # ── Test 2: generate_campaign_strategy ────────────────────────────────────
    print("\n" + "=" * 60)
    print("Test 2: generate_campaign_strategy")
    print("=" * 60)
    profile = {
        "product_description": "Pure organic honey and natural bee products for health-conscious consumers",
        "target_cities": ["Karachi", "Lahore"],
        "target_country": "PK",
    }
    strategy = await generate_campaign_strategy(profile, token)
    print(f"  Interests ({len(strategy['interests'])}):")
    for i in strategy["interests"]:
        print(f"    - {i['name']} (id={i['id']}, audience={i['audience_size']:,})")
    print(f"  Geo: {strategy['geo_locations']}")
    print(f"  Keywords used: {strategy['keywords_used']}")

    # ── Test 3: build_adset_payload ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Test 3: build_adset_payload")
    print("=" * 60)
    payload = build_adset_payload(strategy, daily_budget=30.0, campaign_id="fake_123")
    for k, v in payload.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
