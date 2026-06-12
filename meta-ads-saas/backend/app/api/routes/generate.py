"""
Content generation routes.

POST /api/v1/generate/drafts  → generate AI content drafts for the current user
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ...api.deps import get_current_user_id, get_workspace_id
from ...services.content_generator import generate_drafts

router = APIRouter(prefix="/generate", tags=["AI Content Generation"])


class HiringData(BaseModel):
    job_title: str
    target_candidate_profile: str
    salary_and_perks: str
    requirements: str | None = None
    responsibilities: str | None = None


class GenerateDraftsBody(BaseModel):
    user_guidance: str | None = None
    conversion_event: str | None = None
    destination_type: str | None = None
    whatsapp_number: str | None = None
    selected_messaging_apps: list[str] | None = None
    call_phone_number: str | None = None
    hiring_data: HiringData | None = None


@router.post("/drafts")
async def create_drafts(
    body: GenerateDraftsBody | None = None,
    count: int = Query(default=3, ge=1, le=10),
    product_id: str | None = Query(default=None),
    job_id: str | None = Query(default=None),
    ab_test: bool = Query(default=False),
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Generate AI content drafts based on user preferences."""
    # Auto-load hiring_data from job record if job_id provided
    hiring_data = body.hiring_data.model_dump() if body and body.hiring_data else None
    if job_id:
        from ...core.config import get_settings
        import httpx
        settings = get_settings()
        _headers = {
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        }
        _url = f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1/jobs?id=eq.{job_id}&select=*"
        resp = httpx.get(_url, headers=_headers, timeout=10)
        if resp.status_code == 200 and resp.json():
            job = resp.json()[0]
            salary_parts = []
            if job.get("salary_min"):
                salary_parts.append(str(job["salary_min"]))
            if job.get("salary_max"):
                salary_parts.append(str(job["salary_max"]))
            salary_str = " – ".join(salary_parts)
            if job.get("salary_currency"):
                salary_str = f"{job['salary_currency']} {salary_str}"
            if job.get("perks"):
                salary_str += f" + {job['perks']}"
            hiring_data = {
                "job_title": job["job_title"],
                "target_candidate_profile": job.get("target_candidate_profile") or f"{job.get('experience_level', 'entry')} level {job['job_title']}",
                "salary_and_perks": salary_str or "Competitive",
                "requirements": job.get("requirements"),
                "responsibilities": job.get("responsibilities"),
                "target_country": job.get("target_country", "PK"),
                "location": job.get("location"),
                "work_mode": job.get("work_mode"),
                "employment_type": job.get("employment_type"),
                "company_name": job.get("company_name"),
                "skills": job.get("skills", []),
                "experience_level": job.get("experience_level"),
                "education_level": job.get("education_level"),
            }

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
            hiring_data=hiring_data,
            job_id=job_id,
            workspace_id=workspace_id,
        )
        return {"generated": len(drafts), "drafts": drafts}
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
