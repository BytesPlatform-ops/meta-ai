"""
Audience management routes — niche-scoped Custom Audiences, Lookalike Audiences, and data sync.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from ...api.deps import get_current_user_id
from ...services.audience_sync import sync_audience_for_niche, query_niche_customers_count
from ...db.supabase_client import get_supabase

router = APIRouter(prefix="/meta", tags=["Audiences"])


class CustomerRecord(BaseModel):
    email: str | None = None
    phone: str | None = None
    niche: str | None = None
    product_id: str | None = None


class CustomerBulkUpload(BaseModel):
    customers: list[CustomerRecord]
    niche: str | None = None       # default niche for all records
    product_id: str | None = None  # default product for all records


@router.post("/customers")
async def add_customers(
    body: CustomerBulkUpload,
    user_id: str = Depends(get_current_user_id),
):
    """Add niche-tagged customer records (email/phone) for audience targeting."""
    supabase = get_supabase()

    records = []
    for c in body.customers:
        if c.email or c.phone:
            records.append({
                "user_id": user_id,
                "email": c.email,
                "phone": c.phone,
                "niche": c.niche or body.niche,
                "product_id": c.product_id or body.product_id,
            })

    if not records:
        raise HTTPException(status_code=400, detail="No valid customer records (need email or phone)")

    try:
        result = supabase.table("customers").insert(records).execute()
        return {"inserted": len(result.data), "total_records": len(records)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to insert customers: {e}")


@router.post("/sync-audiences")
async def sync_audiences_endpoint(
    user_id: str = Depends(get_current_user_id),
    niche: str = Query(..., description="Niche/product category to sync (e.g., 'Chatbots', 'Honey')"),
    product_id: str | None = Query(None, description="Optional product ID for exact matching"),
):
    """
    Sync niche-scoped customer data to Meta Custom Audiences + generate 1% LAL.
    Only customers tagged with this niche are included — prevents cross-niche contamination.
    """
    result = await sync_audience_for_niche(user_id, niche, product_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.get("/audience-check")
async def check_audience_data(
    niche: str = Query(..., description="Niche to check customer data for"),
    product_id: str | None = Query(None),
    user_id: str = Depends(get_current_user_id),
):
    """
    Check how many customers exist for a niche — used to preview routing decision.
    Returns count and which route (cold vs data-rich) the AI would take.
    """
    count = query_niche_customers_count(user_id, niche, product_id)
    route = "data_rich" if count >= 100 else "cold"
    return {
        "niche": niche,
        "customer_count": count,
        "route": route,
        "explanation": (
            f"DATA-RICH: {count} customers found — will use Custom Audience + 1% LAL, no interest targeting"
            if route == "data_rich"
            else f"COLD START: only {count} customers — will use API-validated interest targeting (need 100+ for LAL)"
        ),
    }
