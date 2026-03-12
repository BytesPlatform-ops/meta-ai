"""
Product CRUD routes.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import httpx as _httpx

from ...api.deps import get_current_user_id
from ...db.supabase_client import get_supabase
from ...core.config import get_settings


router = APIRouter(prefix="/products", tags=["Products"])


def _postgrest_headers() -> dict:
    settings = get_settings()
    return {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _postgrest_url(table: str) -> str:
    settings = get_settings()
    return f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1/{table}"


class ProductCreate(BaseModel):
    name: str
    description: str | None = None
    image_url: str | None = None
    landing_url: str | None = None
    price: float | None = None
    currency: str = "USD"
    tags: list[str] = []
    target_audience: str | None = None
    product_type: str = "physical"  # physical | digital | saas | service
    product_options: list | None = None  # variation group rules (JSONB)
    profit_margin: float | None = None  # expected profit per sale (for Cost Cap)
    target_country: str | None = None
    pixel_id: str | None = None


class ProductUpdate(ProductCreate):
    is_active: bool = True


class VariantCreate(BaseModel):
    variant_name: str
    price: float
    currency: str = "USD"
    sku: str | None = None
    sort_order: int = 0


class VariantUpdate(BaseModel):
    variant_name: str | None = None
    price: float | None = None
    currency: str | None = None
    sku: str | None = None
    sort_order: int | None = None


@router.get("/")
async def list_products(user_id: str = Depends(get_current_user_id)):
    supabase = get_supabase()
    result = (
        supabase.table("products")
        .select("*")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .order("created_at", desc=True)
        .execute()
    )
    products = result.data or []
    # Attach variants to each product
    product_ids = [p["id"] for p in products]
    if product_ids:
        variants_result = (
            supabase.table("product_variants")
            .select("*")
            .in_("product_id", product_ids)
            .eq("is_active", True)
            .order("sort_order")
            .execute()
        )
        variants_by_product: dict[str, list] = {}
        for v in (variants_result.data or []):
            variants_by_product.setdefault(v["product_id"], []).append(v)
        for p in products:
            p["variants"] = variants_by_product.get(p["id"], [])
    else:
        for p in products:
            p["variants"] = []
    return products


@router.post("/", status_code=201)
async def create_product(body: ProductCreate, user_id: str = Depends(get_current_user_id)):
    data = {"user_id": user_id, **body.model_dump()}
    resp = _httpx.post(
        _postgrest_url("products"),
        headers=_postgrest_headers(),
        json=data,
        timeout=10,
    )
    if resp.status_code in (200, 201) and resp.json():
        return resp.json()[0]
    raise HTTPException(status_code=500, detail=f"Failed to create product: {resp.text}")


@router.get("/{product_id}")
async def get_product(product_id: str, user_id: str = Depends(get_current_user_id)):
    resp = _httpx.get(
        f"{_postgrest_url('products')}?id=eq.{product_id}&user_id=eq.{user_id}&is_active=eq.true",
        headers=_postgrest_headers(),
        timeout=10,
    )
    if resp.status_code == 200 and resp.json():
        return resp.json()[0]
    raise HTTPException(status_code=404, detail="Product not found")


@router.patch("/{product_id}")
async def update_product(
    product_id: str, body: ProductUpdate, user_id: str = Depends(get_current_user_id)
):
    resp = _httpx.patch(
        f"{_postgrest_url('products')}?id=eq.{product_id}&user_id=eq.{user_id}",
        headers={**_postgrest_headers(), "Prefer": "return=representation"},
        json=body.model_dump(exclude_unset=False),
        timeout=10,
    )
    if resp.status_code in (200, 201) and resp.json():
        return resp.json()[0]
    raise HTTPException(status_code=404, detail="Product not found")


@router.delete("/{product_id}", status_code=204)
async def delete_product(product_id: str, user_id: str = Depends(get_current_user_id)):
    _httpx.patch(
        f"{_postgrest_url('products')}?id=eq.{product_id}&user_id=eq.{user_id}",
        headers=_postgrest_headers(),
        json={"is_active": False},
        timeout=10,
    )


# ── Variant CRUD ─────────────────────────────────────────────────────────────

def _verify_product_ownership(product_id: str, user_id: str):
    """Verify the product belongs to this user."""
    supabase = get_supabase()
    result = (
        supabase.table("products")
        .select("id")
        .eq("id", product_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Product not found")


@router.get("/{product_id}/variants")
async def list_variants(product_id: str, user_id: str = Depends(get_current_user_id)):
    _verify_product_ownership(product_id, user_id)
    supabase = get_supabase()
    result = (
        supabase.table("product_variants")
        .select("*")
        .eq("product_id", product_id)
        .eq("is_active", True)
        .order("sort_order")
        .execute()
    )
    return result.data


@router.post("/{product_id}/variants", status_code=201)
async def create_variant(
    product_id: str, body: VariantCreate, user_id: str = Depends(get_current_user_id)
):
    _verify_product_ownership(product_id, user_id)
    data = {"product_id": product_id, **body.model_dump()}
    resp = _httpx.post(
        _postgrest_url("product_variants"),
        headers=_postgrest_headers(),
        json=data,
        timeout=10,
    )
    if resp.status_code in (200, 201) and resp.json():
        return resp.json()[0]
    raise HTTPException(status_code=500, detail=f"Failed to create variant: {resp.text}")


@router.patch("/{product_id}/variants/{variant_id}")
async def update_variant(
    product_id: str, variant_id: str, body: VariantUpdate,
    user_id: str = Depends(get_current_user_id),
):
    _verify_product_ownership(product_id, user_id)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    resp = _httpx.patch(
        f"{_postgrest_url('product_variants')}?id=eq.{variant_id}&product_id=eq.{product_id}",
        headers={**_postgrest_headers(), "Prefer": "return=representation"},
        json=updates,
        timeout=10,
    )
    if resp.status_code in (200, 201) and resp.json():
        return resp.json()[0]
    raise HTTPException(status_code=404, detail="Variant not found")


@router.delete("/{product_id}/variants/{variant_id}", status_code=204)
async def delete_variant(
    product_id: str, variant_id: str, user_id: str = Depends(get_current_user_id)
):
    _verify_product_ownership(product_id, user_id)
    _httpx.patch(
        f"{_postgrest_url('product_variants')}?id=eq.{variant_id}&product_id=eq.{product_id}",
        headers=_postgrest_headers(),
        json={"is_active": False},
        timeout=10,
    )
