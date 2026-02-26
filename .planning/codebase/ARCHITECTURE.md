# Architecture

**Analysis Date:** 2026-02-27

## Pattern Overview

**Overall:** Microservices with layered backend and Next.js frontend, connected via REST API.

**Key Characteristics:**
- Stateless REST API with JWT token-based authentication (Supabase Auth)
- Clear separation between frontend (Next.js/React) and backend (FastAPI/Python)
- Dependency injection pattern for cross-cutting concerns (auth, DB client)
- MCP (Model Context Protocol) integration for AI-powered Meta Ads operations
- Supabase as the unified data store and auth provider
- Multi-layered backend with clear boundaries: API routes → services → external clients → DB

## Layers

**Frontend (Next.js/React):**
- Purpose: Web UI for dashboard, auth, and ad account management
- Location: `/Users/bytes/Desktop/marketing/meta-ads-saas/frontend/src/`
- Contains: Pages (App Router), components, API client utilities, Supabase client configuration
- Depends on: Backend API, Supabase Auth
- Used by: End users (browser)

**Backend API Layer:**
- Purpose: REST endpoints handling user requests, routing to appropriate services
- Location: `/Users/bytes/Desktop/marketing/meta-ads-saas/backend/app/api/routes/`
- Contains: Route handlers (`oauth.py`, `campaigns.py`, `products.py`), dependency injection (`deps.py`)
- Depends on: Core config, security utilities, service layer, database layer
- Used by: Frontend, external clients

**Backend Service Layer:**
- Purpose: Business logic and orchestration — handles OAuth flows, communicates with external APIs
- Location: `/Users/bytes/Desktop/marketing/meta-ads-saas/backend/app/services/`
- Contains: `meta_oauth.py` (OAuth 2.0 workflow), `mcp_client.py` (MCP JSON-RPC client)
- Depends on: Core config, external HTTP clients (httpx), database layer
- Used by: API routes

**Backend Core Layer:**
- Purpose: Cross-cutting concerns — configuration, security, token generation
- Location: `/Users/bytes/Desktop/marketing/meta-ads-saas/backend/app/core/`
- Contains: `config.py` (settings/env), `security.py` (JWT verification), `state_token.py` (CSRF-safe state generation)
- Depends on: Pydantic, PyJWT, standard library
- Used by: All backend layers

**Backend Database Layer:**
- Purpose: Data persistence and client management
- Location: `/Users/bytes/Desktop/marketing/meta-ads-saas/backend/app/db/`
- Contains: `supabase_client.py` (singleton Supabase client)
- Depends on: Supabase SDK
- Used by: Services and routes

## Data Flow

**OAuth 2.0 Flow (Meta Ad Account Connection):**

1. Frontend user clicks "Connect with Facebook" → calls `/api/v1/oauth/meta/authorize`
2. Backend generates HMAC-signed state token (user_id embedded) via `state_token.generate_state()`
3. Backend returns authorization URL pointing to Facebook's consent screen
4. User grants permission on Facebook
5. Facebook redirects to `/api/v1/oauth/meta/callback?code=...&state=...`
6. Backend verifies state token (CSRF check) via `state_token.verify_state()` → extracts user_id
7. Backend exchanges code for short-lived token → upgrades to long-lived token (via `meta_oauth.py`)
8. Backend fetches user's ad accounts from Meta Graph API
9. Backend upserts accounts + tokens to Supabase `ad_accounts` table
10. Backend redirects to frontend dashboard with success/error query param
11. Frontend displays connected accounts list

**Campaign Operations Flow:**

1. Frontend calls `/api/v1/campaigns/{ad_account_id}/pause` with campaign_id
2. Backend route handler extracts user JWT → verifies user owns the ad account
3. Backend retrieves access token from Supabase `ad_accounts` table
4. Backend calls MCP service `mcp_client.pause_campaign()`
5. MCP client sends JSON-RPC call to external MCP server with Meta access token in header
6. MCP server calls Meta Graph API on behalf of the user
7. Backend logs the action to `campaign_logs` table (for audit trail)
8. Backend returns result to frontend

**State Management:**

- **Frontend Auth State:** Managed by Supabase Auth client, stored in browser session
- **Backend Auth:** JWT verification per request via `get_current_user_id()` dependency
- **User's Ad Account State:** Stored in Supabase `ad_accounts` table (tokens, metadata, status)
- **Campaign State:** Stored in Meta's Graph API; Backend logs operations for audit trail
- **Product Catalog State:** Stored in Supabase `products` table (user-scoped)

## Key Abstractions

**Meta OAuth Pipeline (`meta_oauth.py`):**
- Purpose: Encapsulates the 6-step OAuth callback flow (code → short token → long token → ad accounts → DB)
- Examples: `exchange_code_for_token()`, `exchange_for_long_lived_token()`, `fetch_ad_accounts()`, `upsert_ad_accounts()`, `handle_oauth_callback()`
- Pattern: Step-by-step async functions; final orchestrator function chains them; clean error boundaries

**CSRF-Safe State Token (`state_token.py`):**
- Purpose: Stateless CSRF protection without requiring server-side session store
- Examples: `generate_state()` (base64 + HMAC-signed), `verify_state()` (decode + HMAC validation)
- Pattern: HMAC-signed tokens embed user_id; signature proof that only the backend could have generated it

**MCP Client (`mcp_client.py`):**
- Purpose: Thin async wrapper around Facebook Ads MCP server's JSON-RPC endpoint
- Examples: `call_tool()` (low-level RPC), convenience wrappers (`get_campaign_insights()`, `pause_campaign()`, `create_campaign()`, `update_ad_budget()`)
- Pattern: Inject user's access token per request via `X-Meta-Access-Token` header; all operations scoped to that user

**Dependency Injection (`deps.py`):**
- Purpose: Provides authenticated user context to route handlers without boilerplate
- Examples: `get_current_user_id()` extracts and verifies JWT, returns user UUID
- Pattern: FastAPI dependency function with bearer token scheme; raises 401 on invalid/missing token

**Typed API Client (`frontend/src/lib/api.ts`):**
- Purpose: Centralized HTTP client with automatic JWT attachment
- Examples: `api.getMetaAuthUrl()`, `api.listAdAccounts()`, `api.pauseCampaign()`, `api.listProducts()`
- Pattern: Axios instance with interceptor that injects Supabase JWT token on every request

## Entry Points

**Frontend Home Page:**
- Location: `/Users/bytes/Desktop/marketing/meta-ads-saas/frontend/src/app/page.tsx`
- Triggers: User visits `/`
- Responsibilities: Marketing landing page with "Get Started" and "Dashboard" CTAs

**Frontend Auth Page:**
- Location: `/Users/bytes/Desktop/marketing/meta-ads-saas/frontend/src/app/auth/login/page.tsx`
- Triggers: User clicks login or is redirected by auth guard
- Responsibilities: Email/password login form, calls Supabase Auth

**Frontend Dashboard:**
- Location: `/Users/bytes/Desktop/marketing/meta-ads-saas/frontend/src/app/dashboard/page.tsx`
- Triggers: Authenticated user navigates to `/dashboard`
- Responsibilities: Main dashboard hub; auth guard redirects to login if unauthenticated; displays stats placeholders and ad account connection CTA

**Frontend Settings Page:**
- Location: `/Users/bytes/Desktop/marketing/meta-ads-saas/frontend/src/app/dashboard/settings/page.tsx`
- Triggers: User navigates to `/dashboard/settings`
- Responsibilities: Meta OAuth connection UI; displays connected ad accounts; allows disconnecting accounts

**Backend App:**
- Location: `/Users/bytes/Desktop/marketing/meta-ads-saas/backend/app/main.py`
- Triggers: ASGI server startup (Uvicorn/Gunicorn)
- Responsibilities: FastAPI app initialization, middleware setup (CORS), router registration (`oauth`, `campaigns`, `products`)

**Meta OAuth Authorize:**
- Location: `GET /api/v1/oauth/meta/authorize`
- Triggers: Frontend user clicks "Connect with Facebook"
- Responsibilities: Generate CSRF-safe state token, return Facebook consent URL

**Meta OAuth Callback:**
- Location: `GET /api/v1/oauth/meta/callback`
- Triggers: Facebook redirects after user grants/denies permission
- Responsibilities: Verify state (CSRF check), orchestrate token exchange, fetch ad accounts, upsert to DB, redirect to dashboard

**Campaign Insights:**
- Location: `GET /api/v1/campaigns/{ad_account_id}/insights/{campaign_id}`
- Triggers: Frontend requests campaign performance data
- Responsibilities: Retrieve user's access token, call MCP service, return insights

**Campaign Pause:**
- Location: `POST /api/v1/campaigns/{ad_account_id}/pause`
- Triggers: Frontend user pauses a campaign
- Responsibilities: Retrieve user's access token, call MCP service, log action to audit table, return result

## Error Handling

**Strategy:** Multi-layer error boundary approach with clear responsibility at each layer

**Patterns:**

- **Frontend JWT/Auth:** Supabase client-side error handling in login form; shows user-friendly messages (e.g., "Invalid email or password")

- **Frontend API Errors:** Axios errors caught at component level; displayed in banners or toasts (see `settings/page.tsx` banner pattern)

- **Backend Auth Errors:** `deps.py` raises `HTTPException(401)` for invalid/missing tokens; FastAPI serializes to JSON error response

- **Backend OAuth Errors:** `meta_oauth.py` wraps Meta API errors via `_raise_for_meta_error()` helper; converts cryptic Graph API errors to descriptive RuntimeError; routes handle and redirect to frontend with error query param

- **Backend MCP Errors:** `mcp_client.py` raises `MCPError` on JSON-RPC error response; route handlers catch and return 502 with error detail

- **Backend Data Layer:** Supabase SDK raises exceptions; not caught — allowed to propagate as 500 errors (indicates infrastructure issue)

## Cross-Cutting Concerns

**Logging:**
- Backend: No centralized logger detected; uses Python `print()` implicitly via FastAPI. Campaign logs written to `campaign_logs` table for audit trail.
- Frontend: Browser console via React/Next.js dev tools.

**Validation:**
- Frontend: HTML5 form validation (required inputs); component-level state validation (email format via browser)
- Backend: Pydantic models enforce type safety and schema validation at route layer (`ProductCreate`, `ProductUpdate`, `PauseCampaignRequest`)

**Authentication:**
- Supabase Auth for user sign-up/login (email/password)
- JWT bearer token in Authorization header for API requests
- Token verification via `decode_supabase_jwt()` in core/security.py
- Per-route auth via FastAPI dependency injection (`Depends(get_current_user_id)`)

**Authorization:**
- User scoping enforced at DB query level: `.eq("user_id", user_id)` — users can only access their own data
- Ad account ownership verified: route checks user owns the account before allowing operations
- No role-based access control (RBAC) detected — all authenticated users have same permissions

---

*Architecture analysis: 2026-02-27*
