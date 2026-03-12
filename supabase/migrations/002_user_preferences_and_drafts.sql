-- ============================================================
-- Migration 002 — User Preferences & Content Drafts
-- Adds strategy preferences and an approval-based drafts system
-- ============================================================

-- ============================================================
-- USER PREFERENCES
-- Stores onboarding strategy choices per user
-- ============================================================
CREATE TABLE public.user_preferences (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL UNIQUE REFERENCES public.users(id) ON DELETE CASCADE,
    posting_frequency   TEXT NOT NULL DEFAULT 'manual_only'
        CHECK (posting_frequency IN ('daily', '3x_weekly', 'weekends_only', 'manual_only')),
    content_tone        TEXT NOT NULL DEFAULT 'professional'
        CHECK (content_tone IN ('professional', 'humorous', 'educational', 'promotional')),
    ad_budget_level     TEXT NOT NULL DEFAULT 'conservative_$10'
        CHECK (ad_budget_level IN ('conservative_$10', 'moderate_$30', 'aggressive_$50')),
    business_name       TEXT,
    business_description TEXT,                 -- what the business does, products/services
    target_audience     TEXT,                  -- who the ideal customer is
    website_url         TEXT,
    approval_required   BOOLEAN NOT NULL DEFAULT TRUE,
    setup_completed_at  TIMESTAMPTZ,          -- NULL until wizard is finished
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER user_preferences_updated_at
    BEFORE UPDATE ON public.user_preferences
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- CONTENT DRAFTS
-- AI-generated content that awaits user approval
-- ============================================================
CREATE TYPE draft_type AS ENUM ('organic', 'paid');

CREATE TYPE draft_status AS ENUM (
    'pending',       -- awaiting user review
    'approved',      -- user clicked Approve & Schedule
    'rejected',      -- user rejected / wants regeneration
    'publishing',    -- MCP execution in progress
    'active',        -- live on Meta (has meta_ad_id)
    'failed'         -- MCP call failed
);

CREATE TABLE public.content_drafts (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    ad_account_id       UUID REFERENCES public.ad_accounts(id) ON DELETE SET NULL,
    draft_type          draft_type NOT NULL DEFAULT 'organic',
    status              draft_status NOT NULL DEFAULT 'pending',

    -- AI-generated content
    headline            TEXT,
    body_text           TEXT NOT NULL,
    image_url           TEXT,                   -- placeholder or generated image
    cta_type            TEXT,                   -- e.g. "LEARN_MORE", "SHOP_NOW"

    -- Paid ad specifics
    proposed_budget     NUMERIC(12, 2),         -- daily budget in dollars
    targeting           JSONB DEFAULT '{}',     -- AI-researched targeting params

    -- Meta references (populated after publish)
    meta_campaign_id    TEXT,
    meta_adset_id       TEXT,
    meta_ad_id          TEXT,

    -- AI metadata
    ai_reasoning        TEXT,                   -- why AI created this draft
    error_message       TEXT,                   -- if status = failed

    scheduled_for       TIMESTAMPTZ,            -- when to publish
    published_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER content_drafts_updated_at
    BEFORE UPDATE ON public.content_drafts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE INDEX idx_content_drafts_user_id    ON public.content_drafts(user_id);
CREATE INDEX idx_content_drafts_status     ON public.content_drafts(status);
CREATE INDEX idx_content_drafts_created_at ON public.content_drafts(created_at DESC);

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================
ALTER TABLE public.user_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.content_drafts   ENABLE ROW LEVEL SECURITY;

-- Preferences: own row only
CREATE POLICY "user_preferences: own row" ON public.user_preferences
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Drafts: read own; inserts/updates via service role (backend)
CREATE POLICY "content_drafts: read own" ON public.content_drafts
    FOR SELECT USING (user_id = auth.uid());
