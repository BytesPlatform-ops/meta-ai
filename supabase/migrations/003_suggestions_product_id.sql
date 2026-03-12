-- Add product awareness to campaign suggestions
ALTER TABLE public.campaign_suggestions ADD COLUMN IF NOT EXISTS product_id UUID REFERENCES public.products(id) ON DELETE SET NULL;
ALTER TABLE public.campaign_suggestions ADD COLUMN IF NOT EXISTS product_name TEXT;

-- Expand allowed actions to include CREATE_NEW_CAMPAIGN
ALTER TABLE public.campaign_suggestions DROP CONSTRAINT IF EXISTS campaign_suggestions_suggested_action_check;
ALTER TABLE public.campaign_suggestions ADD CONSTRAINT campaign_suggestions_suggested_action_check
  CHECK (suggested_action IN ('INCREASE_BUDGET', 'DECREASE_BUDGET', 'PAUSE', 'DO_NOTHING', 'CREATE_NEW_CAMPAIGN'));
