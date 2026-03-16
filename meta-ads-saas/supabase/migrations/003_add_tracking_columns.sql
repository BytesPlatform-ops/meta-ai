-- Migration: Add tracking columns for Pixel / WhatsApp-COD mode
-- ad_accounts.pixel_id — stores the selected Meta Pixel ID
-- user_preferences.tracking_mode — 'website_pixel' or 'whatsapp_cod'

ALTER TABLE public.ad_accounts
ADD COLUMN IF NOT EXISTS pixel_id TEXT DEFAULT NULL;

ALTER TABLE public.user_preferences
ADD COLUMN IF NOT EXISTS tracking_mode TEXT DEFAULT 'whatsapp_cod'
    CHECK (tracking_mode IN ('website_pixel', 'whatsapp_cod'));

ALTER TABLE public.user_preferences
ADD COLUMN IF NOT EXISTS industry_niche TEXT DEFAULT NULL;

ALTER TABLE public.user_preferences
ADD COLUMN IF NOT EXISTS custom_budget NUMERIC DEFAULT NULL;

ALTER TABLE public.user_preferences
ADD COLUMN IF NOT EXISTS whatsapp_number TEXT DEFAULT NULL;
