-- Add product_options JSONB column to store variation group rules
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS product_options JSONB DEFAULT NULL;
