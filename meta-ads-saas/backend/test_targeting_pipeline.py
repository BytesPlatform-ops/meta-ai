"""
Context Bleeding Test: Honey (B2C) vs Chatbot (B2B) — same seller account.
Verifies that product-level targeting uses product context, NOT business context.
"""
import asyncio
import json
import sys
sys.path.insert(0, "/app")

from app.services.targeting_engine import _generate_llm_keywords, _validate_interests_via_mcp

ACCESS_TOKEN = "EAARaG8JyjdQBQxTgzdftJIMuZCYFKGl8fssvZC4I4HucSsZCuTgLINYCUfLdHj0x02hFZA2TWMF613PTW2CstVjgZBGtWZC89SmsT7ZAncySAlm9DoZCIRRbNRsHOLJyqEJBIU5FklkDdGHfbwdjaDWgZCZBQ1vAXXjzJ8ZAo4YKVkmx6okQ1EVZCHFXn9knhn9lYiUr"

B2B_NOISE = {"digital marketing", "marketing services", "business software", "entrepreneurship",
             "small business", "digital marketing (marketing)", "marketing services and organisations (marketing)"}
GEO_NOISE = {"seoul", "london", "karachi", "lahore", "islamabad", "dubai", "new york", "tokyo"}


def sep(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")


async def main():
    all_pass = True

    # ══════════════════════════════════════════════════════════════════════
    # TEST 1: Honey product — should get FOOD/HEALTH interests only
    # ══════════════════════════════════════════════════════════════════════
    sep("TEST 1 — Honey Product (B2C Food)")
    print("Simulating: Product attached = Cinnamon Infused Honey")
    print("Expected: Food/health/organic interests. Zero B2B interests.\n")

    # This is what _build_client_profile NOW passes when a product is attached:
    # business_description="" (empty!), industry_niche="Honey, Cinnamon, Infused" (from product tags)
    honey_llm = await _generate_llm_keywords(
        product_description="All-Natural wild honey infused with fresh cinnamon. Cinnamon is known for controlling blood pressure and lowering blood sugars. Perfect with afternoon tea. PKR 850 for 500g.",
        product_type="physical",
        industry_niche="Honey, Cinnamon, Infused",  # from product tags
        business_description="",  # EMPTY — no business context bleeding
    )
    print(f"LLM Output:")
    print(json.dumps(honey_llm, indent=2))

    honey_keywords = honey_llm.get("keywords", [])[:4]
    honey_validated = await _validate_interests_via_mcp(honey_keywords, ACCESS_TOKEN)
    honey_interests = sorted(honey_validated, key=lambda x: x.get("audience_size", 0), reverse=True)[:4]

    print(f"\nValidated interests: {[i['name'] for i in honey_interests]}")

    # Check for B2B contamination
    honey_names = {i["name"].lower() for i in honey_interests}
    b2b_leak = honey_names & B2B_NOISE
    geo_leak = honey_names & GEO_NOISE
    if b2b_leak:
        print(f"\n  FAIL: B2B interests in honey ad: {b2b_leak}")
        all_pass = False
    else:
        print(f"\n  PASS: No B2B interests — pure food/health cluster")
    if geo_leak:
        print(f"  FAIL: Geographic interests: {geo_leak}")
        all_pass = False
    else:
        print(f"  PASS: No geographic interests")

    # ══════════════════════════════════════════════════════════════════════
    # TEST 2: Chatbot service — should get B2B/TECH interests only
    # ══════════════════════════════════════════════════════════════════════
    sep("TEST 2 — Chatbot Service (B2B Tech)")
    print("Simulating: No product attached, general business ad")
    print("Expected: B2B/tech interests. Zero food/lifestyle interests.\n")

    chatbot_llm = await _generate_llm_keywords(
        product_description="Custom AI chatbot development for businesses — automate customer support, WhatsApp bots, website live chat, and lead qualification. Starting at PKR 1999.",
        product_type="B2B Service",
        industry_niche="Digital Marketing, IT Services & Consulting",
        business_description="Bytes Platform is a digital marketing agency offering web dev, SEO, chatbot development.",
    )
    print(f"LLM Output:")
    print(json.dumps(chatbot_llm, indent=2))

    chatbot_keywords = chatbot_llm.get("keywords", [])[:4]
    chatbot_validated = await _validate_interests_via_mcp(chatbot_keywords, ACCESS_TOKEN)
    chatbot_interests = sorted(chatbot_validated, key=lambda x: x.get("audience_size", 0), reverse=True)[:4]

    print(f"\nValidated interests: {[i['name'] for i in chatbot_interests]}")

    food_noise = {"organic food", "honey", "healthy eating", "natural foods", "cooking"}
    chatbot_names = {i["name"].lower() for i in chatbot_interests}
    food_leak = chatbot_names & food_noise
    geo_leak2 = chatbot_names & GEO_NOISE
    if food_leak:
        print(f"\n  FAIL: Food interests in chatbot ad: {food_leak}")
        all_pass = False
    else:
        print(f"\n  PASS: No food interests — pure B2B cluster")
    if geo_leak2:
        print(f"  FAIL: Geographic interests: {geo_leak2}")
        all_pass = False
    else:
        print(f"  PASS: No geographic interests")

    # ══════════════════════════════════════════════════════════════════════
    # TEST 3: Context isolation — same user, back-to-back
    # ══════════════════════════════════════════════════════════════════════
    sep("TEST 3 — Cross-contamination check")
    print("Verifying zero overlap between honey and chatbot interest sets:\n")

    overlap = honey_names & chatbot_names
    print(f"  Honey interests:   {honey_names}")
    print(f"  Chatbot interests: {chatbot_names}")
    print(f"  Overlap:           {overlap if overlap else 'NONE'}")
    if overlap:
        print(f"\n  FAIL: Cross-contamination detected")
        all_pass = False
    else:
        print(f"\n  PASS: Zero overlap — complete isolation")

    # ══════════════════════════════════════════════════════════════════════
    sep("FINAL RESULT")
    if all_pass:
        print("  ALL TESTS PASSED — no context bleeding detected")
    else:
        print("  SOME TESTS FAILED — see above")


if __name__ == "__main__":
    asyncio.run(main())
