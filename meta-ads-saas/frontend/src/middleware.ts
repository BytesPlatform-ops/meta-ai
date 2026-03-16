import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

/**
 * Lightweight helper — checks if a Supabase auth cookie exists and
 * contains a session with a refresh_token (meaning the user has signed
 * in at some point and the session is potentially refreshable).
 *
 * We intentionally do NOT call getSession() / getUser() here because
 * those methods try to refresh an expired access token over the network.
 * Inside Docker the public Supabase URL (http://localhost:PORT) is not
 * reachable from the container, so the refresh silently fails and the
 * middleware concludes "no user" → redirect loop.
 *
 * Real validation happens in the dashboard layout (server component)
 * which can use the Docker-internal URL.
 */
function hasSessionCookie(request: NextRequest): boolean {
  // Look for any Supabase auth cookie (may be chunked: .0, .1, etc.)
  const cookie = request.cookies
    .getAll()
    .find(
      (c) =>
        c.name.startsWith("sb-") &&
        (c.name.endsWith("-auth-token") ||
          c.name.includes("-auth-token."))
    );
  if (!cookie || !cookie.value) return false;

  // Try to decode the value — @supabase/ssr v0.9+ uses base64url encoding,
  // older versions used URL-encoded JSON.
  try {
    let raw = cookie.value;
    try {
      // base64url → JSON
      raw = Buffer.from(raw, "base64url").toString("utf-8");
    } catch {
      // try URL-decoded JSON (legacy)
      raw = decodeURIComponent(raw);
    }
    const session = JSON.parse(raw);
    return !!session?.refresh_token;
  } catch {
    // If we can't parse it, the cookie still exists — let downstream
    // server components do the real validation.
    return true;
  }
}

/**
 * Middleware that:
 * 1) Refreshes Supabase cookies (setAll) so the browser keeps them alive
 * 2) Redirects unauthenticated users away from /dashboard
 * 3) Redirects authenticated users away from /auth/login
 */
export async function middleware(request: NextRequest) {
  const publicUrl = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
  const internalUrl = process.env.SUPABASE_URL || publicUrl;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

  // Skip if Supabase isn't configured
  if (!publicUrl || publicUrl.includes("<") || !key || key.includes("<")) {
    return NextResponse.next();
  }

  let supabaseResponse = NextResponse.next({ request });

  // Custom fetch that rewrites the public URL to the Docker-internal URL
  const proxyFetch: typeof globalThis.fetch = (input, init) => {
    const reqUrl =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    return globalThis.fetch(reqUrl.replace(publicUrl, internalUrl), init);
  };

  const supabase = createServerClient(publicUrl, key, {
    cookies: {
      getAll() {
        return request.cookies.getAll().map(({ name, value }) => ({ name, value }));
      },
      setAll(cookiesToSet: { name: string; value: string; options?: any }[]) {
        cookiesToSet.forEach(({ name, value, options }) => {
          request.cookies.set({ name, value, ...options });
        });
        supabaseResponse = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) => {
          supabaseResponse.cookies.set({ name, value, ...options });
        });
      },
    },
    global: { fetch: proxyFetch },
  });

  // Attempt a session refresh. This may fail inside Docker if the
  // internal URL is temporarily unreachable — that's fine, we fall
  // back to the cookie-presence check below.
  try {
    await supabase.auth.getSession();
  } catch {
    // swallow — cookie-level check is the fallback
  }

  const isAuthenticated = hasSessionCookie(request);

  // Protect /dashboard — kick unauthenticated users to login
  if (!isAuthenticated && request.nextUrl.pathname.startsWith("/dashboard")) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/auth/login";
    return NextResponse.redirect(loginUrl);
  }

  // Convenience — redirect signed-in users off the login page
  if (isAuthenticated && request.nextUrl.pathname === "/auth/login") {
    const dashboardUrl = request.nextUrl.clone();
    dashboardUrl.pathname = "/dashboard";
    return NextResponse.redirect(dashboardUrl);
  }

  return supabaseResponse;
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
