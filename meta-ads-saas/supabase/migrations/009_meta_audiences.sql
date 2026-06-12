-- ============================================================
-- META AUDIENCES — Product-aware audience registry
-- Maps every Meta audience back to its owning product
-- to prevent cross-product audience contamination.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.meta_audiences (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    workspace_id        UUID REFERENCES public.workspaces(id) ON DELETE CASCADE,
    product_id          UUID REFERENCES public.products(id) ON DELETE SET NULL,
    meta_audience_id    TEXT NOT NULL,
    name                TEXT NOT NULL,
    audience_type       TEXT NOT NULL DEFAULT 'SEED'
        CHECK (audience_type IN ('SEED', 'LAL', 'RETARGETING', 'EXCLUSION', 'ENGAGEMENT')),
    origin_audience_id  TEXT,
    pixel_id            TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_meta_audiences_meta_id
    ON public.meta_audiences (meta_audience_id);
CREATE INDEX IF NOT EXISTS idx_meta_audiences_product
    ON public.meta_audiences (product_id);
CREATE INDEX IF NOT EXISTS idx_meta_audiences_workspace
    ON public.meta_audiences (workspace_id);

ALTER TABLE public.meta_audiences ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "meta_audiences: own rows" ON public.meta_audiences;
CREATE POLICY "meta_audiences: own rows" ON public.meta_audiences
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS "service_role: full access meta_audiences" ON public.meta_audiences;
CREATE POLICY "service_role: full access meta_audiences" ON public.meta_audiences
    FOR ALL TO service_role USING (true) WITH CHECK (true);
