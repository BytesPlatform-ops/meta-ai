# Testing Patterns

**Analysis Date:** 2026-02-27

## Test Framework

**Runner:**
- Frontend: Not detected - no Jest, Vitest, or test runner configured
- Backend: Not detected - no pytest, unittest, or test runner configured

**Assertion Library:**
- Frontend: Not applicable
- Backend: Not applicable

**Run Commands:**
```bash
# Frontend
npm run lint              # Run ESLint via Next.js
npm run dev               # Development server (suitable for manual testing)
npm run build             # Build and validate types

# Backend
# No test command detected
uvicorn app.main:app --reload    # Run server locally for manual testing
```

## Test File Organization

**Location:**
- No test files found in codebase
- Frontend: No `__tests__/`, `tests/`, `*.test.tsx`, or `*.spec.tsx` directories
- Backend: No `tests/`, `test_*.py`, or `*_test.py` files

**Naming Convention:**
- Not applicable - no test files exist
- Standard convention would be: `[feature].test.ts` or `[feature].spec.py`

**Structure:**
- Not applicable - no test files present

## Test Structure

**Manual Testing Approach:**
The codebase appears to rely on manual testing rather than automated tests. The architecture supports testing through:

1. **Frontend Development Server:**
   - Next.js dev server with hot reload
   - Browser DevTools for inspecting React state and network calls
   - Manual interaction with UI components

2. **Backend Development Server:**
   - FastAPI automatic OpenAPI documentation at `/api/docs`
   - Interactive API testing via Swagger UI
   - Console output from async operations

**Example: Testing OAuth Flow Manually**

Frontend (`src/app/dashboard/settings/page.tsx`):
```typescript
// Manual testing:
// 1. Click "Connect with Facebook" button in ConnectMetaButton
// 2. Observe api.getMetaAuthUrl() call in Network tab
// 3. Follow redirect to Facebook consent screen
// 4. Verify callback redirects back to /dashboard/settings?connected=true
// 5. Check adAccountCard rendering in browser
```

Backend (`app/api/routes/oauth.py`):
```python
# Manual testing via API docs:
# 1. Visit http://localhost:8000/api/docs
# 2. Authenticate with Bearer token from Supabase session
# 3. Test /api/v1/oauth/meta/authorize -> returns authorization_url
# 4. Verify callback handling with ?code=... and ?state=...
# 5. Check /api/v1/oauth/meta/accounts returns account list
```

## Mocking

**Framework:**
- Frontend: Not configured
- Backend: Not configured

**What Would Need Mocking:**
- Frontend API calls to backend (axios)
- Backend external API calls (httpx to Meta Graph API)
- Backend database calls (Supabase client)
- Frontend Supabase auth operations

**Current Approach:**
- Frontend: Manual testing with real backend (dev server)
- Backend: OpenAPI docs allow testing real Meta API calls (when app is registered)

## Fixtures and Factories

**Test Data:**
- Not implemented
- No factory libraries detected (factory_boy, etc.)

**Recommended Approach for Future Testing:**
Frontend would benefit from fixtures for:
- Mock AdAccount objects (for testing `AdAccountCard`)
- Mock API responses (for testing error states)

Backend would benefit from fixtures for:
- Mock Meta Graph API responses
- Test user data for OAuth callback flow
- Supabase test data

## Coverage

**Requirements:** Not enforced

**Current Coverage:** 0% (no automated tests)

**Critical Paths Without Tests:**
1. **OAuth Security:** State token verification (`core/state_token.py`)
2. **Auth Dependencies:** JWT verification (`api/deps.py`)
3. **API Error Handling:** Meta API error parsing (`services/meta_oauth.py`)
4. **Database Operations:** Supabase CRUD in routes
5. **Frontend State Management:** useState hooks in components
6. **Error Display:** Error message rendering in UI

## Test Types

**Unit Tests - Needed:**
- Backend: `test_state_token.py`
  - Test `generate_state()` produces valid tokens
  - Test `verify_state()` extracts correct user_id
  - Test tampering detection with invalid signatures

- Backend: `test_security.py`
  - Test `decode_supabase_jwt()` with valid tokens
  - Test expired token rejection
  - Test invalid token rejection

- Backend: `test_meta_oauth.py`
  - Test `build_authorization_url()` format
  - Test token exchange error handling
  - Test ad account fetch and parsing

- Frontend: `src/lib/api.test.ts`
  - Test API client initialization
  - Test JWT interceptor attachment
  - Test request method wrappers (listProducts, createProduct, etc.)

**Integration Tests - Needed:**
- Backend: `test_oauth_flow.py`
  - Test complete callback flow from code to token to accounts
  - Test state verification with user context
  - Test database upsert behavior

- Backend: `test_products_route.py`
  - Test CRUD operations with authenticated user
  - Test user isolation (users can't access other users' products)
  - Test database errors

- Frontend: `src/components/ui/__tests__/ConnectMetaButton.test.tsx`
  - Test button renders and handles clicks
  - Test API call and error display
  - Test loading state

**E2E Tests - Not Implemented:**
- No Playwright, Cypress, or Selenium setup
- Manual browser testing currently used

## Common Patterns (Needed for Future Tests)

**Async Testing:**
```python
# Backend pattern (would use pytest-asyncio):
@pytest.mark.asyncio
async def test_exchange_code_for_token():
    token = await exchange_code_for_token("test_code")
    assert isinstance(token, str)
```

**Error Testing:**
```python
# Backend pattern:
def test_verify_state_with_tampered_token():
    with pytest.raises(ValueError, match="signature mismatch"):
        verify_state("invalid_tampered_token")
```

**Frontend Component Testing:**
```typescript
// Frontend pattern (would use React Testing Library):
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConnectMetaButton } from './ConnectMetaButton';

it('shows error when API fails', async () => {
  const user = userEvent.setup();
  render(<ConnectMetaButton />);

  await user.click(screen.getByText('Connect with Facebook'));
  // Verify error message appears
});
```

**Mocking Axios:**
```typescript
// Frontend pattern:
jest.mock('@/lib/api', () => ({
  api: {
    getMetaAuthUrl: jest.fn().mockRejectedValue({
      response: { data: { detail: 'Auth failed' } }
    })
  }
}));
```

**Mocking Supabase:**
```python
# Backend pattern:
@patch('app.db.supabase_client.get_supabase')
def test_list_products(mock_get_supabase):
    mock_client = MagicMock()
    mock_get_supabase.return_value = mock_client
    # Verify Supabase operations
```

## Test Coverage Gaps

**High Priority:**
- OAuth callback security (state verification)
- JWT authentication and authorization
- Database ownership checks (users can't access other users' data)

**Medium Priority:**
- Frontend API error handling and display
- Form validation and submission
- Component rendering with different data states

**Low Priority:**
- OpenAPI schema validation
- CSS styling (not typically tested)
- Development-only endpoints (/health check)

## Recommended Test Setup

**Frontend (Add to package.json):**
```json
{
  "devDependencies": {
    "@testing-library/react": "^14.0.0",
    "@testing-library/jest-dom": "^6.0.0",
    "jest": "^29.0.0",
    "jest-environment-jsdom": "^29.0.0"
  }
}
```

**Backend (Add to requirements.txt):**
```
pytest==7.4.0
pytest-asyncio==0.21.0
pytest-cov==4.1.0
httpx==0.27.0
```

---

*Testing analysis: 2026-02-27*
