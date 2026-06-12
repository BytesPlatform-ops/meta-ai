-- Add target_cities (JSONB array of city names) for city-level ad targeting
ALTER TABLE public.user_preferences ADD COLUMN IF NOT EXISTS target_cities JSONB DEFAULT '[]'::jsonb;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS target_cities JSONB DEFAULT NULL;
