"""
FastAPI dependency injection — auth, DB client, etc.
"""
from fastapi import Depends, HTTPException, status
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
