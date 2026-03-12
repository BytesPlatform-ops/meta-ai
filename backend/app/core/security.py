"""
JWT verification against Supabase Auth.

We use supabase.auth.get_user(token) instead of manually decoding the JWT.
This is the correct approach because:
  - Supabase user tokens are signed with the project JWT Secret, which is a
    separate value from the service role key or anon key.
  - get_user() also handles token revocation and expiry server-side.
"""
from fastapi import HTTPException, status
from ..db.supabase_client import get_supabase


def get_user_id_from_token(token: str) -> str:
    """
    Validate a Supabase user JWT by calling the Auth server.
    Returns the user UUID (sub claim) on success.
    Raises HTTP 401 on any failure.
    """
    supabase = get_supabase()
    try:
        response = supabase.auth.get_user(token)
        if response is None or response.user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        return str(response.user.id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token verification failed: {exc}",
        )
