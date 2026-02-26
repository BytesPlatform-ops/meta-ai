# Codebase Structure

**Analysis Date:** 2026-02-27

## Directory Layout

```
/Users/bytes/Desktop/marketing/
├── meta-ads-saas/                          # Main project root
│   ├── frontend/                           # Next.js React frontend
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   ├── tailwind.config.js
│   │   ├── next.config.js
│   │   ├── src/
│   │   │   ├── app/                        # Next.js App Router
│   │   │   │   ├── page.tsx                # Home landing page
│   │   │   │   ├── layout.tsx              # Root layout
│   │   │   │   ├── globals.css             # Global styles (Tailwind)
│   │   │   │   ├── api/                    # API routes directory (unused currently)
│   │   │   │   ├── auth/                   # Auth pages
│   │   │   │   │   └── login/
│   │   │   │   │       └── page.tsx        # Login form
│   │   │   │   └── dashboard/              # Dashboard pages
│   │   │   │       ├── page.tsx            # Main dashboard
│   │   │   │       ├── accounts/           # Ad accounts management
│   │   │   │       │   └── page.tsx
│   │   │   │       └── settings/           # User settings, Meta OAuth
│   │   │   │           └── page.tsx
│   │   │   ├── components/
│   │   │   │   ├── layout/                 # Layout components (header, nav)
│   │   │   │   └── ui/                     # Reusable UI components
│   │   │   │       ├── AdAccountCard.tsx   # Ad account display component
│   │   │   │       └── ConnectMetaButton.tsx  # Meta OAuth trigger button
│   │   │   └── lib/                        # Utilities and clients
│   │   │       ├── api.ts                  # Typed Axios HTTP client
│   │   │       └── supabase/
│   │   │           ├── client.ts           # Client-side Supabase (browser)
│   │   │           └── server.ts           # Server-side Supabase (RSC)
│   │   └── node_modules/
│   │
│   ├── backend/                            # FastAPI Python backend
│   │   ├── requirements.txt                # Python dependencies
│   │   ├── .env                            # Environment variables (secrets)
│   │   ├── .env.example                    # Template for .env
│   │   ├── Dockerfile                      # Container build config
│   │   └── app/
│   │       ├── __init__.py
│   │       ├── main.py                     # FastAPI app + router registration
│   │       ├── core/                       # Cross-cutting concerns
│   │       │   ├── __init__.py
│   │       │   ├── config.py               # Environment configuration (Pydantic Settings)
│   │       │   ├── security.py             # JWT verification
│   │       │   └── state_token.py          # CSRF-safe OAuth state generation
│   │       ├── api/
│   │       │   ├── __init__.py
│   │       │   ├── deps.py                 # Dependency injection (auth)
│   │       │   └── routes/
│   │       │       ├── __init__.py
│   │       │       ├── oauth.py            # Meta OAuth endpoints
│   │       │       ├── campaigns.py        # Campaign management endpoints
│   │       │       └── products.py         # Product CRUD endpoints
│   │       ├── services/
│   │       │   ├── __init__.py
│   │       │   ├── meta_oauth.py           # Meta OAuth 2.0 workflow
│   │       │   └── mcp_client.py           # MCP JSON-RPC client wrapper
│   │       └── db/
│   │           ├── __init__.py
│   │           └── supabase_client.py      # Supabase client singleton
│   │
│   ├── mcp-server/                         # External MCP server (not analyzed in detail)
│   │
│   └── supabase/
│       └── migrations/                     # Database schema migrations
│
└── .planning/
    └── codebase/                           # Analysis documents
        ├── ARCHITECTURE.md
        └── STRUCTURE.md (this file)
```

## Directory Purposes

**Frontend Root (`frontend/`):**
- Purpose: Next.js web application, entry point for end users
- Contains: Package config, source code, build outputs
- Key files: `package.json`, `tsconfig.json`, `next.config.js`, `src/`

**Frontend App Router (`frontend/src/app/`):**
- Purpose: Next.js App Router directory — file-based routing system
- Contains: Page files (`page.tsx`), layout files (`layout.tsx`), styles
- Key files: Root `page.tsx` (home), `layout.tsx` (shell), auth and dashboard subdirectories

**Frontend Components (`frontend/src/components/`):**
- Purpose: Reusable React components (UI atoms, molecules, layouts)
- Contains: Functional components, typically co-located with child styles
- Key files: `ui/AdAccountCard.tsx`, `ui/ConnectMetaButton.tsx`, `layout/` components

**Frontend Lib (`frontend/src/lib/`):**
- Purpose: Utilities, clients, and helpers
- Contains: HTTP client, Supabase client configuration, API type definitions
- Key files: `api.ts` (typed API wrapper), `supabase/client.ts`, `supabase/server.ts`

**Backend App (`backend/app/`):**
- Purpose: FastAPI application code and business logic
- Contains: Main app entry, routes, services, database, core utilities
- Key files: `main.py`, route files, service modules

**Backend Core (`backend/app/core/`):**
- Purpose: Configuration and cross-cutting concerns shared across all layers
- Contains: Environment config, security utilities, token generation
- Key files: `config.py`, `security.py`, `state_token.py`

**Backend API Routes (`backend/app/api/routes/`):**
- Purpose: HTTP endpoint handlers organized by feature domain
- Contains: Route handlers, request/response models (Pydantic), endpoint logic
- Key files: `oauth.py`, `campaigns.py`, `products.py`

**Backend Services (`backend/app/services/`):**
- Purpose: Business logic and orchestration; abstracts external API calls
- Contains: Meta OAuth workflow, MCP client wrapper
- Key files: `meta_oauth.py`, `mcp_client.py`

**Backend Database (`backend/app/db/`):**
- Purpose: Data persistence and database client management
- Contains: Supabase client singleton (no ORM, raw Supabase SDK)
- Key files: `supabase_client.py`

**Supabase Migrations (`supabase/migrations/`):**
- Purpose: Version-controlled database schema
- Contains: SQL migration files for creating tables, indexes, policies
- Example: `ad_accounts`, `products`, `campaign_logs` tables

## Key File Locations

**Entry Points:**

- `frontend/src/app/page.tsx` — Home page
- `frontend/src/app/layout.tsx` — Root layout (HTML shell, metadata)
- `frontend/src/app/auth/login/page.tsx` — Login form
- `frontend/src/app/dashboard/page.tsx` — Main dashboard
- `frontend/src/app/dashboard/settings/page.tsx` — Settings + Meta OAuth UI
- `backend/app/main.py` — FastAPI app initialization + router setup

**Configuration:**

- `frontend/package.json` — Frontend dependencies and scripts
- `frontend/tsconfig.json` — TypeScript compiler config with `@/*` path alias
- `backend/requirements.txt` — Python dependencies
- `backend/app/core/config.py` — Environment variables (Pydantic Settings)

**Core Logic:**

- `backend/app/services/meta_oauth.py` — Meta OAuth 2.0 workflow (6 steps)
- `backend/app/services/mcp_client.py` — MCP server JSON-RPC wrapper
- `backend/app/api/routes/oauth.py` — Meta OAuth HTTP endpoints
- `backend/app/api/routes/campaigns.py` — Campaign management endpoints
- `backend/app/api/routes/products.py` — Product CRUD endpoints
- `frontend/src/lib/api.ts` — Typed HTTP client with JWT auto-injection

**Testing:**

- Not detected — no test files present in codebase

## Naming Conventions

**Frontend Files:**

- Pages: `page.tsx` (Next.js convention; must be named exactly this)
- Layouts: `layout.tsx` (Next.js convention; applied to directory and children)
- Components: PascalCase + `.tsx` — `AdAccountCard.tsx`, `ConnectMetaButton.tsx`
- Utilities: camelCase + `.ts` — `api.ts`, `client.ts`
- Styles: Tailwind CSS classes inline in JSX; global styles in `globals.css`

**Frontend Directories:**

- Feature pages: kebab-case — `auth/`, `dashboard/`, `settings/`
- Component categories: kebab-case — `components/ui/`, `components/layout/`
- Utilities: `lib/` (standard Next.js convention)

**Backend Files:**

- Routes: kebab-case + `.py` — `oauth.py`, `campaigns.py`, `products.py`
- Services: snake_case + `.py` — `meta_oauth.py`, `mcp_client.py`
- Modules: snake_case + `.py` — `config.py`, `security.py`, `state_token.py`

**Backend Directories:**

- Feature modules: kebab-case (within Python packages) — `api/routes/`, `services/`, `db/`

**Database Tables:**

- PascalCase in code references, snake_case in actual Supabase — `.table("ad_accounts")`, `.table("campaign_logs")`
- Example tables: `ad_accounts`, `products`, `campaign_logs`, `users` (Supabase Auth)

## Where to Add New Code

**New Frontend Page:**

- Create directory under `/frontend/src/app/{feature-name}/`
- Add `page.tsx` with default export component
- Optionally add `layout.tsx` for route-specific layout
- Example: `/frontend/src/app/analytics/page.tsx` for new analytics view

**New Frontend Component:**

- Reusable component: `/frontend/src/components/ui/{ComponentName}.tsx`
- Layout component: `/frontend/src/components/layout/{ComponentName}.tsx`
- Page-specific component: Co-locate within feature directory (e.g., `app/dashboard/components/`)
- Pattern: Use `"use client"` if interactive; default to server components for SSR

**New Frontend Utility/Helper:**

- Add to `/frontend/src/lib/` or create subdirectory if grouped
- Example: `/frontend/src/lib/validators.ts` for form validation
- Import path: Use `@/lib/...` alias from `tsconfig.json`

**New Backend API Endpoint:**

- Add route handler to appropriate file in `/backend/app/api/routes/`
- If new domain: Create new file (e.g., `reports.py`)
- Register router in `main.py` via `app.include_router()`
- Pattern: Use `Depends(get_current_user_id)` for auth; all endpoints require JWT

**New Backend Service:**

- Create new file in `/backend/app/services/{feature_name}.py`
- Pattern: Module-level async functions for operations; helper functions for sub-steps
- Import from `core/` for config and security; use `get_supabase()` for DB access
- Import into route handler; call via dependency or direct import

**New Backend Core Utility:**

- Add to `/backend/app/core/{utility_name}.py` if cross-cutting
- Examples: New security scheme, new configuration section, new token type
- Export functions for use throughout backend

**Database Schema Changes:**

- Add migration file to `/supabase/migrations/{timestamp}_{description}.sql`
- Pattern: Use Supabase naming convention (auto-generated or follow existing style)
- Changes are applied during deployment; include Row Level Security (RLS) policies if user-scoped

**New Type Definitions:**

- Frontend types: Inline in `page.tsx` or component files where used, or export from separate `.ts` file in `lib/`
- Backend types: Pydantic `BaseModel` classes defined in route file or dedicated `models/` file
- Example: `AdAccount` type exported from `/frontend/src/app/dashboard/settings/page.tsx`

## Special Directories

**`.next/` (Frontend Build Output):**
- Purpose: Next.js build cache and compiled output
- Generated: Yes (by `npm run build`)
- Committed: No (in `.gitignore`)

**`node_modules/` (Frontend Dependencies):**
- Purpose: Installed npm packages
- Generated: Yes (by `npm install`)
- Committed: No (in `.gitignore`)

**`__pycache__/` (Backend Bytecode Cache):**
- Purpose: Python compiled modules cache
- Generated: Yes (by Python runtime)
- Committed: No (in `.gitignore`)

**`supabase/migrations/` (Database Migrations):**
- Purpose: Version-controlled schema changes
- Generated: No (manually written SQL)
- Committed: Yes (source of truth for DB schema)

**`frontend/.env` (Environment Variables):**
- Purpose: Contains secrets and config (API keys, Supabase URLs)
- Generated: No (manually created from `.env.example`)
- Committed: No (in `.gitignore`)
- Note: `.env.example` provides template without secrets

**`backend/.env` (Environment Variables):**
- Purpose: Contains secrets and config for Python backend
- Generated: No (manually created from `.env.example`)
- Committed: No (in `.gitignore`)
- Note: `.env.example` provides template without secrets

---

*Structure analysis: 2026-02-27*
