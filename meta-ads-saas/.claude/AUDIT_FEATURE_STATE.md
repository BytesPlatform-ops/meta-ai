# Account Audit Feature — Implementation State

## Status: NOT STARTED — Context exhausted before implementation began

## What was done this session (prior work)
- Phase 1-4 of the original epic (onboarding wizard, drafts dashboard, MCP execution) — COMPLETE
- Business info added to onboarding wizard — COMPLETE
- Custom budget option added — COMPLETE
- OAuth callback fix (replaced supabase-py upsert with direct httpx POST) — COMPLETE
- OpenAI content generation wired up — COMPLETE
- "Launch Dashboard" network error fixed — COMPLETE

## What needs to be built: Account Audit Feature

### Phase 1: Database Schema
Add to `supabase/docker/init/01-app-schema.sql` (after content_drafts, before GRANT):
```sql
CREATE TABLE IF NOT EXISTS public.account_audits (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    ad_account_id       UUID REFERENCES public.ad_accounts(id) ON DELETE SET NULL,
    total_spend         NUMERIC(12, 2),
    roas                NUMERIC(10, 4),
    winning_ads         JSONB DEFAULT '[]',
    losing_ads          JSONB DEFAULT '[]',
    ai_strategy_report  TEXT,
    status              TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Add trigger, RLS, service_role policy, index
```

### Phase 2: MCP Server Tool
Add `get_account_audit_data` tool to `/Users/bytes/Desktop/marketing/nutreoPak-meta-mcp/server.py`:
- Input: access_token, ad_account_id
- Query: `GET act_{ad_account_id}/insights?level=ad&date_preset=last_30d&fields=ad_name,spend,actions,cost_per_action_type,outbound_clicks_ctr`
- Return: cleaned JSON array of ad performance data

### Phase 3: Backend Service + Route
- Create `backend/app/services/account_auditor.py` — orchestrates MCP call → data analysis → OpenAI report → DB save
- Create `backend/app/api/routes/audits.py` with:
  - `POST /api/v1/audits/sync` — trigger audit
  - `GET /api/v1/audits/latest` — get latest audit
- Register router in `backend/app/main.py`
- Uses patterns from `content_generator.py` (OpenAI) and `mcp_client.py` (MCP calls)

### Phase 4: Frontend
- Create `frontend/src/app/dashboard/AccountAuditWidget.tsx` client component
- Add to dashboard page.tsx (below DashboardStats, above CTA card)
- Shows: Total Spend card, ROAS card, Winning/Losing ads tables, AI Strategy Report (markdown)
- Empty state: "Run Initial Audit" button or "Syncing..." skeleton
- Add `runAudit` and `getLatestAudit` to `frontend/src/lib/api.ts`

## Key patterns to follow
- **DB**: Use `CREATE TABLE IF NOT EXISTS`, idempotent RLS policies, service_role full access
- **Backend OpenAI**: `AsyncOpenAI(api_key=settings.OPENAI_API_KEY)`, model `gpt-4o-mini`
- **MCP client**: `mcp_client.call_tool("tool_name", {args}, access_token)`
- **MCP server tools**: `@mcp.tool()` decorator, `access_token` as first param, use `_get()` helper
- **Frontend**: `glass` utility class, gradient-text, glow-blue, lucide-react icons
- **API client**: axios wrapper at `http://localhost:54562`, auto-attaches JWT
- **Supabase client (backend)**: `get_supabase()` returns service-role client
- **Auth dep**: `user_id: str = Depends(get_current_user_id)`

## Important: Known issues to handle
- supabase-py `.insert()` fails with empty `APIError: {}` — use direct httpx POST to PostgREST instead (see meta_oauth.py pattern)
- Use `datetime.now(timezone.utc).isoformat()` for timestamps, NOT `"now()"`
- Backend runs on port 54562, frontend on 54561
- After schema changes: `docker compose down -v && docker compose up --build -d`
