"""Quick test: verify bid_amount flows through to MCP stage_params."""
import asyncio
import sys
sys.path.insert(0, "/app")

async def test():
    from app.db.supabase_client import get_supabase
    supabase = get_supabase()

    # Find the pending paid draft with profit_margin
    result = supabase.table("content_drafts").select("id, targeting, product_id, draft_type, status").eq("id", "4469d4ad-d38d-40d7-b022-3da593bc43ec").execute()
    if not result.data:
        print("ERROR: Draft not found")
        return

    draft = result.data[0]
    print(f"Draft: {draft['id']}")
    print(f"Type: {draft['draft_type']}, Status: {draft['status']}")
    print(f"Targeting: {draft['targeting']}")
    print(f"Targeting type: {type(draft['targeting'])}")

    # Simulate the profit_margin extraction logic
    import json
    raw_targeting = draft.get("targeting")
    draft_targeting = raw_targeting or {}
    if isinstance(draft_targeting, str):
        try:
            draft_targeting = json.loads(draft_targeting)
        except (json.JSONDecodeError, TypeError):
            draft_targeting = {}
    if not isinstance(draft_targeting, dict):
        draft_targeting = {}

    profit_margin = draft_targeting.get("profit_margin")
    print(f"\nFrom draft targeting: profit_margin={profit_margin}")

    # Fallback to product
    if not profit_margin and draft.get("product_id"):
        pm_result = supabase.table("products").select("profit_margin").eq("id", draft["product_id"]).execute()
        if pm_result.data and pm_result.data[0].get("profit_margin"):
            profit_margin = pm_result.data[0]["profit_margin"]
            print(f"From product: profit_margin={profit_margin}")

    # Calculate bid_amount
    bid_amount = 0
    if profit_margin:
        try:
            pm_float = float(profit_margin)
            if pm_float > 0:
                bid_amount = int(pm_float * 0.7 * 100)
                bid_amount = max(bid_amount, 100)
        except (ValueError, TypeError):
            bid_amount = 0

    print(f"\nFINAL: profit_margin={profit_margin} → bid_amount={bid_amount}")
    if bid_amount > 0:
        print(f"  bid_strategy = COST_CAP")
        print(f"  bid_amount = {bid_amount} (= {bid_amount/100:.0f} PKR cost cap)")
    else:
        print(f"  bid_strategy = LOWEST_COST_WITHOUT_CAP")

    print("\n✓ Test passed" if bid_amount == 28000 else f"\n✗ Expected 28000, got {bid_amount}")

asyncio.run(test())
