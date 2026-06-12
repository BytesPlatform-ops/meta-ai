"""
Hiring / Jobs CRUD routes — 1-Click Recruitment Ads.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import httpx as _httpx

from ...api.deps import get_current_user_id, get_workspace_id
from ...core.config import get_settings

router = APIRouter(prefix="/hiring", tags=["Hiring"])


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


class JobCreate(BaseModel):
    job_title: str
    department: str | None = None
    company_name: str | None = None
    company_logo_url: str | None = None
    work_mode: str = "onsite"                   # onsite | remote | hybrid
    location: str | None = None
    employment_type: str = "full_time"           # full_time | part_time | contract | internship | freelance
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = "PKR"
    salary_period: str = "month"                 # month | year | hour | project
    perks: str | None = None
    experience_level: str = "entry"              # entry | mid | senior | lead | executive
    experience_years_min: int = 0
    experience_years_max: int | None = None
    education_level: str | None = None
    skills: list[str] = []
    target_candidate_profile: str | None = None
    requirements: str | None = None
    responsibilities: str | None = None
    application_url: str | None = None
    application_email: str | None = None
    target_country: str = "PK"
    target_cities: list[dict] | None = None
    status: str = "open"
    tags: list[str] = []


class JobUpdate(JobCreate):
    is_active: bool = True


# ── List Jobs ─────────────────────────────────────────────────────────────────

@router.get("/")
async def list_jobs(
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """List all active jobs for the current workspace."""
    url = _postgrest_url("jobs")
    params = "is_active=eq.true&order=created_at.desc"
    if workspace_id:
        params += f"&workspace_id=eq.{workspace_id}"
    else:
        params += f"&user_id=eq.{user_id}"

    resp = _httpx.get(f"{url}?{params}", headers=_postgrest_headers(), timeout=10)
    return resp.json() if resp.status_code == 200 else []


# ── Create Job ────────────────────────────────────────────────────────────────

@router.post("/")
async def create_job(
    job: JobCreate,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Create a new job posting."""
    data = job.model_dump()
    data["user_id"] = user_id
    if workspace_id:
        data["workspace_id"] = workspace_id

    resp = _httpx.post(
        _postgrest_url("jobs"),
        headers=_postgrest_headers(),
        json=data,
        timeout=10,
    )
    if resp.status_code in (200, 201) and resp.json():
        return resp.json()[0]
    raise HTTPException(500, f"Failed to create job: {resp.text}")


# ── Get Single Job ────────────────────────────────────────────────────────────

@router.get("/{job_id}")
async def get_job(
    job_id: str,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Get a single job by ID."""
    url = _postgrest_url("jobs")
    params = f"id=eq.{job_id}"
    if workspace_id:
        params += f"&workspace_id=eq.{workspace_id}"
    else:
        params += f"&user_id=eq.{user_id}"

    resp = _httpx.get(f"{url}?{params}", headers=_postgrest_headers(), timeout=10)
    data = resp.json() if resp.status_code == 200 else []
    if not data:
        raise HTTPException(404, "Job not found")
    return data[0]


# ── Update Job ────────────────────────────────────────────────────────────────

@router.patch("/{job_id}")
async def update_job(
    job_id: str,
    job: JobUpdate,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Update an existing job posting."""
    data = job.model_dump(exclude_unset=True)
    url = _postgrest_url("jobs")
    params = f"id=eq.{job_id}"
    if workspace_id:
        params += f"&workspace_id=eq.{workspace_id}"
    else:
        params += f"&user_id=eq.{user_id}"

    resp = _httpx.patch(
        f"{url}?{params}",
        headers=_postgrest_headers(),
        json=data,
        timeout=10,
    )
    if resp.status_code == 200 and resp.json():
        return resp.json()[0]
    raise HTTPException(500, f"Failed to update job: {resp.text}")


# ── Delete Job (soft) ─────────────────────────────────────────────────────────

@router.delete("/{job_id}")
async def delete_job(
    job_id: str,
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
    """Soft-delete a job posting."""
    url = _postgrest_url("jobs")
    params = f"id=eq.{job_id}"
    if workspace_id:
        params += f"&workspace_id=eq.{workspace_id}"
    else:
        params += f"&user_id=eq.{user_id}"

    resp = _httpx.patch(
        f"{url}?{params}",
        headers=_postgrest_headers(),
        json={"is_active": False},
        timeout=10,
    )
    return {"deleted": True}
