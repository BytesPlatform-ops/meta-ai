-- ============================================================
-- Customers table — stores customer data (email/phone) for
-- Custom Audience + Lookalike Audience pipeline.
-- Niche-scoped to prevent cross-product contamination.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.customers (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    email       TEXT,
    phone       TEXT,
    niche       TEXT,
    product_id  UUID REFERENCES public.products(id) ON DELETE SET NULL,
    source      TEXT DEFAULT 'manual',   -- manual | webhook | meta_lead | zapier
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- At least one contact method required
    CONSTRAINT customers_contact_check CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

-- Prevent exact duplicates per user (same email+phone+niche combo)
CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_dedup
    ON public.customers (user_id, COALESCE(email, ''), COALESCE(phone, ''), COALESCE(niche, ''));

-- Fast niche lookups for audience_sync
CREATE INDEX IF NOT EXISTS idx_customers_user_niche
    ON public.customers (user_id, niche);

CREATE INDEX IF NOT EXISTS idx_customers_user_product
    ON public.customers (user_id, product_id);
