# Coding Conventions

**Analysis Date:** 2026-02-27

## Naming Patterns

**Files:**
- Frontend components: PascalCase (e.g., `ConnectMetaButton.tsx`, `AdAccountCard.tsx`)
- Frontend pages: lowercase with hyphens for nested routes (e.g., `login/page.tsx`, `dashboard/settings/page.tsx`)
- Backend modules: snake_case (e.g., `meta_oauth.py`, `supabase_client.py`)
- Backend route files: snake_case (e.g., `products.py`, `campaigns.py`, `oauth.py`)
- Config files: snake_case (e.g., `config.py`, `state_token.py`, `security.py`)

**Functions:**
- Frontend: camelCase (e.g., `handleConnect`, `handleDisconnect`, `handleLogin`)
- Backend: snake_case async functions (e.g., `exchange_code_for_token`, `fetch_ad_accounts`, `list_products`)
- Backend private functions: leading underscore + snake_case (e.g., `_raise_for_meta_error`, `_sign`, `_get_account_token`)
- Factory/getter functions: `get_*` prefix (e.g., `get_settings()`, `get_supabase()`, `get_current_user_id()`)

**Variables:**
- Frontend: camelCase (e.g., `email`, `password`, `loading`, `error`, `confirming`, `disconnecting`)
- Backend: snake_case (e.g., `user_id`, `access_token`, `ad_accounts`, `expires_at`)
- Constants: UPPER_SNAKE_CASE (e.g., `API_VERSION`, `META_BASE`, `OAUTH_SCOPES`)
- Type parameters: UPPER_SNAKE_CASE (e.g., `NEXT_PUBLIC_API_URL`, `SUPABASE_SERVICE_ROLE_KEY`)

**Types:**
- Frontend: PascalCase (e.g., `Props`, `AdAccount`)
- Backend Pydantic models: PascalCase (e.g., `ProductCreate`, `ProductUpdate`, `Settings`)

## Code Style

**Formatting:**
- Frontend: uses Tailwind CSS for styling (utility classes)
- Backend: Python with standard line breaks and indentation
- No explicit prettier/eslint config detected; relying on Next.js defaults and TypeScript strict mode

**Linting:**
- Frontend: `next lint` (ESLint via Next.js)
- Backend: No linter detected; style enforced manually

**TypeScript:**
- `strict: true` in `tsconfig.json` - strict type checking enabled
- `skipLibCheck: true` - skip type checking for libraries
- `moduleResolution: "bundler"` - modern module resolution
- Path alias: `@/*` maps to `./src/*` for absolute imports

**Python:**
- Type hints on function signatures (e.g., `def get_supabase() -> Client:`)
- Async functions explicitly marked with `async def`
- Pydantic v2 with `BaseModel` for request/response schemas
- `pydantic_settings.BaseSettings` for configuration management

## Import Organization

**Frontend (TypeScript/React):**
1. React/Next.js imports (e.g., `import { useState } from "react"`)
2. Next.js utilities (e.g., `import Link from "next/link"`)
3. Absolute imports using `@/` alias (e.g., `import { api } from "@/lib/api"`)
4. Type imports with `type` keyword (e.g., `import type { AdAccount } from "@/app/dashboard/settings/page"`)
5. Local relative imports

Example from `ConnectMetaButton.tsx`:
```typescript
"use client";

import { useState } from "react";
import { api } from "@/lib/api";
```

**Backend (Python):**
1. Standard library imports
2. Third-party imports (fastapi, pydantic, httpx, supabase, jwt)
3. Local relative imports from same package

Example from `oauth.py`:
```python
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from ...core.config import get_settings
from ...core.state_token import generate_state, verify_state
```

## Error Handling

**Frontend:**
- Try-catch blocks wrap async API calls
- Set error state as string message: `setError(error?.response?.data?.detail ?? "Failed message")`
- Display errors in UI with `{error && <p className="...text-red-400...">{error}</p>}`
- Distinguish between error types (e.g., network errors vs validation errors)

Example from `ConnectMetaButton.tsx`:
```typescript
try {
  const { data } = await api.getMetaAuthUrl();
  window.location.href = data.authorization_url;
} catch (err: any) {
  setError(err?.response?.data?.detail ?? "Failed to start OAuth flow.");
  setLoading(false);
}
```

**Backend:**
- Use FastAPI `HTTPException` for API errors with status codes
- Wrap external API calls with custom error handling for clarity
- Helper function `_raise_for_meta_error()` extracts Meta API error messages
- Raise `ValueError` for token/signature verification failures
- Raise `RuntimeError` for external API failures with descriptive messages

Example from `meta_oauth.py`:
```python
def _raise_for_meta_error(resp: httpx.Response) -> None:
    """Raise a descriptive RuntimeError when Meta's Graph API returns an error."""
    if resp.is_error:
        try:
            body = resp.json()
            err = body.get("error", {})
            msg = err.get("message") or resp.text
            code = err.get("code", resp.status_code)
            raise RuntimeError(f"Meta API error {code}: {msg}")
        except (ValueError, KeyError):
            resp.raise_for_status()
```

## Logging

**Framework:** Console only (no logging framework detected)

**Patterns:**
- Frontend: No explicit logging; relies on browser console and error boundaries
- Backend: No explicit logging framework; relies on console output

## Comments

**When to Comment:**
- Security-critical sections (e.g., JWT verification, CSRF protection, token exchange)
- Complex multi-step operations (e.g., OAuth callback flow)
- Non-obvious design decisions (e.g., stateless HMAC state tokens instead of session storage)
- Function docstrings for public APIs

**Docstring Pattern:**
- Function: Triple-quoted docstring describing purpose, parameters, and return value
- Module: Top-level docstring explaining the module's role and any key flows

Example from `state_token.py`:
```python
def verify_state(state: str) -> str:
    """
    Verify the state token and return the user_id it contains.
    Raises ValueError on any tampering or malformed input.
    """
```

## Function Design

**Size:**
- Frontend event handlers: 5-20 lines (e.g., `handleConnect`, `handleDisconnect`)
- Backend route handlers: 10-30 lines (logic delegated to service functions)
- Service functions: 10-40 lines (focused on single responsibility)

**Parameters:**
- Frontend: Props passed as single object with destructuring (e.g., `{ account, onDisconnect }`)
- Backend routes: Dependencies injected via FastAPI `Depends()` (e.g., `user_id: str = Depends(get_current_user_id)`)
- Backend services: Explicit parameters matching business domain

**Return Values:**
- Frontend: React components return JSX elements
- Frontend handlers: Async functions return void (set state instead)
- Backend: Routes return JSON-serializable data structures (dicts from Supabase)
- Backend services: Return data from external APIs or DB, wrapped in appropriate types

## Module Design

**Exports:**
- Frontend: Default export for page components (e.g., `export default function LoginPage()`)
- Frontend: Named export for UI components (e.g., `export function ConnectMetaButton()`)
- Backend: `router = APIRouter(...)` for route collections
- Backend: Top-level async functions or class methods for services

**Barrel Files:**
- Frontend: None detected; imports reference specific files
- Backend: `__init__.py` files present but appear empty or minimal

**Client Creation:**
- Frontend Supabase client: Factory function `createClient()` in `lib/supabase/client.ts` - called fresh per-component
- Backend Supabase client: Singleton with `@lru_cache` in `db/supabase_client.py` - `get_supabase()` returns cached instance
- Frontend API client: Singleton `apiClient` with axios and interceptors in `lib/api.ts`

**State Management:**
- Frontend: React hooks (`useState` for component-level state)
- Backend: No client-side state; immutable request/response data flow

## Async Patterns

**Frontend:**
- Event handlers: `const handleX = async (e: React.FormEvent) => { ... }`
- State flags: `loading` and `error` managed with `useState` during async operations
- Router: `useRouter()` from Next.js for navigation after success

**Backend:**
- Route handlers: `async def handler(...) -> ResponseType:`
- Service functions: `async def` for HTTP calls (httpx.AsyncClient)
- Dependency injection: Async dependencies supported via `Depends()`
- DB operations: Supabase client methods are synchronous; wrapped in async routes

## Security Patterns

**Authentication:**
- Frontend: Browser session JWT from Supabase auth
- Backend: JWT verification via `decode_supabase_jwt()` in dependency
- API requests: Axios interceptor attaches token to all requests

**CSRF Protection:**
- Stateless HMAC-signed tokens in OAuth flow
- State token embeds user_id + nonce + signature (base64 encoded)
- Verified via `verify_state()` before trusting extracted user_id

**Secret Management:**
- Environment variables only (never hardcoded)
- Backend: Service-role key kept server-side; anon key exposed to frontend
- Frontend: Only anon key in environment variables

---

*Convention analysis: 2026-02-27*
