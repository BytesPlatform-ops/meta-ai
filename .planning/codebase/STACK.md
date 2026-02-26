# Technology Stack

**Analysis Date:** 2026-02-27

## Languages

**Primary:**
- TypeScript 5.x - Frontend (Next.js) with strict type checking
- Python 3.12 - Backend (FastAPI) API server
- SQL - Supabase database migrations and schemas

**Secondary:**
- JavaScript - Next.js configuration, Node.js scripts
- HTML/CSS - Rendered by React/Next.js and Tailwind CSS

## Runtime

**Environment:**
- Node.js 20 (Alpine) - Frontend and tooling
- Python 3.12 (slim) - Backend API server
- Supabase (hosted cloud) - Database and authentication

**Package Manager:**
- npm (Node.js) - Frontend dependencies
- pip (Python) - Backend dependencies
- Lockfile: `package.json` with npm (no package-lock.json detected in repo, docker-compose uses multi-stage build)

## Frameworks

**Core:**
- Next.js 14.2.3 - Frontend framework (React 18 based)
- FastAPI 0.111.0 - Backend REST API framework
- React 18 - UI component library
- Supabase - PostgreSQL database + authentication + real-time

**Styling:**
- Tailwind CSS 3.4.1 - Utility-first CSS framework
- PostCSS 8 - CSS processing

**Charts & UI:**
- Recharts 2.12.6 - Data visualization for dashboards
- Lucide React 0.378.0 - Icon library
- clsx 2.1.1, tailwind-merge 2.3.0 - CSS utility helpers

**Build/Dev:**
- Next.js build system (includes webpack)
- Uvicorn 0.29.0 (with standard extras) - ASGI server for FastAPI

## Key Dependencies

**Critical:**
- @supabase/supabase-js 2.43.4 - Supabase client for frontend authentication and real-time
- @supabase/ssr 0.3.0 - Supabase SSR adapter for Next.js server-side rendering
- supabase 2.4.3 (Python) - Supabase client for backend database access
- axios 1.7.2 - HTTP client for frontend API calls

**Infrastructure:**
- pydantic 2.7.1 - Data validation (FastAPI)
- pydantic-settings 2.2.1 - Configuration management (FastAPI)
- httpx 0.27.0 - Async HTTP client (Python) for Meta Graph API calls
- PyJWT 2.8.0 - JWT token signing/verification for OAuth state tokens
- python-dotenv 1.0.1 - Environment variable loading

**Frontend Utilities:**
- autoprefixer 10.0.1 - CSS vendor prefixes
- eslint 8.x - JavaScript linting
- eslint-config-next 14.2.3 - Next.js ESLint configuration

## Configuration

**Environment:**
- Frontend: `.env` file (git-ignored) with Supabase public keys + API URL
  - `NEXT_PUBLIC_SUPABASE_URL`
  - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
  - `NEXT_PUBLIC_API_URL` (backend URL, defaults to http://localhost:8000)
- Backend: `.env` file (git-ignored) with secrets and service keys
  - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`
  - `META_APP_ID`, `META_APP_SECRET`, `META_REDIRECT_URI`
  - `MCP_SERVER_URL`, `MCP_SERVER_API_KEY`
  - `DEBUG`, `SECRET_KEY`

**Build:**
- `tsconfig.json` - TypeScript configuration at `/Users/bytes/Desktop/marketing/meta-ads-saas/frontend/tsconfig.json`
  - Strict mode enabled, path alias `@/*` → `./src/*`
- `next.config.mjs` - Next.js config with remote image patterns for Meta CDNs
- `tailwind.config.ts` - Tailwind CSS configuration
- Backend: Pydantic Settings (env file based) at `/Users/bytes/Desktop/marketing/meta-ads-saas/backend/app/core/config.py`

## Platform Requirements

**Development:**
- Node.js 20.x (Alpine)
- Python 3.12
- Docker & Docker Compose (for local multi-service dev)
- npm for frontend package management
- pip for backend package management

**Production:**
- Deployment target: Docker containers
  - Frontend: Node.js 20 Alpine with multi-stage build (deps → builder → runner)
  - Backend: Python 3.12 slim with uvicorn ASGI server
- Supabase cloud hosted (no self-hosted database)
- Meta (Facebook) Graph API v19.0

## Containerization

**Docker Compose Stack:**
- `frontend` service - Next.js on port 3000 (hot reload in dev)
- `backend` service - FastAPI on port 8000
- `mcp-server` service - Node.js placeholder on port 8080 (will be Facebook Ads MCP server)
- Network: `app-network` (bridge)

**Dockerfiles:**
- Frontend: `/Users/bytes/Desktop/marketing/meta-ads-saas/frontend/Dockerfile` (multi-stage: deps, builder, runner)
- Backend: `/Users/bytes/Desktop/marketing/meta-ads-saas/backend/Dockerfile` (Python slim base)

---

*Stack analysis: 2026-02-27*
