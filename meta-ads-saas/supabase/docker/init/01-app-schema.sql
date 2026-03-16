-- ============================================================
-- Meta Ads SaaS — App Schema (runs after GoTrue migration)
-- This script is executed via a startup entrypoint that waits
-- for GoTrue to finish creating auth.users, then applies this.
-- ============================================================
-- We check if the table already exists so re-runs are safe.

-- Enable UUID generation (idempotent)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- USERS — mirrors Supabase auth.users with profile data
-- ============================================================
CREATE TABLE IF NOT EXISTS public.users (
    id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email       TEXT NOT NULL UNIQUE,
    full_name   TEXT,
    avatar_url  TEXT,
    plan        TEXT NOT NULL DEFAULT 'free'
                    CHECK (plan IN ('free', 'starter', 'pro', 'enterprise')),
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

DROP TRIGGER IF EXISTS users_updated_at ON public.users;
CREATE TRIGGER users_updated_at
    BEFORE UPDATE ON public.users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- AD ACCOUNTS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.ad_accounts (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    meta_account_id     TEXT NOT NULL,
    account_name        TEXT,
    access_token        TEXT NOT NULL,
    token_expires_at    TIMESTAMPTZ,
    currency            TEXT DEFAULT 'USD',
    timezone            TEXT DEFAULT 'UTC',
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, meta_account_id)
);

DROP TRIGGER IF EXISTS ad_accounts_updated_at ON public.ad_accounts;
CREATE TRIGGER ad_accounts_updated_at
    BEFORE UPDATE ON public.ad_accounts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE INDEX IF NOT EXISTS idx_ad_accounts_user_id ON public.ad_accounts(user_id);

-- ============================================================
-- PRODUCTS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.products (
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

DROP TRIGGER IF EXISTS products_updated_at ON public.products;
CREATE TRIGGER products_updated_at
    BEFORE UPDATE ON public.products
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE INDEX IF NOT EXISTS idx_products_user_id ON public.products(user_id);

-- ============================================================
-- CAMPAIGN LOGS
-- ============================================================
DO $$ BEGIN
    CREATE TYPE campaign_action AS ENUM (
        'campaign_created','campaign_paused','campaign_resumed','campaign_deleted',
        'adset_created','adset_updated',
        'ad_created','ad_paused','ad_resumed',
        'budget_updated','roas_snapshot','ai_recommendation','error'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.campaign_logs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    ad_account_id       UUID REFERENCES public.ad_accounts(id) ON DELETE SET NULL,
    product_id          UUID REFERENCES public.products(id) ON DELETE SET NULL,
    action              campaign_action NOT NULL,
    meta_campaign_id    TEXT,
    meta_adset_id       TEXT,
    meta_ad_id          TEXT,
    payload             JSONB DEFAULT '{}',
    result              JSONB DEFAULT '{}',
    roas                NUMERIC(10, 4),
    spend               NUMERIC(12, 2),
    revenue             NUMERIC(12, 2),
    ai_model            TEXT,
    ai_reasoning        TEXT,
    status              TEXT NOT NULL DEFAULT 'success'
                            CHECK (status IN ('success', 'failed', 'pending')),
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_campaign_logs_user_id    ON public.campaign_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_campaign_logs_ad_account ON public.campaign_logs(ad_account_id);
CREATE INDEX IF NOT EXISTS idx_campaign_logs_created_at ON public.campaign_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_campaign_logs_action     ON public.campaign_logs(action);

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================
ALTER TABLE public.users         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ad_accounts   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.products      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.campaign_logs ENABLE ROW LEVEL SECURITY;

-- Drop-if-exists for idempotency
DROP POLICY IF EXISTS "users: own row"          ON public.users;
DROP POLICY IF EXISTS "ad_accounts: own rows"   ON public.ad_accounts;
DROP POLICY IF EXISTS "products: own rows"      ON public.products;
DROP POLICY IF EXISTS "campaign_logs: read own"  ON public.campaign_logs;

CREATE POLICY "users: own row" ON public.users
    USING (id = auth.uid()) WITH CHECK (id = auth.uid());

CREATE POLICY "ad_accounts: own rows" ON public.ad_accounts
    USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "products: own rows" ON public.products
    USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "campaign_logs: read own" ON public.campaign_logs
    FOR SELECT USING (user_id = auth.uid());

-- Allow service_role to bypass RLS (backend writes)
DROP POLICY IF EXISTS "service_role: full access users"         ON public.users;
DROP POLICY IF EXISTS "service_role: full access ad_accounts"   ON public.ad_accounts;
DROP POLICY IF EXISTS "service_role: full access products"      ON public.products;
DROP POLICY IF EXISTS "service_role: full access campaign_logs" ON public.campaign_logs;

CREATE POLICY "service_role: full access users" ON public.users
    TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role: full access ad_accounts" ON public.ad_accounts
    TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role: full access products" ON public.products
    TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role: full access campaign_logs" ON public.campaign_logs
    TO service_role USING (true) WITH CHECK (true);

-- ============================================================
-- NEW USER TRIGGER
-- Auto-creates public.users row when a user signs up via GoTrue
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

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ============================================================
-- USER PREFERENCES
-- Stores onboarding strategy choices per user
-- ============================================================
CREATE TABLE IF NOT EXISTS public.user_preferences (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL UNIQUE REFERENCES public.users(id) ON DELETE CASCADE,
    posting_frequency   TEXT NOT NULL DEFAULT 'manual_only'
        CHECK (posting_frequency IN ('daily', '3x_weekly', 'weekends_only', 'manual_only')),
    content_tone        TEXT NOT NULL DEFAULT 'professional'
        CHECK (content_tone IN ('professional', 'humorous', 'educational', 'promotional')),
    ad_budget_level     TEXT NOT NULL DEFAULT 'conservative'
        CHECK (ad_budget_level IN ('conservative_$10', 'moderate_$30', 'aggressive_$50', 'conservative', 'moderate', 'aggressive', 'custom')),
    budget_currency     TEXT NOT NULL DEFAULT 'USD',
    custom_budget       NUMERIC(12, 2),
    business_name       TEXT,
    business_description TEXT,
    target_audience     TEXT,
    website_url         TEXT,
    approval_required   BOOLEAN NOT NULL DEFAULT TRUE,
    setup_completed_at  TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS user_preferences_updated_at ON public.user_preferences;
CREATE TRIGGER user_preferences_updated_at
    BEFORE UPDATE ON public.user_preferences
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- CONTENT DRAFTS
-- AI-generated content that awaits user approval
-- ============================================================
DO $$ BEGIN
    CREATE TYPE draft_type AS ENUM ('organic', 'paid');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE draft_status AS ENUM (
        'pending', 'approved', 'rejected', 'publishing', 'active', 'failed'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.content_drafts (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    ad_account_id       UUID REFERENCES public.ad_accounts(id) ON DELETE SET NULL,
    draft_type          draft_type NOT NULL DEFAULT 'paid',
    status              draft_status NOT NULL DEFAULT 'pending',
    headline            TEXT,
    body_text           TEXT NOT NULL,
    image_url           TEXT,
    cta_type            TEXT,
    proposed_budget     NUMERIC(12, 2),
    targeting           JSONB DEFAULT '{}',
    meta_campaign_id    TEXT,
    meta_adset_id       TEXT,
    meta_ad_id          TEXT,
    ai_reasoning        TEXT,
    error_message       TEXT,
    scheduled_for       TIMESTAMPTZ,
    published_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS content_drafts_updated_at ON public.content_drafts;
CREATE TRIGGER content_drafts_updated_at
    BEFORE UPDATE ON public.content_drafts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE INDEX IF NOT EXISTS idx_content_drafts_user_id    ON public.content_drafts(user_id);
CREATE INDEX IF NOT EXISTS idx_content_drafts_status     ON public.content_drafts(status);
CREATE INDEX IF NOT EXISTS idx_content_drafts_created_at ON public.content_drafts(created_at DESC);

-- ── RLS for new tables ───────────────────────────────────────
ALTER TABLE public.user_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.content_drafts   ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "user_preferences: own row"   ON public.user_preferences;
DROP POLICY IF EXISTS "content_drafts: read own"     ON public.content_drafts;

CREATE POLICY "user_preferences: own row" ON public.user_preferences
    USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY "content_drafts: read own" ON public.content_drafts
    FOR SELECT USING (user_id = auth.uid());

-- ── Service role full access for new tables ──────────────────
DROP POLICY IF EXISTS "service_role: full access user_preferences" ON public.user_preferences;
DROP POLICY IF EXISTS "service_role: full access content_drafts"   ON public.content_drafts;

CREATE POLICY "service_role: full access user_preferences" ON public.user_preferences
    TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role: full access content_drafts" ON public.content_drafts
    TO service_role USING (true) WITH CHECK (true);

-- ============================================================
-- ACCOUNT AUDITS
-- AI-generated account health & strategy reports
-- ============================================================
CREATE TABLE IF NOT EXISTS public.account_audits (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    ad_account_id       UUID REFERENCES public.ad_accounts(id) ON DELETE SET NULL,
    total_spend         NUMERIC(12, 2),
    roas                NUMERIC(10, 4),
    winning_ads         JSONB DEFAULT '[]',
    losing_ads          JSONB DEFAULT '[]',
    ai_strategy_report  TEXT,
    status              TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS account_audits_updated_at ON public.account_audits;
CREATE TRIGGER account_audits_updated_at
    BEFORE UPDATE ON public.account_audits
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE INDEX IF NOT EXISTS idx_account_audits_user_id ON public.account_audits(user_id);
CREATE INDEX IF NOT EXISTS idx_account_audits_created_at ON public.account_audits(created_at DESC);

ALTER TABLE public.account_audits ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "account_audits: read own" ON public.account_audits;
CREATE POLICY "account_audits: read own" ON public.account_audits
    FOR SELECT USING (user_id = auth.uid());

DROP POLICY IF EXISTS "service_role: full access account_audits" ON public.account_audits;
CREATE POLICY "service_role: full access account_audits" ON public.account_audits
    TO service_role USING (true) WITH CHECK (true);

-- ============================================================
-- SCHEMA MIGRATIONS — additive columns for new features
-- ============================================================

-- Product catalog: target_audience per product
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS target_audience TEXT;

-- Content drafts: product-specific generation + A/B testing
ALTER TABLE public.content_drafts ADD COLUMN IF NOT EXISTS product_id UUID REFERENCES public.products(id) ON DELETE SET NULL;
ALTER TABLE public.content_drafts ADD COLUMN IF NOT EXISTS ab_variants JSONB;

-- Account audits: demographics + tone recommendation
ALTER TABLE public.account_audits ADD COLUMN IF NOT EXISTS audience_demographics JSONB;
ALTER TABLE public.account_audits ADD COLUMN IF NOT EXISTS tone_recommendation TEXT;

-- User preferences: industry niche
ALTER TABLE public.user_preferences ADD COLUMN IF NOT EXISTS industry_niche TEXT;

-- Tracking: pixel_id on ad_accounts, tracking_mode + extras on user_preferences
ALTER TABLE public.ad_accounts ADD COLUMN IF NOT EXISTS pixel_id TEXT DEFAULT NULL;
ALTER TABLE public.user_preferences ADD COLUMN IF NOT EXISTS tracking_mode TEXT DEFAULT 'whatsapp_cod';
ALTER TABLE public.user_preferences ADD COLUMN IF NOT EXISTS custom_budget NUMERIC DEFAULT NULL;
ALTER TABLE public.user_preferences ADD COLUMN IF NOT EXISTS whatsapp_number TEXT DEFAULT NULL;

-- Product type (physical, digital, saas, service)
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS product_type TEXT DEFAULT 'physical';

-- Product variation group rules (Shopify-style variation builder)
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS product_options JSONB DEFAULT NULL;

-- ============================================================
-- PRODUCT VARIANTS — multiple pricing tiers per product
-- ============================================================
CREATE TABLE IF NOT EXISTS public.product_variants (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id      UUID NOT NULL REFERENCES public.products(id) ON DELETE CASCADE,
    variant_name    TEXT NOT NULL,
    price           NUMERIC(12, 2) NOT NULL,
    currency        TEXT DEFAULT 'USD',
    sku             TEXT,
    sort_order      INT DEFAULT 0,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS product_variants_updated_at ON public.product_variants;
CREATE TRIGGER product_variants_updated_at
    BEFORE UPDATE ON public.product_variants
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE INDEX IF NOT EXISTS idx_product_variants_product_id ON public.product_variants(product_id);

ALTER TABLE public.product_variants ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "product_variants: own rows" ON public.product_variants;
CREATE POLICY "product_variants: own rows" ON public.product_variants
    USING (product_id IN (SELECT id FROM public.products WHERE user_id = auth.uid()))
    WITH CHECK (product_id IN (SELECT id FROM public.products WHERE user_id = auth.uid()));

DROP POLICY IF EXISTS "service_role: full access product_variants" ON public.product_variants;
CREATE POLICY "service_role: full access product_variants" ON public.product_variants
    TO service_role USING (true) WITH CHECK (true);

-- ============================================================
-- CAMPAIGN SUGGESTIONS — HITL Co-Pilot AI recommendations
-- ============================================================
CREATE TABLE IF NOT EXISTS public.campaign_suggestions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    ad_account_id       UUID REFERENCES public.ad_accounts(id) ON DELETE SET NULL,
    campaign_id         TEXT NOT NULL,
    adset_id            TEXT,
    entity_name         TEXT NOT NULL DEFAULT '',
    analysis_reasoning  TEXT NOT NULL,
    suggested_action    TEXT NOT NULL DEFAULT 'DO_NOTHING'
        CHECK (suggested_action IN ('INCREASE_BUDGET', 'DECREASE_BUDGET', 'PAUSE', 'DO_NOTHING', 'CREATE_NEW_CAMPAIGN')),
    action_payload      JSONB DEFAULT '{}',
    status              TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'FAILED')),
    product_id          UUID REFERENCES public.products(id) ON DELETE SET NULL,
    product_name        TEXT,
    executed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_campaign_suggestions_user_id ON public.campaign_suggestions(user_id);
CREATE INDEX IF NOT EXISTS idx_campaign_suggestions_status ON public.campaign_suggestions(status);
CREATE INDEX IF NOT EXISTS idx_campaign_suggestions_created_at ON public.campaign_suggestions(created_at DESC);

ALTER TABLE public.campaign_suggestions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "campaign_suggestions: own rows" ON public.campaign_suggestions;
CREATE POLICY "campaign_suggestions: own rows" ON public.campaign_suggestions
    USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "service_role: full access campaign_suggestions" ON public.campaign_suggestions;
CREATE POLICY "service_role: full access campaign_suggestions" ON public.campaign_suggestions
    TO service_role USING (true) WITH CHECK (true);

-- ============================================================
-- STORAGE — product image uploads bucket
-- ============================================================
INSERT INTO storage.buckets (id, name, public)
VALUES ('product-images', 'product-images', true)
ON CONFLICT (id) DO NOTHING;

-- Allow authenticated users to upload to their own folder
CREATE POLICY "product-images: upload own" ON storage.objects
    FOR INSERT TO authenticated
    WITH CHECK (bucket_id = 'product-images' AND (storage.foldername(name))[1] = auth.uid()::text);

-- Allow public read access (images are public)
CREATE POLICY "product-images: public read" ON storage.objects
    FOR SELECT TO anon, authenticated
    USING (bucket_id = 'product-images');

-- Service role full access
CREATE POLICY "product-images: service full" ON storage.objects
    FOR ALL TO service_role
    USING (bucket_id = 'product-images')
    WITH CHECK (bucket_id = 'product-images');

-- Instagram / placement support: social identities on ad_accounts
ALTER TABLE public.ad_accounts ADD COLUMN IF NOT EXISTS facebook_page_id TEXT DEFAULT NULL;
ALTER TABLE public.ad_accounts ADD COLUMN IF NOT EXISTS instagram_actor_id TEXT DEFAULT NULL;

-- Placement preference on user_preferences
ALTER TABLE public.user_preferences ADD COLUMN IF NOT EXISTS ad_placements TEXT DEFAULT 'BOTH';

-- Target country for ad targeting
ALTER TABLE public.user_preferences ADD COLUMN IF NOT EXISTS target_country TEXT DEFAULT 'PK';

-- Website intelligence: scraped + structured data from user's website
ALTER TABLE public.user_preferences ADD COLUMN IF NOT EXISTS website_intel JSONB DEFAULT NULL;
ALTER TABLE public.user_preferences ADD COLUMN IF NOT EXISTS website_scraped_at TIMESTAMPTZ DEFAULT NULL;

-- ============================================================
-- CONTENT STRATEGIES — AI-generated market research + campaign plans
-- ============================================================
CREATE TABLE IF NOT EXISTS public.content_strategies (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    niche               TEXT,
    research_summary    TEXT,
    strategy_json       JSONB DEFAULT '{}',
    status              TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'APPROVED')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS content_strategies_updated_at ON public.content_strategies;
CREATE TRIGGER content_strategies_updated_at
    BEFORE UPDATE ON public.content_strategies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE INDEX IF NOT EXISTS idx_content_strategies_user_id ON public.content_strategies(user_id);

ALTER TABLE public.content_strategies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "content_strategies: own rows" ON public.content_strategies;
CREATE POLICY "content_strategies: own rows" ON public.content_strategies
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "service_role: full access content_strategies" ON public.content_strategies;
CREATE POLICY "service_role: full access content_strategies" ON public.content_strategies
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Profit margin per product (for Cost Cap / Profit-Protection)
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS profit_margin NUMERIC(12, 2) DEFAULT NULL;

-- Product-level target country for geo-cultural targeting (ISO code: PK, US, GB, etc.)
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS target_country TEXT DEFAULT NULL;

-- Pixel-to-Product mapping: each product/URL gets its own pixel for conversion tracking
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS pixel_id TEXT DEFAULT NULL;

-- Validated Meta targeting spec on content drafts (interests, demographics, geo from AI pipeline)
ALTER TABLE public.content_drafts ADD COLUMN IF NOT EXISTS target_country TEXT DEFAULT NULL;
ALTER TABLE public.content_drafts ADD COLUMN IF NOT EXISTS targeting_spec JSONB DEFAULT NULL;

-- Draft-level pixel and conversion event tracking
ALTER TABLE public.content_drafts ADD COLUMN IF NOT EXISTS pixel_id TEXT DEFAULT NULL;
ALTER TABLE public.content_drafts ADD COLUMN IF NOT EXISTS conversion_event TEXT DEFAULT NULL;
ALTER TABLE public.content_drafts ADD COLUMN IF NOT EXISTS thumbnail_url TEXT DEFAULT NULL;
ALTER TABLE public.content_drafts ADD COLUMN IF NOT EXISTS destination_type TEXT DEFAULT 'WEBSITE';
ALTER TABLE public.content_drafts ADD COLUMN IF NOT EXISTS whatsapp_number TEXT DEFAULT NULL;

-- Flexible creative testing: array of media items [{type:'image'|'video', url:string, thumbnail_url?:string}]
ALTER TABLE public.content_drafts ADD COLUMN IF NOT EXISTS media_items JSONB DEFAULT NULL;

-- User-defined fallback target cost per result (for new accounts with no history)
ALTER TABLE public.user_preferences ADD COLUMN IF NOT EXISTS target_cost_per_result NUMERIC(12, 2) DEFAULT NULL;

-- ============================================================
-- OPTIMIZATION PROPOSALS — AI Co-Pilot suggestions
-- ============================================================
DO $$ BEGIN
    CREATE TYPE proposal_action AS ENUM (
        'increase_budget','decrease_budget',
        'pause','enable',
        'reallocate',
        'audience_shift',
        'custom',
        'refresh_creative',
        'prune_placements',
        'consolidate_adsets',
        'apply_cost_cap',
        'mutate_winner',
        'shift_budget',
        'create_lookalike'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE proposal_status AS ENUM (
        'pending','approved','applied','rejected','failed'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.optimization_proposals (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    ad_account_id   TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    entity_type     TEXT NOT NULL CHECK (entity_type IN ('campaign','adset','ad')),
    entity_name     TEXT,
    action_type     proposal_action NOT NULL DEFAULT 'custom',
    current_value   JSONB NOT NULL DEFAULT '{}',
    proposed_value  JSONB NOT NULL DEFAULT '{}',
    ai_reasoning    TEXT,
    impact_score    SMALLINT CHECK (impact_score BETWEEN 1 AND 10),
    status          proposal_status NOT NULL DEFAULT 'pending',
    applied_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS optimization_proposals_updated_at ON public.optimization_proposals;
CREATE TRIGGER optimization_proposals_updated_at
    BEFORE UPDATE ON public.optimization_proposals
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE INDEX IF NOT EXISTS idx_optimization_proposals_user_id ON public.optimization_proposals(user_id);
CREATE INDEX IF NOT EXISTS idx_optimization_proposals_status ON public.optimization_proposals(status);

ALTER TABLE public.optimization_proposals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "optimization_proposals: own rows" ON public.optimization_proposals;
CREATE POLICY "optimization_proposals: own rows" ON public.optimization_proposals
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "service_role: full access optimization_proposals" ON public.optimization_proposals;
CREATE POLICY "service_role: full access optimization_proposals" ON public.optimization_proposals
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ============================================================
-- GRANT table access to API roles (for PostgREST)
-- Per-draft destination URL (overrides product landing_url and preferences website_url)
ALTER TABLE public.content_drafts ADD COLUMN IF NOT EXISTS destination_url TEXT DEFAULT NULL;

-- Lead forms saved for reuse
CREATE TABLE IF NOT EXISTS public.lead_forms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id),
    page_id TEXT NOT NULL,
    meta_form_id TEXT NOT NULL,
    form_name TEXT NOT NULL,
    questions JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE public.lead_forms ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users see own lead forms" ON public.lead_forms FOR ALL USING (auth.uid() = user_id);

-- Draft-level lead form ID for INSTANT_FORM destination
ALTER TABLE public.content_drafts ADD COLUMN IF NOT EXISTS lead_form_id TEXT DEFAULT NULL;

-- Multi-messaging & phone call destination fields
ALTER TABLE public.content_drafts ADD COLUMN IF NOT EXISTS selected_messaging_apps JSONB DEFAULT NULL;
ALTER TABLE public.content_drafts ADD COLUMN IF NOT EXISTS call_phone_number TEXT DEFAULT NULL;

-- ============================================================
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
    TO anon, authenticated, service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public
    TO anon, authenticated, service_role;
