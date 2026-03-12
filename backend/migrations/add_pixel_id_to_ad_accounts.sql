-- Migration: Add pixel_id column to ad_accounts table
-- Stores the Meta Pixel ID selected by the user for conversion tracking.
-- When NULL, the system uses the WhatsApp/Messenger COD fallback strategy.

ALTER TABLE ad_accounts
ADD COLUMN IF NOT EXISTS pixel_id VARCHAR DEFAULT NULL;

COMMENT ON COLUMN ad_accounts.pixel_id IS 'Meta Pixel ID for conversion tracking. NULL = WhatsApp/COD fallback.';
