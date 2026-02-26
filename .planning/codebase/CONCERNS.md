# Codebase Concerns

**Analysis Date:** 2026-02-27

## Tech Debt

**Weak JWT Verification Strategy:**
- Issue: In `/Users/bytes/Desktop/marketing/meta-ads-saas/backend/app/core/security.py`, the JWT decoder uses `options={"verify_aud": False}` which disables audience verification. Additionally, `SUPABASE_SERVICE_ROLE_KEY` is being used to decode user tokens in line 17, which is the server-side secret key and should not be used for validating user-issued JWTs.
- Files: `backend/app/core/security.py` (line 17-19)
- Impact: Tokens from other services or malformed tokens could be accepted. Using the service role key for verification creates a security mismatch—user tokens should be verified with the public/anon key instead.
- Fix approach: Use `SUPABASE_ANON_KEY` (public key) to decode user JWTs instead of `SUPABASE_SERVICE_ROLE_KEY`. Enable audience verification by removing `verify_aud: False` or explicitly setting audience to match Supabase project ID.

**Missing Default SECRET_KEY in Production:**
- Issue: In `backend/app/core/config.py` line 12, `SECRET_KEY` defaults to `"change-me-in-production"` which is a hardcoded placeholder.
- Files: `backend/app/core/config.py` (line 12)
- Impact: If `.env` is not properly configured in production, OAuth state tokens will be signed with a weak, known secret, completely invalidating CSRF protection. State tokens could be forged by attackers.
- Fix approach: Make `SECRET_KEY` required (no default value) and add startup validation in `main.py` that raises an error if `SECRET_KEY == "change-me-in-production"` or is missing.

**Silent Error Suppression in Settings Page:**
- Issue: In `frontend/src/app/dashboard/settings/page.tsx` line 48, the catch block silently swallows errors when loading ad accounts: `catch { /* User might not have any accounts yet — not an error state */ }`. This assumes empty results equal success, but actual API errors are hidden.
- Files: `frontend/src/app/dashboard/settings/page.tsx` (lines 44-52)
- Impact: Network failures, 500 errors, and permission issues are indistinguishable from "no accounts connected." Users won't know if the system is broken.
- Fix approach: Distinguish between 404/empty response (OK) and actual errors (5xx, network timeout). Log errors to console or error tracking. Show different UI message for "failed to load" vs "no accounts."

**Error Handling in Disconnect Flow:**
- Issue: In `frontend/src/app/dashboard/settings/page.tsx` line 60, `handleDisconnect` doesn't wrap the API call in try-catch. If the disconnect fails, the state is updated anyway (line 61), leaving the UI and backend out of sync.
- Files: `frontend/src/app/dashboard/settings/page.tsx` (lines 59-62)
- Impact: User sees account removed from UI, but backend still has the active token. User could accidentally use the old token, or reconnecting becomes confused with stale records.
- Fix approach: Wrap `api.disconnectAdAccount()` in try-catch. Only update state if delete succeeds. Show error toast on failure.

**Unhandled Promise in ConnectMetaButton:**
- Issue: In `frontend/src/components/ui/ConnectMetaButton.tsx` line 16, `window.location.href` assignment doesn't return or error-check. The catch block (lines 17-20) sets `loading` back to false, but if an error occurs, the redirect never happens and user sees no feedback beyond error text.
- Files: `frontend/src/components/ui/ConnectMetaButton.tsx` (lines 10-21)
- Impact: If OAuth fails silently (network timeout, CORS error), button stays disabled and user must refresh to retry.
- Fix approach: Add retry logic or more explicit error states. Consider using `router.push()` instead of `window.location.href` so errors can be caught by React's error boundary.

**Supabase Service Role Key Exposure Risk:**
- Issue: In `backend/app/db/supabase_client.py`, the service role key is cached at module level (line 14) without expiration or rotation policy. If credentials are compromised, there's no way to invalidate the cached instance.
- Files: `backend/app/db/supabase_client.py` (lines 13-14)
- Impact: A compromised SUPABASE_SERVICE_ROLE_KEY gives attackers full write access to all tables for all users. No audit trail of key compromise.
- Fix approach: Implement credential rotation mechanism. Consider using short-lived tokens from Supabase Auth API instead of long-lived service role keys. Add logging of all Supabase mutations.

## Known Bugs

**Token Expiration Not Enforced on Reads:**
- Symptoms: Ad accounts with expired tokens can still be listed and used in the UI. The token expiry is only displayed as a warning in `AdAccountCard` (line 21) but the backend doesn't validate token freshness before using it.
- Files: `frontend/src/components/ui/AdAccountCard.tsx` (lines 15-21), `backend/app/api/routes/campaigns.py` (lines 13-26)
- Trigger: Navigate to settings page after a token expires (token_expires_at < now). The account still appears usable and can be selected for campaign operations, which will then fail at the MCP client.
- Workaround: Manually disconnect and reconnect the account before token expires. Frontend warns at 14 days but doesn't auto-reconnect.

**Product Delete Missing Error Handling:**
- Symptoms: Calling DELETE `/api/v1/products/{product_id}` does not check if the delete succeeded. If the row doesn't exist or user isn't the owner, no error is raised.
- Files: `backend/app/api/routes/products.py` (lines 68-73)
- Trigger: DELETE a non-existent product or another user's product. API returns 204 with no error.
- Workaround: None—user is misled into thinking deletion succeeded.

**Campaign Logs Table Upsert Without Exists Check:**
- Symptoms: In `campaigns.py` line 56-62, campaign logs are inserted after a pause action, but there's no guarantee the `campaign_logs` table exists or has the correct schema.
- Files: `backend/app/api/routes/campaigns.py` (lines 56-62)
- Trigger: Call pause_campaign on a deployment where `campaign_logs` table is missing or has different columns.
- Workaround: Pre-create table with exact schema. No migration validation.

## Security Considerations

**Meta Redirect URI Hardcoding:**
- Risk: In `backend/app/core/config.py` line 22, `META_REDIRECT_URI` defaults to `"http://localhost:8000/api/v1/oauth/meta/callback"`. If not overridden in production, redirects will fail in any non-localhost environment. More critically, an attacker could intercept localhost redirects on a shared server.
- Files: `backend/app/core/config.py` (line 22)
- Current mitigation: Must override via env var, but no validation that it matches Meta app settings.
- Recommendations: Add validation that `META_REDIRECT_URI` must be HTTPS in production. Compare against Meta's registered callback URLs at startup. Log auth failures to detect hijack attempts.

**CORS Allows All Methods:**
- Risk: In `backend/app/main.py` line 20, CORS is configured with `allow_methods=["*"]`, which allows DELETE, PUT, PATCH from any origin if the origin is in `ALLOWED_ORIGINS`.
- Files: `backend/app/main.py` (line 20)
- Current mitigation: None—POST/DELETE/PATCH are wide open to any ALLOWED_ORIGINS site. Origin spoofing is not a concern if ALLOWED_ORIGINS is tightly controlled.
- Recommendations: Explicitly list methods: `["GET", "POST", "OPTIONS", "DELETE"]`. Add rate limiting per user/IP. Log all mutation operations.

**No API Request Logging or Audit Trail:**
- Risk: No middleware logs API calls, errors, or state mutations. If a security breach occurs, there's no way to audit what was accessed or modified.
- Files: All routes in `backend/app/api/routes/`
- Current mitigation: None.
- Recommendations: Add logging middleware that records: user_id, method, path, status code, errors. Store logs outside the main database to prevent tampering. Implement request signing / audit log immutability.

**Meta Access Tokens Stored in Plaintext:**
- Risk: In `backend/app/services/meta_oauth.py` line 136, long-lived access tokens are stored directly in Supabase `ad_accounts.access_token` column with no encryption.
- Files: `backend/app/services/meta_oauth.py` (lines 131-149)
- Current mitigation: Tokens are server-side only (not sent to browser), but if Supabase DB is breached, attacker gains direct access to Meta Ads API for all connected accounts.
- Recommendations: Encrypt tokens at rest using a KMS or Vault. Rotate tokens regularly (before 60-day expiry). Use `[redacted]` in logs. Implement token rotation without user action.

**User ID Extracted from JWT Without Type Safety:**
- Risk: In `backend/app/api/deps.py` line 17, `user_id` is extracted from JWT payload with `.get("sub")` and could be None. While line 18 checks for None, the type system doesn't enforce this at call sites—developers could forget the check.
- Files: `backend/app/api/deps.py` (lines 12-20)
- Current mitigation: HTTPException is raised if user_id is missing, but errors are not logged with enough context.
- Recommendations: Add type annotation clarifying this returns a non-None str. Add logging of failed auth attempts. Consider raising more specific exceptions (InvalidToken vs Unauthorized).

## Performance Bottlenecks

**No Pagination in Account/Product Listings:**
- Problem: In `backend/app/api/routes/oauth.py` (lines 98-115) and `products.py` (lines 26-37), all accounts/products are fetched without limit. If a user has thousands of accounts or products, query and transfer times explode.
- Files: `backend/app/api/routes/oauth.py` (lines 105-115), `backend/app/api/routes/products.py` (lines 29-36)
- Cause: No `.limit()` or cursor-based pagination applied.
- Improvement path: Add optional `limit` and `offset` query params. Use Supabase RLS (row-level security) to filter at DB level. Implement cursor-based pagination for large result sets.

**MCP Client Has 30s Timeout, No Retry Logic:**
- Problem: In `backend/app/services/mcp_client.py` line 60, httpx client has `timeout=30.0` but no retry logic. A single transient network hiccup kills the request.
- Files: `backend/app/services/mcp_client.py` (lines 60-72)
- Cause: No exponential backoff or circuit breaker.
- Improvement path: Wrap calls in tenacity/backoff decorator. Implement circuit breaker for MCP server failures. Add request tracing to detect slow calls.

**No Caching of OAuth Authorization URL:**
- Problem: Every time user clicks "Connect with Facebook," backend generates a new state token and builds a new auth URL. If user navigates away and back, the previous state is discarded.
- Files: `backend/app/api/routes/oauth.py` (lines 24-35)
- Cause: Stateless design—no session to remember in-flight auth attempts.
- Improvement path: Cache authorization URLs keyed by user_id in Redis with short TTL (5 min). Allow user to resume incomplete auth without regenerating state.

## Fragile Areas

**OAuth State Token Relies on Global SECRET_KEY:**
- Files: `backend/app/core/state_token.py` (lines 21, 24-26)
- Why fragile: The HMAC signing uses a single global `SECRET_KEY`. If that key changes (deployment, rotation, env var typo), all in-flight OAuth authorizations become invalid and users see "CSRF attack" errors on callback.
- Safe modification: Never rotate SECRET_KEY without handling in-flight tokens. Consider versioning the key (e.g., include key version in state token format). Add graceful degradation for key rollover.
- Test coverage: No tests for state token verification. No tests for malformed/tampered tokens. No boundary tests for 60-day token expiry.

**MCP Client Assumes Server Availability:**
- Files: `backend/app/services/mcp_client.py` (lines 41-72)
- Why fragile: No health check before calling. If MCP server is down, users see 502 errors with raw MCP error messages, no fallback, no graceful degradation.
- Safe modification: Add startup health check in main.py. Implement circuit breaker—after N failures, fast-fail with "service temporarily unavailable" instead of timeout. Cache last successful MCP responses.
- Test coverage: No integration tests with mock MCP server. No failure scenario tests (server 500, timeout, malformed response).

**Frontend Supabase Client Initialization:**
- Files: `frontend/src/lib/supabase/client.ts` (lines 4-7)
- Why fragile: Client is re-initialized on every component mount. If env vars are missing, error is thrown at render time with no fallback.
- Safe modification: Initialize client once at app level in root layout or middleware. Add error boundary to catch initialization failures. Validate env vars at build time.
- Test coverage: No tests for missing SUPABASE_URL or SUPABASE_ANON_KEY. No tests for offline scenarios.

**Settings Page Banner Auto-Dismiss:**
- Files: `frontend/src/app/dashboard/settings/page.tsx` (lines 75-91)
- Why fragile: Banner state is local, so if user refreshes the page, success/error message disappears. User won't know if the operation completed.
- Safe modification: Persist banner state to URL query params. Move banner to a toast notification system that survives page reloads. Add server-side confirmation by checking token validity on page load.
- Test coverage: No tests for banner lifecycle. No tests for concurrent connect/disconnect operations.

## Scaling Limits

**Supabase Database Scalability Assumptions:**
- Current capacity: Single Supabase project with no sharding. Row-level security (RLS) policies are not visible in code, so DB query patterns are unknown.
- Limit: If users have >10k ad accounts or >10k products, unindexed queries will degrade. If a single account has >100k campaign logs, inserts become slow.
- Scaling path: Add indexes on (user_id, created_at) for queries. Implement table partitioning in Supabase. Archive old campaign logs to cold storage (S3). Consider horizontal sharding by region.

**MCP Server Single Instance:**
- Current capacity: One MCP server instance at `MCP_SERVER_URL`.
- Limit: If multiple users call campaign operations concurrently, MCP server queue backs up. No load balancer in config.
- Scaling path: Deploy MCP server replicas with load balancer. Implement request queuing with priority. Add observability (traces, metrics) to detect bottlenecks.

**No Request Queuing or Rate Limiting:**
- Current capacity: FastAPI default settings allow unlimited concurrent requests.
- Limit: A single user making 1000 requests/sec can exhaust the server or Supabase connection pool.
- Scaling path: Add rate limiting middleware (e.g., slowapi). Implement per-user token bucket. Add request queuing with backpressure.

## Dependencies at Risk

**PyJWT Version 2.8.0 (Outdated):**
- Risk: PyJWT 2.8.0 is from early 2024. If a JWT algorithm vulnerability is discovered, upgrade path is blocked until requirements.txt is updated.
- Impact: Potential crypto vulnerabilities in JWT handling.
- Migration plan: Pin to latest PyJWT (e.g., 3.x if available). Add dependency update automation via Dependabot. Test JWT signing/verification after upgrade.

**Next.js 14.2.3 (Not Latest):**
- Risk: Next.js 14.2.3 is mid-2024. Newer versions may have security patches or breaking changes.
- Impact: Unpatched security holes in routing, server actions, or middleware.
- Migration plan: Upgrade to Next.js 15.x (latest). Run full test suite. Check for breaking changes in `next/navigation` and `next.config.js`.

**Supabase JS SDK 2.43.4 (Not Latest):**
- Risk: Older version may have auth or RLS bugs.
- Impact: Potential auth bypass or data leakage.
- Migration plan: Upgrade to latest `@supabase/supabase-js` and `@supabase/ssr`. Run integration tests with real Supabase instance.

## Missing Critical Features

**No Refresh Token Rotation:**
- Problem: Meta long-lived tokens expire after ~60 days. Users must manually reconnect to refresh. No automatic refresh before expiry.
- Blocks: Long-running AI agents that rely on stable token access. Users forget to reconnect and campaigns fail silently.
- Improvement path: Implement background job that refreshes tokens 7 days before expiry. Notify users of upcoming reconnect. Handle token refresh errors gracefully.

**No Observability / Error Tracking:**
- Problem: Errors are logged to stdout/stderr. No centralized error tracking (Sentry, DataDog, etc.). If a user's operation fails, we have no way to debug it post-hoc.
- Blocks: Troubleshooting production issues. Understanding failure patterns. Proactive alerting.
- Improvement path: Integrate Sentry or similar error tracking. Add structured logging with request ID / user ID / trace ID. Implement APM for performance monitoring.

**No Admin Dashboard or Operational Tools:**
- Problem: No way for ops to view user accounts, audit logs, or disconnect/reconnect tokens without directly accessing the database.
- Blocks: Supporting customers. Investigating abuse or fraud. Managing compliance audits.
- Improvement path: Build admin panel to list users, view connection history, manually disconnect accounts, inspect campaign logs.

**No Webhook Support for Meta Events:**
- Problem: Token expiry is only checked when user views the settings page. If token expires while user is offline, reconnect is delayed.
- Blocks: Real-time notifications of token expiry. Proactive refreshes.
- Improvement path: Set up Meta webhook to notify on token expiry. Implement push notifications to user's app.

## Test Coverage Gaps

**OAuth Flow Entirely Untested:**
- What's not tested: State token generation/verification. OAuth callback handling. Token exchange. Expired token handling.
- Files: `backend/app/core/state_token.py`, `backend/app/services/meta_oauth.py`, `backend/app/api/routes/oauth.py`
- Risk: A CSRF vulnerability, token expiry bug, or state parsing error could go unnoticed until production.
- Priority: **High** — OAuth is security-critical.

**Frontend Error Scenarios:**
- What's not tested: Network timeout during login. API 500 errors. Missing env vars. Supabase auth failures.
- Files: `frontend/src/app/auth/login/page.tsx`, `frontend/src/lib/supabase/client.ts`
- Risk: Silent failures. Stuck loaders. Confusing error messages.
- Priority: **High** — Directly impacts user experience.

**Campaign Operations (Pause, Get Insights):**
- What's not tested: MCP client failures. Campaign not found. User doesn't have access to ad account. Concurrent operations.
- Files: `backend/app/services/mcp_client.py`, `backend/app/api/routes/campaigns.py`
- Risk: Cascading failures. Race conditions. Data inconsistency.
- Priority: **High** — Core business logic.

**Database Mutations (Product Create/Update/Delete):**
- What's not tested: Constraint violations (e.g., duplicate name). User ownership checks. Transaction failures. Soft delete consistency.
- Files: `backend/app/api/routes/products.py`
- Risk: Data corruption. Security bypass (users modifying others' products).
- Priority: **Medium** — Less critical but still important.

**JWT Verification:**
- What's not tested: Expired tokens. Malformed tokens. Missing sub claim. Wrong algorithm. Token from wrong Supabase project.
- Files: `backend/app/core/security.py`, `backend/app/api/deps.py`
- Risk: Auth bypass. Accepting forged tokens.
- Priority: **High** — Foundation of security.

---

*Concerns audit: 2026-02-27*
