"""
Content Strategy routes.

POST  /api/v1/strategy/generate   → trigger AI strategy pipeline
GET   /api/v1/strategy            → get latest strategy
PATCH /api/v1/strategy/{id}       → approve a strategy
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from ...api.deps import get_current_user_id
from ...db.supabase_client import get_supabase
from ...services.strategy_engine import generate_content_strategy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategy", tags=["Content Strategy"])


@router.post("/generate")
async def trigger_strategy_generation(
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
):
    """Kick off the autonomous market research + strategy pipeline."""

    async def _run(uid: str):
        try:
            await generate_content_strategy(uid)
        except Exception as e:
            logger.error("Strategy generation failed for user %s: %s", uid, e)

    background_tasks.add_task(_run, user_id)
    return {
        "status": "generating",
        "message": "Strategy generation started. Check back in a moment.",
    }


@router.get("")
async def get_latest_strategy(user_id: str = Depends(get_current_user_id)):
    """Return the most recent content strategy for this user."""
    supabase = get_supabase()
    result = (
        supabase.table("content_strategies")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not result.data:
        return {"strategy": None}
    return {"strategy": result.data[0]}


@router.get("/history")
async def list_strategies(user_id: str = Depends(get_current_user_id)):
    """Return all strategies for this user, newest first."""
    supabase = get_supabase()
    result = (
        supabase.table("content_strategies")
        .select("id, niche, research_summary, status, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    return {"strategies": result.data or []}


@router.patch("/{strategy_id}")
async def approve_strategy(
    strategy_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Mark a strategy as APPROVED."""
    supabase = get_supabase()
    existing = (
        supabase.table("content_strategies")
        .select("id")
        .eq("id", strategy_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")

    supabase.table("content_strategies").update(
        {"status": "APPROVED"}
    ).eq("id", strategy_id).execute()

    return {"success": True, "status": "APPROVED"}
