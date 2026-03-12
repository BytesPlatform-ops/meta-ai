# Meta Ads AI — SaaS Platform

AI-powered Meta Ads management platform. Connect your Facebook Ad Accounts, let the AI optimize campaigns in real-time, and track ROAS through a clean dashboard.

---

## Tech Stack

| Layer      | Technology                          |
|------------|-------------------------------------|
| Frontend   | Next.js 14 (App Router), TypeScript, Tailwind CSS |
| Backend    | FastAPI (Python 3.12), Pydantic v2  |
| Database   | Supabase (PostgreSQL + Auth + RLS)  |
| AI/MCP     | Facebook Ads MCP Server (JSON-RPC 2.0) |
| Auth       | Supabase Auth + Meta OAuth 2.0      |
| Infra      | Docker Compose                      |

---

## Project Structure

```
meta-ads-saas/
├── frontend/                   # Next.js App Router
│   └── src/
│       ├── app/
│       │   ├── page.tsx               # Landing page
│       │   ├── auth/login/page.tsx    # Login
│       │   └── dashboard/
│       │       ├── page.tsx           # Main dashboard
│       │       └── accounts/page.tsx  # Ad account connection
│       └── lib/
│           ├── supabase/              # Supabase client (browser + server)
│           └── api.ts                 # Typed FastAPI client
│
├── backend/                    # FastAPI
│   └── app/
│       ├── main.py                    # App entry point + CORS
│       ├── core/
│       │   ├── config.py              # Settings via pydantic-settings
│       │   └── security.py            # JWT verification
│       ├── db/
│       │   └── supabase_client.py     # Supabase service-role client
│       ├── services/
│       │   ├── meta_oauth.py          # Meta OAuth 2.0 full flow
│       │   └── mcp_client.py          # Facebook Ads MCP JSON-RPC client
│       └── api/routes/
│           ├── oauth.py               # /oauth/meta/authorize + /callback
│           ├── campaigns.py           # Campaign insights + pause
│           └── products.py            # Product CRUD
│
├── supabase/migrations/
│   └── 001_initial_schema.sql  # Full PostgreSQL schema with RLS
│
├── docker-compose.yml
└── README.md
```

---

## Database Schema

### `users`
Extends Supabase `auth.users`. Auto-populated on sign-up via trigger.

### `ad_accounts`
Stores Meta Ad Account IDs and long-lived OAuth tokens per user. Unique constraint on `(user_id, meta_account_id)` prevents duplicates on reconnect.

### `products`
Product catalog used as context for AI ad creative generation.

### `campaign_logs`
Append-only audit trail of every AI action (campaign created/paused, budget changes, ROAS snapshots). Includes `ai_reasoning` field so users can see why the AI took an action.

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- A [Supabase](https://supabase.com) project
- A [Meta Developer App](https://developers.facebook.com) with `ads_management` permissions

### 1. Clone & configure

```bash
git clone <repo>
cd meta-ads-saas

# Root env (Next.js public vars)
cp .env.example .env
# Fill in NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY

# Backend env
cp backend/.env.example backend/.env
# Fill in all values (Supabase service role key, Meta app credentials, etc.)

# Frontend env
cp frontend/.env.local.example frontend/.env.local
# Same Supabase values + API URL
```

### 2. Apply the database schema

In your Supabase dashboard → **SQL Editor**, paste and run:

```
supabase/migrations/001_initial_schema.sql
```

Or use the Supabase CLI:

```bash
supabase db push
```

### 3. Start the stack

```bash
docker compose up --build
```

| Service     | URL                          |
|-------------|------------------------------|
| Frontend    | http://localhost:3000        |
| Backend API | http://localhost:8000/api/docs |
| MCP Server  | http://localhost:8080        |

---

## Meta OAuth Flow

```
Frontend                     Backend                        Meta
   │                            │                             │
   │  GET /api/v1/oauth/meta/   │                             │
   │       authorize            │                             │
   │ ─────────────────────────► │                             │
   │ ◄─────────────────────────  {authorization_url, state}  │
   │                            │                             │
   │  redirect user ──────────────────────────────────────►  │
   │                            │     user grants permission  │
   │  ◄──────────────────────────────── redirect to callback  │
   │                            │                             │
   │         GET /api/v1/oauth/meta/callback?code=...         │
   │ ─────────────────────────► │                             │
   │                            │  exchange code → token ──► │
   │                            │  exchange → long-lived ──► │
   │                            │  fetch ad accounts ──────► │
   │                            │  upsert to Supabase         │
   │  redirect to /dashboard ◄─ │                             │
```

---

## MCP Integration

The `MCPClient` in [backend/app/services/mcp_client.py](backend/app/services/mcp_client.py) communicates with the Facebook Ads MCP server using **JSON-RPC 2.0 over HTTP**.

Each request is scoped to the user by injecting their Meta access token via the `X-Meta-Access-Token` header.

Available tool wrappers:
- `get_campaign_insights(ad_account_id, campaign_id)`
- `create_campaign(ad_account_id, params)`
- `pause_campaign(ad_account_id, campaign_id)`
- `update_ad_budget(ad_account_id, adset_id, daily_budget_cents)`
- `list_tools()` — discover all tools the MCP server exposes

To swap in a real MCP server, update `MCP_SERVER_URL` in `backend/.env`.

---

## API Reference

Auto-generated docs available at **http://localhost:8000/api/docs** (Swagger UI).

Key endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/v1/oauth/meta/authorize` | Get Meta authorization URL |
| `GET`  | `/api/v1/oauth/meta/callback` | OAuth callback handler |
| `GET`  | `/api/v1/products/` | List user's products |
| `POST` | `/api/v1/products/` | Create a product |
| `GET`  | `/api/v1/campaigns/{account_id}/insights/{campaign_id}` | Get campaign ROAS/stats |
| `POST` | `/api/v1/campaigns/{account_id}/pause` | Pause a campaign |

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (never expose to client) |
| `SUPABASE_ANON_KEY` | Anon key |
| `META_APP_ID` | Meta Developer App ID |
| `META_APP_SECRET` | Meta Developer App Secret |
| `META_REDIRECT_URI` | Must match your Meta App's OAuth redirect URI |
| `MCP_SERVER_URL` | Facebook Ads MCP server base URL |
| `MCP_SERVER_API_KEY` | Optional API key for MCP server auth |

### Frontend (`frontend/.env.local`)

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon key |
| `NEXT_PUBLIC_API_URL` | FastAPI backend URL |

---

## Security Notes

- **RLS is enabled** on all tables — users can only read/write their own rows.
- **Service role key** is only used server-side in FastAPI. It is never sent to the browser.
- **Access tokens** are stored in Supabase. In production, consider encrypting them at rest using `pgcrypto`.
- **State parameter** in OAuth flow should be validated against a server-side session store (CSRF protection) — marked as TODO in the callback route.
- **Long-lived Meta tokens** expire after ~60 days. Implement a refresh job to exchange them before expiry.
