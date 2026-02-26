# External Integrations

**Analysis Date:** 2026-02-27

## APIs & External Services

**Meta (Facebook) OAuth & Graph API:**
- Service: Meta Developers (facebook.com/dialog/oauth, graph.facebook.com)
- What it's used for: OAuth 2.0 sign-in, ad account management, campaign insights, performance metrics
  - SDK/Client: httpx (Python async HTTP) in `backend/app/services/meta_oauth.py`
  - Auth: `META_APP_ID`, `META_APP_SECRET` (env vars)
  - Scope: `ads_management,ads_read,business_management,pages_read_engagement`
  - API Version: v19.0 (configurable via `META_API_VERSION`)
  - OAuth redirect URI: `http://localhost:8000/api/v1/oauth/meta/callback` (configured in `META_REDIRECT_URI`)

**Facebook Ads MCP Server:**
- Service: Internal JSON-RPC 2.0 MCP (Model Context Protocol) server
- What it's used for: Tool calling for campaign management (create, pause, update), budget optimization, performance analysis
  - SDK/Client: httpx async HTTP in `backend/app/services/mcp_client.py`
  - URL: `MCP_SERVER_URL` (env var, defaults to `http://mcp-server:8080` in docker-compose)
  - Auth: Optional `MCP_SERVER_API_KEY` (env var) passed as Bearer token
  - Protocol: JSON-RPC 2.0 POST requests with `X-Meta-Access-Token` header per-request

## Data Storage

**Databases:**
- PostgreSQL (via Supabase)
  - Host: Supabase cloud (URL in `SUPABASE_URL`)
  - Connection: Service role key in `SUPABASE_SERVICE_ROLE_KEY` (backend only)
  - Client: supabase-py (Python) 2.4.3 in backend, @supabase/supabase-js (JS) in frontend
  - Key tables:
    - `public.users` - User profiles, extended from Supabase auth
    - `public.ad_accounts` - Meta ad account links with long-lived OAuth tokens
    - `public.products` - Product catalog for ad creative generation
    - `public.campaign_logs` - Immutable audit trail of all AI-driven Meta actions
  - Row-level security (RLS): All tables use RLS policies scoped to authenticated user (auth.uid())
  - Migrations: SQL in `/Users/bytes/Desktop/marketing/meta-ads-saas/supabase/migrations/001_initial_schema.sql`

**File Storage:**
- Meta CDN for images: Facebook/Instagram CDNs (via Next.js remote image patterns)
  - Remote patterns configured in `next.config.mjs`:
    - `**.fbcdn.net` (Facebook CDN)
    - `**.cdninstagram.com` (Instagram CDN)
  - Product images stored as URLs in `public.products.image_url`
  - User avatars stored as URLs in `public.users.avatar_url`

**Caching:**
- No explicit caching service detected (Redis, Memcached)
- Browser session caching via Supabase SSR

## Authentication & Identity

**Auth Provider:**
- Supabase Auth (built-in PostgreSQL auth)
  - Implementation: Supabase native auth (email/password signup)
  - Frontend: @supabase/ssr package for browser client
  - Backend: JWT verification via `PyJWT` in `backend/app/core/security.py`
  - OAuth integration: Meta OAuth 2.0 redirects to `/api/v1/oauth/meta/callback`

**Auth Flow:**
1. User signs up via Supabase Auth (frontend)
2. JWT token issued and stored in browser session
3. Frontend attaches JWT as `Authorization: Bearer <token>` via axios interceptor (`frontend/src/lib/api.ts`)
4. Backend validates JWT in `app/api/deps.py` using `get_current_user_id()`
5. Meta OAuth optional: User can connect Meta ad accounts via callback route
6. OAuth state token: HMAC-signed token (no server session required) in `backend/app/core/state_token.py`

**Secrets:**
- Location: Environment variables (`.env` files, git-ignored)
- Backend: `SUPABASE_SERVICE_ROLE_KEY` (never exposed to frontend)
- Frontend: `NEXT_PUBLIC_SUPABASE_ANON_KEY` (safe for browser)

## Monitoring & Observability

**Error Tracking:**
- Not detected - no Sentry, DataDog, or similar integration

**Logs:**
- Python logging: Not explicitly configured, defaults to uvicorn stdout
- Audit trail: Immutable `public.campaign_logs` table captures all AI-driven Meta actions with:
  - `ai_model` - Which AI model triggered the action
  - `ai_reasoning` - AI explanation for the action
  - `payload` - Full request to Meta API
  - `result` - Response / performance snapshot
  - `status` - success/failed/pending

## CI/CD & Deployment

**Hosting:**
- Docker containers (frontend and backend)
- Supabase cloud (database)
- MCP server: Placeholder for Facebook Ads MCP (currently Node.js placeholder)

**CI Pipeline:**
- Not detected - no GitHub Actions, GitLab CI, or similar

**Build Process:**
- Frontend: Docker multi-stage (deps → builder → runner)
- Backend: Docker Python image with pip install from requirements.txt

## Environment Configuration

**Required env vars:**

**Frontend (.env):**
- `NEXT_PUBLIC_SUPABASE_URL` - Supabase project URL
- `NEXT_PUBLIC_SUPABASE_ANON_KEY` - Supabase anonymous key (safe for browser)

**Backend (.env):**
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY` - Supabase service role (backend only)
- `SUPABASE_ANON_KEY` - Supabase anonymous key
- `META_APP_ID` - Meta app ID from Facebook Developers
- `META_APP_SECRET` - Meta app secret (backend only)
- `META_REDIRECT_URI` - OAuth callback URL
- `META_API_VERSION` - Graph API version (default: v19.0)
- `MCP_SERVER_URL` - MCP server endpoint
- `MCP_SERVER_API_KEY` - Optional MCP auth key
- `DEBUG` - Enable debug mode
- `SECRET_KEY` - FastAPI secret key

**Secrets location:**
- `.env` files (one per service, git-ignored)
- Environment variables injected at runtime (docker-compose passes via env_file)
- No external secret management detected (e.g., AWS Secrets Manager, HashiCorp Vault)

## Webhooks & Callbacks

**Incoming:**
- `/api/v1/oauth/meta/callback` - Meta OAuth redirect endpoint (`backend/app/api/routes/oauth.py`)
  - Receives: `code`, `state`, `error`, `error_description` query params
  - Workflow: Validates HMAC-signed state → exchanges code for token → fetches ad accounts → stores in Supabase
  - Redirects browser to frontend with success/error params

**Outgoing:**
- None detected - No webhooks sent to external services
- MCP server is called synchronously (not via webhook)

## Data Models

**ad_accounts table:**
- Stores encrypted/long-lived Meta ad account OAuth tokens
- Fields: `user_id`, `meta_account_id`, `account_name`, `access_token`, `token_expires_at`, `currency`, `timezone`, `is_active`
- Used by: Meta OAuth service for token refresh, MCP client for scoped API calls

**campaign_logs table:**
- Immutable audit trail of AI-driven actions
- Fields: `user_id`, `ad_account_id`, `product_id`, `action` (enum), `meta_campaign_id`, `meta_adset_id`, `meta_ad_id`, `payload`, `result`, `roas`, `spend`, `revenue`, `ai_model`, `ai_reasoning`, `status`, `error_message`
- Used by: Backend to log all Meta API calls and outcomes

---

*Integration audit: 2026-02-27*
