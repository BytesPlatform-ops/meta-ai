-- ============================================================
-- Local Supabase Bootstrap
-- Sets up the roles, schemas, and extensions that
-- GoTrue (auth) and PostgREST (REST API) require.
--
-- This mirrors what supabase/postgres does internally,
-- keeping it transparent so you can migrate to Supabase Cloud
-- by simply swapping URL + keys.
-- ============================================================

-- ── Extensions ───────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── Schemas ──────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS extensions;

-- ── Roles (PostgREST) ────────────────────────────────────────
-- anon: unauthenticated requests
-- authenticated: logged-in users
-- service_role: backend/admin access — bypasses RLS
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN NOINHERIT BYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticator') THEN
        CREATE ROLE authenticator LOGIN PASSWORD 'postgres' NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'supabase_auth_admin') THEN
        CREATE ROLE supabase_auth_admin LOGIN PASSWORD 'postgres' CREATEROLE;
    END IF;
END
$$;

-- authenticator can switch to any of these roles
GRANT anon              TO authenticator;
GRANT authenticated     TO authenticator;
GRANT service_role      TO authenticator;

-- ── Schema Permissions ───────────────────────────────────────
-- public schema: all API roles can read/write
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON FUNCTIONS TO anon, authenticated, service_role;

-- auth schema: owned by supabase_auth_admin (GoTrue)
GRANT ALL ON SCHEMA auth TO supabase_auth_admin;
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_auth_admin IN SCHEMA auth
    GRANT ALL ON TABLES TO supabase_auth_admin;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_auth_admin IN SCHEMA auth
    GRANT ALL ON SEQUENCES TO supabase_auth_admin;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_auth_admin IN SCHEMA auth
    GRANT ALL ON FUNCTIONS TO supabase_auth_admin;

-- Let API roles read auth schema tables (needed for auth.uid() etc.)
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_auth_admin IN SCHEMA auth
    GRANT SELECT ON TABLES TO anon, authenticated, service_role;

-- ── Grant auth_admin full access on public schema too ────────
-- Needed for the trigger that creates public.users rows
GRANT ALL ON SCHEMA public TO supabase_auth_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES TO supabase_auth_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON SEQUENCES TO supabase_auth_admin;

-- Set search path for auth admin
ALTER ROLE supabase_auth_admin SET search_path = auth, public, extensions;

-- ── Database-level grants ────────────────────────────────────
GRANT CONNECT ON DATABASE postgres TO anon, authenticated, service_role, supabase_auth_admin;
