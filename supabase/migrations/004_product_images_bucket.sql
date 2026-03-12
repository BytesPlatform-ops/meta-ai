-- Create product-images storage bucket
INSERT INTO storage.buckets (id, name, public)
VALUES ('product-images', 'product-images', true)
ON CONFLICT (id) DO NOTHING;

-- Allow service role full access (backend uploads with service role key)
DROP POLICY IF EXISTS "product-images: service full" ON storage.objects;
CREATE POLICY "product-images: service full" ON storage.objects
    FOR ALL TO service_role
    USING (bucket_id = 'product-images')
    WITH CHECK (bucket_id = 'product-images');

-- Allow public read access (images are public URLs)
DROP POLICY IF EXISTS "product-images: public read" ON storage.objects;
CREATE POLICY "product-images: public read" ON storage.objects
    FOR SELECT TO anon, authenticated
    USING (bucket_id = 'product-images');
