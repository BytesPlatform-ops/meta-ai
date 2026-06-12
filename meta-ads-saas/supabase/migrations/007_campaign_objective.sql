-- Add campaign_objective column to content_drafts
-- Nullable: when NULL, objective is computed dynamically from destination_type + conversion_event + pixel
-- When set, acts as a user override
ALTER TABLE public.content_drafts ADD COLUMN IF NOT EXISTS campaign_objective TEXT DEFAULT NULL;
