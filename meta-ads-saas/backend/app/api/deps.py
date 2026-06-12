"""
FastAPI dependency injection — auth, DB client, etc.
"""
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from ..core.security import get_user_id_from_token

# auto_error=False so we return 401 (not FastAPI's default 403)
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    """Validate the Supabase JWT and return the user's UUID."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — please sign in first.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return get_user_id_from_token(credentials.credentials)


def get_workspace_id(
    user_id: str = Depends(get_current_user_id),
    x_workspace_id: str | None = Header(None),
) -> str:
    """
    Resolve the active workspace for this request.

    Priority:
      1. X-Workspace-Id header (explicit workspace switch)
      2. User's first workspace (default fallback)

    Always verifies the workspace belongs to the authenticated user.
    """
    from ..db.supabase_client import get_supabase
    supabase = get_supabase()

    if x_workspace_id:
        # Verify this workspace belongs to the user
        result = (
            supabase.table("workspaces")
            .select("id")
            .eq("id", x_workspace_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found or does not belong to you.",
            )
        return x_workspace_id

    # Fallback: user's first (default) workspace
    result = (
        supabase.table("workspaces")
        .select("id")
        .eq("user_id", user_id)
        .order("created_at")
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No workspace found. Please contact support.",
        )
    return result.data[0]["id"]
