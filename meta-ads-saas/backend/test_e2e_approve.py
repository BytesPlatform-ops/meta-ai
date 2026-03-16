"""E2E test: approve a paid draft and watch bid_amount flow to MCP."""
import asyncio
import sys
sys.path.insert(0, "/app")

async def test():
    from app.services.ad_executor import execute_approved_ad
    draft_id = "4469d4ad-d38d-40d7-b022-3da593bc43ec"

    # Set status to approved first
    from app.db.supabase_client import get_supabase
    supabase = get_supabase()
    supabase.table("content_drafts").update({"status": "approved"}).eq("id", draft_id).execute()

    print(f"Executing paid ad for draft {draft_id}...")
    result = await execute_approved_ad(draft_id)
    print(f"Result: {result}")

asyncio.run(test())
