import asyncio, sys
sys.path.insert(0, "/app")
async def test():
    from app.services.ad_executor import execute_approved_ad
    from app.db.supabase_client import get_supabase
    supabase = get_supabase()
    draft_id = "3dc1410f-c952-4f70-b3ec-88972258d777"
    supabase.table("content_drafts").update({"status": "approved"}).eq("id", draft_id).execute()
    result = await execute_approved_ad(draft_id)
    print(f"Result: {result}")
    print("SUCCESS" if result.get("ad_id") else "PARTIAL — check MCP logs")
asyncio.run(test())
