-- ============================================================
-- Migration 005: Workspace / Agency Model
-- 1 User → Many Workspaces → Each workspace owns ad assets
--
-- STEP 1: Schema changes only. Backward-compatible.
-- All existing data gets a default workspace via the data
-- migration at the bottom of this file.
-- ============================================================

-- ── 1. WORKSPACES TABLE ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.workspaces (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL DEFAULT 'My First Business',

    -- Meta asset IDs (moved from ad_accounts — one set per workspace)
    meta_ad_account_id  TEXT,
    meta_page_id        TEXT,
    meta_pixel_id       TEXT,
    meta_ig_actor_id    TEXT,
    -- Per-workspace access token (if user connects different Meta
    -- Business Managers per workspace). Falls back to ad_accounts
    -- token if NULL.
    meta_access_token   TEXT,

    -- Business context (moved from user_preferences — these are
    -- per-business, not per-user)
    business_name       TEXT,
    business_description TEXT,
    target_audience     TEXT,
    website_url         TEXT,
    target_country      TEXT DEFAULT 'PK',
    industry_niche      TEXT,
    website_intel       JSONB DEFAULT NULL,
    website_scraped_at  TIMESTAMPTZ DEFAULT NULL,
    tracking_mode       TEXT DEFAULT 'whatsapp_cod',

    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS workspaces_updated_at ON public.workspaces;
CREATE TRIGGER workspaces_updated_at
    BEFORE UPDATE ON public.workspaces
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE INDEX IF NOT EXISTS idx_workspaces_user_id ON public.workspaces(user_id);

-- ── 2. ADD workspace_id FK TO ALL BUSINESS TABLES ───────────────
-- These are all NULLABLE initially so existing rows don't break.
-- The data migration below backfills them.

ALTER TABLE public.ad_accounts
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES public.workspaces(id) ON DELETE CASCADE;

ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES public.workspaces(id) ON DELETE CASCADE;

ALTER TABLE public.content_drafts
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES public.workspaces(id) ON DELETE CASCADE;

ALTER TABLE public.campaign_logs
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES public.workspaces(id) ON DELETE CASCADE;

ALTER TABLE public.campaign_suggestions
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES public.workspaces(id) ON DELETE CASCADE;

ALTER TABLE public.content_strategies
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES public.workspaces(id) ON DELETE CASCADE;

ALTER TABLE public.optimization_proposals
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES public.workspaces(id) ON DELETE CASCADE;

ALTER TABLE public.account_audits
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES public.workspaces(id) ON DELETE CASCADE;

ALTER TABLE public.lead_forms
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES public.workspaces(id) ON DELETE CASCADE;

-- Indexes for workspace_id on high-traffic tables
CREATE INDEX IF NOT EXISTS idx_ad_accounts_workspace_id       ON public.ad_accounts(workspace_id);
CREATE INDEX IF NOT EXISTS idx_products_workspace_id          ON public.products(workspace_id);
CREATE INDEX IF NOT EXISTS idx_content_drafts_workspace_id    ON public.content_drafts(workspace_id);
CREATE INDEX IF NOT EXISTS idx_campaign_logs_workspace_id     ON public.campaign_logs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_campaign_suggestions_ws_id     ON public.campaign_suggestions(workspace_id);
CREATE INDEX IF NOT EXISTS idx_optimization_proposals_ws_id   ON public.optimization_proposals(workspace_id);
CREATE INDEX IF NOT EXISTS idx_account_audits_workspace_id    ON public.account_audits(workspace_id);

-- ── 3. RLS POLICIES FOR WORKSPACES ──────────────────────────────

ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "workspaces: own rows" ON public.workspaces;
CREATE POLICY "workspaces: own rows" ON public.workspaces
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "service_role: full access workspaces" ON public.workspaces;
CREATE POLICY "service_role: full access workspaces" ON public.workspaces
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Grant access
GRANT SELECT, INSERT, UPDATE, DELETE ON public.workspaces
    TO anon, authenticated, service_role;

-- ── 4. AUTO-CREATE DEFAULT WORKSPACE ON SIGNUP ──────────────────
-- Extends the existing handle_new_user() trigger to also create
-- a default workspace.

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
    -- Auto-create default workspace for new signups
    INSERT INTO public.workspaces (user_id, name)
    VALUES (NEW.id, 'My First Business');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ── 5. DATA MIGRATION — Backfill existing users ────────────────
-- Creates a default workspace for every existing user who doesn't
-- have one yet, then moves their data into it.

-- 5a. Create default workspace per existing user
INSERT INTO public.workspaces (user_id, name)
SELECT u.id, 'My First Business'
FROM public.users u
WHERE NOT EXISTS (
    SELECT 1 FROM public.workspaces w WHERE w.user_id = u.id
);

-- 5b. Copy Meta asset IDs from ad_accounts → workspace
-- (takes the first active ad_account per user as the default)
UPDATE public.workspaces w
SET
    meta_ad_account_id = aa.meta_account_id,
    meta_page_id       = aa.facebook_page_id,
    meta_pixel_id      = aa.pixel_id,
    meta_ig_actor_id   = aa.instagram_actor_id,
    meta_access_token  = aa.access_token
FROM (
    SELECT DISTINCT ON (user_id)
        user_id, meta_account_id, facebook_page_id,
        pixel_id, instagram_actor_id, access_token
    FROM public.ad_accounts
    WHERE is_active = TRUE
    ORDER BY user_id, created_at ASC
) aa
WHERE w.user_id = aa.user_id
  AND w.meta_ad_account_id IS NULL;

-- 5c. Copy business context from user_preferences → workspace
UPDATE public.workspaces w
SET
    business_name        = up.business_name,
    business_description = up.business_description,
    target_audience      = up.target_audience,
    website_url          = up.website_url,
    target_country       = COALESCE(up.target_country, 'PK'),
    industry_niche       = up.industry_niche,
    website_intel        = up.website_intel,
    website_scraped_at   = up.website_scraped_at,
    tracking_mode        = COALESCE(up.tracking_mode, 'whatsapp_cod')
FROM public.user_preferences up
WHERE w.user_id = up.user_id
  AND w.business_name IS NULL;

-- 5d. Backfill workspace_id on all business tables
-- Each user's rows get assigned to their default workspace
UPDATE public.ad_accounts t
SET workspace_id = w.id
FROM public.workspaces w
WHERE t.user_id = w.user_id AND t.workspace_id IS NULL;

UPDATE public.products t
SET workspace_id = w.id
FROM public.workspaces w
WHERE t.user_id = w.user_id AND t.workspace_id IS NULL;

UPDATE public.content_drafts t
SET workspace_id = w.id
FROM public.workspaces w
WHERE t.user_id = w.user_id AND t.workspace_id IS NULL;

UPDATE public.campaign_logs t
SET workspace_id = w.id
FROM public.workspaces w
WHERE t.user_id = w.user_id AND t.workspace_id IS NULL;

UPDATE public.campaign_suggestions t
SET workspace_id = w.id
FROM public.workspaces w
WHERE t.user_id = w.user_id AND t.workspace_id IS NULL;

UPDATE public.content_strategies t
SET workspace_id = w.id
FROM public.workspaces w
WHERE t.user_id = w.user_id AND t.workspace_id IS NULL;

UPDATE public.optimization_proposals t
SET workspace_id = w.id
FROM public.workspaces w
WHERE t.user_id = w.user_id AND t.workspace_id IS NULL;

UPDATE public.account_audits t
SET workspace_id = w.id
FROM public.workspaces w
WHERE t.user_id = w.user_id AND t.workspace_id IS NULL;

UPDATE public.lead_forms t
SET workspace_id = w.id
FROM public.workspaces w
WHERE t.user_id = w.user_id AND t.workspace_id IS NULL;

-- ── 5e. Replace uniqueness: (user_id, meta_account_id) → (workspace_id, meta_account_id)
-- Allows the same Meta account to be linked in multiple workspaces
ALTER TABLE public.ad_accounts DROP CONSTRAINT IF EXISTS ad_accounts_user_id_meta_account_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_ad_accounts_ws_meta ON public.ad_accounts(workspace_id, meta_account_id) WHERE workspace_id IS NOT NULL;

-- ── 6. MAKE workspace_id NOT NULL (after backfill) ──────────────
-- Only safe to run after all existing data is backfilled.
-- Uncomment in Step 2 once the backend is updated to always
-- provide workspace_id on inserts.
--
-- ALTER TABLE public.ad_accounts         ALTER COLUMN workspace_id SET NOT NULL;
-- ALTER TABLE public.products             ALTER COLUMN workspace_id SET NOT NULL;
-- ALTER TABLE public.content_drafts       ALTER COLUMN workspace_id SET NOT NULL;
-- ALTER TABLE public.campaign_logs        ALTER COLUMN workspace_id SET NOT NULL;
-- ALTER TABLE public.campaign_suggestions ALTER COLUMN workspace_id SET NOT NULL;
-- ALTER TABLE public.content_strategies   ALTER COLUMN workspace_id SET NOT NULL;
-- ALTER TABLE public.optimization_proposals ALTER COLUMN workspace_id SET NOT NULL;
-- ALTER TABLE public.account_audits       ALTER COLUMN workspace_id SET NOT NULL;
-- ALTER TABLE public.lead_forms           ALTER COLUMN workspace_id SET NOT NULL;
