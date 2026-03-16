"""
Image upload routes — saves files locally and serves via FastAPI static mount.
Falls back to Supabase Storage if available, otherwise uses local filesystem.
"""
import uuid
import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from ...api.deps import get_current_user_id
from ...core.config import get_settings

router = APIRouter(prefix="/uploads", tags=["Uploads"])

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "avi", "mkv", "webm"}
ALLOWED_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS
MAX_IMAGE_SIZE = 0   # No limit
MAX_VIDEO_SIZE = 0   # No limit
MAX_SIZE = 0

# Local upload directory (inside backend container or host)
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))


@router.post("/product-image")
async def upload_product_image(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    """Upload a product image and return a public URL."""
    settings = get_settings()

    # Validate extension
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"File type '.{ext}' not allowed. Use: {', '.join(ALLOWED_EXTENSIONS)}")

    contents = await file.read()

    file_id = uuid.uuid4().hex
    filename = f"{file_id}.{ext}"

    # Try Supabase Storage first
    try:
        import httpx
        object_path = f"{user_id}/{filename}"
        bucket = "product-images"
        storage_url = f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/{bucket}/{object_path}"
        headers = {
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": file.content_type or "application/octet-stream",
        }
        resp = httpx.post(storage_url, headers=headers, content=contents, timeout=10)
        if resp.status_code in (200, 201):
            public_url = f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{bucket}/{object_path}"
            return {"url": public_url}
    except Exception:
        pass  # Fall through to local storage

    # Fallback: save locally and serve via /uploads/files/ static mount
    user_dir = UPLOAD_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    file_path = user_dir / filename
    file_path.write_bytes(contents)

    # Build public URL using the API base URL
    # The static mount at /uploads/files serves from UPLOAD_DIR
    public_url = f"/uploads/files/{user_id}/{filename}"
    return {"url": public_url}
