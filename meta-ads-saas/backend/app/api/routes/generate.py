"""
Content generation routes.

POST /api/v1/generate/drafts  → generate AI content drafts for the current user
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ...api.deps import get_current_user_id
from ...services.content_generator import generate_drafts

router = APIRouter(prefix="/generate", tags=["AI Content Generation"])


class GenerateDraftsBody(BaseModel):
    user_guidance: str | None = None
    conversion_event: str | None = None
    destination_type: str | None = None
    whatsapp_number: str | None = None
    selected_messaging_apps: list[str] | None = None
    call_phone_number: str | None = None


@router.post("/drafts")
async def create_drafts(
    body: GenerateDraftsBody | None = None,
    count: int = Query(default=3, ge=1, le=10),
    product_id: str | None = Query(default=None),
    ab_test: bool = Query(default=False),
    user_id: str = Depends(get_current_user_id),
):
    """Generate AI content drafts based on user preferences."""
    try:
        drafts = await generate_drafts(
            user_id=user_id,
            count=count,
            product_id=product_id,
            ab_test=ab_test,
            user_guidance=body.user_guidance if body else None,
            conversion_event=body.conversion_event if body else None,
            destination_type=body.destination_type if body else None,
            whatsapp_number=body.whatsapp_number if body else None,
            selected_messaging_apps=body.selected_messaging_apps if body else None,
            call_phone_number=body.call_phone_number if body else None,
        )
        return {"generated": len(drafts), "drafts": drafts}
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
