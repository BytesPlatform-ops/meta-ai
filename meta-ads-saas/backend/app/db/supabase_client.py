"""
Singleton Supabase client using the service-role key.
Use this only in backend services — never expose the service role key to the client.
"""
from supabase import create_client, Client
from ..core.config import get_settings
from functools import lru_cache

settings = get_settings()


@lru_cache
def get_supabase() -> Client:
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
