-- ============================================================
-- Meta Ads SaaS — Initial Schema
-- Multi-tenant PostgreSQL schema for Supabase
-- ============================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- USERS
-- Mirrors Supabase auth.users — extended profile data
-- ============================================================
CREATE TABLE public.users (
    id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email       TEXT NOT NULL UNIQUE,
    full_name   TEXT,
    avatar_url  TEXT,
    plan        TEXT NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'starter', 'pro', 'enterprise')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER users_updated_at
    BEFORE UPDATE ON public.users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- AD ACCOUNTS
-- Stores Meta Ad Account IDs and OAuth tokens per user
-- ============================================================
CREATE TABLE public.ad_accounts (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    meta_account_id     TEXT NOT NULL,               -- e.g. "act_1234567890"
    account_name        TEXT,
    access_token        TEXT NOT NULL,               -- long-lived user access token
    token_expires_at    TIMESTAMPTZ,                 -- NULL = non-expiring (long-lived)
    currency            TEXT DEFAULT 'USD',
    timezone            TEXT DEFAULT 'UTC',
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, meta_account_id)
);

CREATE TRIGGER ad_accounts_updated_at
    BEFORE UPDATE ON public.ad_accounts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Index for fast user-scoped lookups
CREATE INDEX idx_ad_accounts_user_id ON public.ad_accounts(user_id);

-- ============================================================
-- PRODUCTS
-- Product catalog linked to a user (for ad creative generation)
-- ============================================================
CREATE TABLE public.products (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT,
    image_url       TEXT,
    landing_url     TEXT,
    price           NUMERIC(12, 2),
    currency        TEXT DEFAULT 'USD',
    tags            TEXT[] DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER products_updated_at
    BEFORE UPDATE ON public.products
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE INDEX idx_products_user_id ON public.products(user_id);

-- ============================================================
-- CAMPAIGN LOGS
-- Immutable audit trail of every AI action taken on Meta Ads
-- ============================================================
CREATE TYPE campaign_action AS ENUM (
    'campaign_created',
    'campaign_paused',
    'campaign_resumed',
    'campaign_deleted',
    'adset_created',
    'adset_updated',
    'ad_created',
    'ad_paused',
    'ad_resumed',
    'budget_updated',
    'roas_snapshot',
    'ai_recommendation',
    'error'
);

CREATE TABLE public.campaign_logs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    ad_account_id       UUID REFERENCES public.ad_accounts(id) ON DELETE SET NULL,
    product_id          UUID REFERENCES public.products(id) ON DELETE SET NULL,
    action              campaign_action NOT NULL,
    meta_campaign_id    TEXT,                        -- Meta's campaign/adset/ad ID
    meta_adset_id       TEXT,
    meta_ad_id          TEXT,
    payload             JSONB DEFAULT '{}',          -- full request sent to Meta API
    result              JSONB DEFAULT '{}',          -- response / stats snapshot
    roas                NUMERIC(10, 4),              -- captured if action = roas_snapshot
    spend               NUMERIC(12, 2),
    revenue             NUMERIC(12, 2),
    ai_model            TEXT,                        -- which AI model triggered this
    ai_reasoning        TEXT,                        -- short explanation from the AI
    status              TEXT NOT NULL DEFAULT 'success' CHECK (status IN ('success', 'failed', 'pending')),
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- campaign_logs is append-only — no UPDATE trigger needed
CREATE INDEX idx_campaign_logs_user_id     ON public.campaign_logs(user_id);
CREATE INDEX idx_campaign_logs_ad_account  ON public.campaign_logs(ad_account_id);
CREATE INDEX idx_campaign_logs_created_at  ON public.campaign_logs(created_at DESC);
CREATE INDEX idx_campaign_logs_action      ON public.campaign_logs(action);

-- ============================================================
-- ROW LEVEL SECURITY (RLS)
-- Each user can only access their own rows
-- ============================================================
ALTER TABLE public.users         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ad_accounts   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.products      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.campaign_logs ENABLE ROW LEVEL SECURITY;

-- Users: read/write own row only
CREATE POLICY "users: own row" ON public.users
    USING (id = auth.uid())
    WITH CHECK (id = auth.uid());

-- Ad Accounts: scoped to owner
CREATE POLICY "ad_accounts: own rows" ON public.ad_accounts
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Products: scoped to owner
CREATE POLICY "products: own rows" ON public.products
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Campaign Logs: read own logs; inserts via service role only (backend)
CREATE POLICY "campaign_logs: read own" ON public.campaign_logs
    FOR SELECT USING (user_id = auth.uid());

-- ============================================================
-- NEW USER TRIGGER
-- Auto-inserts a row in public.users on Supabase sign-up
-- ============================================================
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.users (id, email, full_name, avatar_url)
    VALUES (
        NEW.id,
        NEW.email,
        NEW.raw_user_meta_data->>'full_name',
        NEW.raw_user_meta_data->>'avatar_url'
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
