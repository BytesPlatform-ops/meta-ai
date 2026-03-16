import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

function isConfigured(): boolean {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
  return !!url && !url.includes("<") && !!key && !key.includes("<");
}

export { isConfigured as isSupabaseConfigured };

/**
 * Server-side Supabase client.
 *
 * Uses NEXT_PUBLIC_SUPABASE_URL for cookie name consistency with the
 * browser client, but rewrites API calls to the Docker-internal URL
 * (SUPABASE_URL) so they work inside the container.
 */
export function createClient() {
  if (!isConfigured()) {
    throw new Error(
      "Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in your .env file."
    );
  }
  const publicUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
  const internalUrl = process.env.SUPABASE_URL || publicUrl;

  // Rewrite fetch requests from the public URL to the Docker-internal URL
  const proxyFetch: typeof globalThis.fetch = (input, init) => {
    const requestUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    const rewritten = requestUrl.replace(publicUrl, internalUrl);
    return globalThis.fetch(rewritten, init);
  };

  const cookieStore = cookies();
  return createServerClient(
    publicUrl,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll().map(({ name, value }) => ({ name, value }));
        },
        setAll(cookiesToSet: { name: string; value: string; options?: any }[]) {
          try {
            cookiesToSet.forEach(({ name, value, options }) => {
              cookieStore.set({ name, value, ...options });
            });
          } catch {}
        },
      },
      global: { fetch: proxyFetch },
    }
  );
}
