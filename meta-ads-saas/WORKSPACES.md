# Multi-Workspace System

## Overview

Each user can have multiple **workspaces** — isolated business environments with their own Meta credentials, products, drafts, campaigns, and settings. Switching workspaces changes the entire dashboard context without logging out.

---

## Database

### `workspaces` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Workspace identifier |
| `user_id` | UUID (FK → users) | Owner |
| `name` | TEXT | Display name (e.g. "NutreoPak", "Client ABC") |
| `meta_ad_account_id` | TEXT | Ad account ID for this workspace |
| `meta_page_id` | TEXT | Facebook Page ID |
| `meta_pixel_id` | TEXT | Conversion pixel ID |
| `meta_ig_actor_id` | TEXT | Instagram account ID |
| `meta_access_token` | TEXT | Workspace-level access token |
| `business_name` | TEXT | Business context (moved from user_preferences) |
| `business_description` | TEXT | |
| `target_audience` | TEXT | |
| `website_url` | TEXT | |
| `target_country` | TEXT | Default 'PK' |
| `industry_niche` | TEXT | |
| `website_intel` | JSONB | Scraped website data |
| `tracking_mode` | TEXT | Default 'whatsapp_cod' |
| `is_active` | BOOLEAN | Default TRUE |

### Foreign keys added to all business tables

Every data table now has a nullable `workspace_id` column:

- `ad_accounts`
- `products`
- `content_drafts`
- `campaign_logs`
- `campaign_suggestions`
- `content_strategies`
- `optimization_proposals`
- `account_audits`
- `lead_forms`

### Auto-creation

A database trigger on `auth.users` INSERT automatically creates a default workspace named "My First Business" for every new user.

### Migration

File: `supabase/migrations/005_workspaces.sql`

1. Creates default workspace per existing user
2. Copies Meta credentials from first ad_account → workspace
3. Copies business context from user_preferences → workspace
4. Backfills `workspace_id` on all existing rows
5. `workspace_id NOT NULL` constraints are commented out for Step 2 (after full backend migration)

---

## Backend — Request-Scoped Workspace

### `get_workspace_id()` dependency (`app/api/deps.py`)

Every route that touches workspace-scoped data injects this dependency:

```python
async def some_endpoint(
    user_id: str = Depends(get_current_user_id),
    workspace_id: str = Depends(get_workspace_id),
):
```

**Resolution priority:**

1. `X-Workspace-Id` header → verify ownership → use it
2. Fallback → user's first workspace (by `created_at`)

All queries then filter by workspace:

```python
supabase.table("products").select("*").eq("workspace_id", workspace_id)
```

### Workspace CRUD (`app/api/routes/workspaces.py`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/workspaces/` | List all user workspaces |
| POST | `/api/v1/workspaces/` | Create workspace |
| GET | `/api/v1/workspaces/{id}` | Get single (ownership verified) |
| PUT | `/api/v1/workspaces/{id}` | Update (Meta creds, business info) |
| DELETE | `/api/v1/workspaces/{id}` | Delete (blocks if last workspace) |

### Token resolution (`app/services/ad_executor.py`)

`_get_workspace_context(draft)` resolves credentials with 3-tier fallback:

1. `workspace.meta_access_token` (workspace-level)
2. `ad_accounts.access_token` WHERE `workspace_id = ...` (workspace ad account)
3. `ad_accounts.access_token` WHERE `user_id = ...` (legacy fallback)

Campaign routes use helper functions:
- `_get_account_token(workspace_id, ad_account_id)` — specific account token
- `_get_first_account(workspace_id)` — first active account for workspace

--
\
## OAuth Flow with Workspace

### State token (`app/core/state_token.py`)

OAuth state embeds both `user_id` and `workspace_id`:

```
payload = "user_uuid|workspace_uuid"
state = base64(payload:nonce:hmac_signature)
```

### Flow

1. **Authorize** — `GET /api/v1/oauth/meta/authorize`
   - Reads `workspace_id` from dependency
   - Generates state with `generate_state(user_id, workspace_id)`
   - Returns Meta authorization URL

2. **Callback** — `GET /api/v1/oauth/meta/callback`
   - `verify_state(state)` → extracts `(user_id, workspace_id)`
   - Exchanges code for long-lived token
   - Saves token to the **correct workspace**
   - Upserts `ad_accounts` with `workspace_id`
   - Redirects to settings with account picker

3. **Account picker** — `GET /api/v1/oauth/meta/available-accounts`
   - Fetches workspace's stored token
   - Returns all Meta ad accounts (flagged `already_linked` if in workspace)

4. **Link accounts** — `POST /api/v1/oauth/meta/link-accounts`
   - Upserts selected accounts into `ad_accounts` with `workspace_id`

### Manual connect (`POST /api/v1/auth/manual-connect`)

Also workspace-aware — updates both `ad_accounts` and `workspaces` table with the provided token.

---

## Frontend

### WorkspaceProvider (`contexts/WorkspaceContext.tsx`)

React context providing:

```typescript
{
  workspaces: Workspace[];
  activeWorkspace: Workspace | null;
  isLoading: boolean;
  switchWorkspace: (id: string) => void;
  refetchWorkspaces: () => Promise<void>;
}
```

- On mount: fetches `/api/v1/workspaces/`, restores last-used from localStorage
- `switchWorkspace()`: saves to localStorage, triggers `window.location.reload()` to force all components to re-fetch with new workspace header

### Header injection (`lib/api.ts`)

Axios interceptor automatically attaches `X-Workspace-Id` to every request:

```typescript
const wsId = localStorage.getItem("meta-ads-active-workspace-id");
if (wsId) {
  config.headers["X-Workspace-Id"] = wsId;
}
```

### Component tree

```
layout.tsx
  └─ WorkspaceShell (provider wrapper)
       └─ Sidebar
            └─ WorkspaceSwitcher (dropdown at top of sidebar)
       └─ {page content}
```

### WorkspaceSwitcher (`components/layout/WorkspaceSwitcher.tsx`)

- Dropdown showing all workspaces with active indicator
- Inline rename (Enter/Escape)
- Delete with confirmation (blocks last workspace)
- **Create New Workspace** — 2-step modal:
  - Step 1: Name, business info, country, audience
  - Step 2: Posting frequency, content tone, budget, placements
  - Creates workspace + saves preferences in one flow

### AccountPickerModal (`components/ui/AccountPickerModal.tsx`)

- Shows after OAuth callback
- Checkbox list of Meta ad accounts
- Saves selection via `POST /link-accounts`

### PagePickerModal (`components/ui/PagePickerModal.tsx`)

- Radio list of Facebook pages (from `/api/v1/meta/identities`)
- Saves to workspace via `PUT /api/v1/workspaces/{id}`

---

## Complete User Flow

### New user

1. Signs up → trigger creates default workspace "My First Business"
2. Lands on dashboard → `WorkspaceProvider` loads workspaces
3. First workspace auto-selected, stored in localStorage
4. All API calls scoped to this workspace

### Connecting Meta

1. User clicks "Connect Meta" in settings
2. Backend generates OAuth state embedding `workspace_id`
3. User authenticates on Meta → callback extracts `workspace_id` from state
4. Token saved to correct workspace → account picker shown
5. User selects ad accounts → linked to workspace

### Switching workspaces

1. User clicks workspace in sidebar switcher
2. localStorage updated, page reloads
3. Axios interceptor sends new `X-Workspace-Id` header
4. All data re-fetches scoped to new workspace
5. Different products, drafts, campaigns, audits appear

### Creating a new workspace

1. User clicks "New Workspace" in switcher
2. Fills 2-step form (business info + preferences)
3. New workspace created → auto-switched
4. User connects Meta account for this workspace separately

---

## Data Isolation Guarantees

| Layer | Mechanism |
|-------|-----------|
| Database | RLS policies: `user_id = auth.uid()` |
| Application | Every query filters `.eq("workspace_id", workspace_id)` |
| Transport | `X-Workspace-Id` header on every request |
| Ownership | `get_workspace_id()` verifies workspace belongs to authenticated user |
| Credentials | Each workspace has its own `meta_access_token` |
| Uniqueness | `(workspace_id, meta_account_id)` constraint on ad_accounts |

---

## Key Files

| File | Purpose |
|------|---------|
| `supabase/docker/init/01-app-schema.sql` | Workspace table + FK columns + RLS |
| `supabase/migrations/005_workspaces.sql` | Migration + data backfill |
| `backend/app/api/routes/workspaces.py` | CRUD endpoints |
| `backend/app/api/deps.py` | `get_workspace_id()` dependency |
| `backend/app/core/state_token.py` | OAuth state with workspace |
| `backend/app/api/routes/oauth.py` | OAuth flow (workspace-aware) |
| `backend/app/services/ad_executor.py` | `_get_workspace_context()` token resolution |
| `frontend/src/contexts/WorkspaceContext.tsx` | React context + localStorage |
| `frontend/src/components/layout/WorkspaceShell.tsx` | Provider wrapper |
| `frontend/src/components/layout/WorkspaceSwitcher.tsx` | Switcher UI + create modal |
| `frontend/src/components/ui/AccountPickerModal.tsx` | Meta account linking |
| `frontend/src/components/ui/PagePickerModal.tsx` | Page selection |
| `frontend/src/lib/api.ts` | `X-Workspace-Id` header injection |
