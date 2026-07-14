# Idle Auto-Logout (Sliding-Window Refresh) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Log a user out after 12 hours of *inactivity* (not a fixed 12h token life) by activating the app's already-built refresh-token flow as a sliding window, while preserving offline-queued work across any forced re-login.

**Architecture:** Backend keeps its existing refresh flow (rotate + re-set cookie `max_age` on every `/login/refresh-token` = the sliding window) — only two TTLs change. The frontend gains one small `auth-session.ts` module plus a single response-interceptor that transparently refreshes on 401 and retries, gates offline-replay on a valid session, and makes explicit logout clear the server cookie. The guiding invariant: **never fire an authenticated request — including a replayed offline mutation — until a valid access token is held.**

**Tech Stack:** FastAPI / PyJWT (backend); React + TypeScript, `@hey-api` axios-based generated SDK, TanStack Query (offline persistence), Playwright (E2E). Source spec: `docs/superpowers/specs/2026-07-11-castranova-idle-auto-logout-design.md`.

## Global Constraints

- **Access token TTL = `15` minutes** (`ACCESS_TOKEN_EXPIRE_MINUTES = 15`). **Refresh token TTL = `60 * 12` = 12 hours** (`REFRESH_TOKEN_EXPIRE_MINUTES = 60 * 12`) → cookie `max-age=43200`. These exact values are the contract.
- **NEVER reset the dev DB.** (Memory: `no-db-reset-without-permission`.) Every backend test runs against the `app_test` database via the bind-mount command in each task; every E2E run sets `E2E_SKIP_DB_RESET=1`. No task may truncate/reseed the `app` database.
- **Backend:** all DB access through `crud.py`; strict mypy; ruff clean. No schema change here, so **no Alembic migration and no SDK regeneration** are needed (no new/changed endpoints or models).
- **Frontend:** biome for lint/format (`bun run lint`); do not hand-edit `src/client/` (generated). New auth logic lives only in `src/lib/auth-session.ts` and the three wiring points (`main.tsx`, `query-client.ts`, `useAuth.ts`).
- **High-risk (auth):** TDD every task; Review stage (stage 5) before PR must run `requesting-code-review` **plus** `ecc:security-reviewer`.
- **Safe test commands (copy verbatim):**
  - **Backend (never touches `app`):**
    ```bash
    MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -e POSTGRES_DB=app_test \
      -v "$(pwd -W)/backend/tests:/app/backend/tests" \
      -v "$(pwd -W)/backend/app:/app/backend/app" \
      backend pytest backend/tests/api/routes/test_auth_refresh.py -q
    ```
  - **E2E (never resets `app`):** run from repo root with the dev stack up (`docker compose watch`):
    ```bash
    docker compose run --rm -e E2E_SKIP_DB_RESET=1 playwright \
      bunx playwright test tests/<spec-file> --project=chromium
    ```
    E2E tests self-seed with random suffixes (collision-safe on the shared DB); they never assume an empty DB.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `backend/app/core/config.py` | Two TTL constants (the sliding-window contract) | 1 |
| `backend/tests/api/routes/test_auth_refresh.py` | Assert refresh cookie `max-age≈12h` + access-token `exp≈15min` | 1 |
| `frontend/src/lib/auth-session.ts` *(new)* | Single-flight refresh, session validity, session-end. The only new client logic. | 2 |
| `frontend/src/main.tsx` | Register the 401 refresh-then-retry response interceptor; gate `resumePausedMutations()` on `ensureValidSession()` | 2, 3 |
| `frontend/src/lib/query-client.ts` | `handleApiError`: on 401 just `endSession()` (refresh already tried at request boundary) | 2 |
| `frontend/src/hooks/useAuth.ts` | `logout()` clears the server refresh cookie, then ends the session; `login` flushes the paused queue | 3, 4 |
| `frontend/tests/auth-session.spec.ts` *(new)* | E2E: silent refresh, idle logout, true logout | 2, 4 |
| `frontend/tests/sale.spec.ts` | E2E: offline <12h and >12h auth cases (reuses `seedSellableUnit`) | 3 |

---

## Task 1: Backend TTL re-tune + sliding-window tests

**Files:**
- Modify: `backend/app/core/config.py:35-39`
- Test: `backend/tests/api/routes/test_auth_refresh.py` (append two tests)

**Interfaces:**
- Consumes: existing `settings.ACCESS_TOKEN_EXPIRE_MINUTES`, `settings.REFRESH_TOKEN_EXPIRE_MINUTES`; `security.create_access_token`; `_login(client)` helper already in the test file.
- Produces: nothing new for other tasks (config values only). Frontend tasks do not import backend code.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/api/routes/test_auth_refresh.py`:

```python
def test_refresh_cookie_max_age_is_12h(client: TestClient) -> None:
    # The sliding idle window IS the refresh cookie's max-age. Lock it at 12h
    # so a future TTL edit can't silently change the inactivity boundary.
    _login(client)
    r = client.post(REFRESH)
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "max-age=43200" in set_cookie  # 60 * 12 * 60 seconds


def test_access_token_lifetime_is_15_minutes(client: TestClient) -> None:
    # Access tokens are short-lived; the frontend refreshes them transparently.
    import jwt

    from app.core import security

    login = _login(client)
    access = login.json()["access_token"]
    payload = jwt.decode(
        access, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
    )
    lifetime_s = payload["exp"] - int(
        __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).timestamp()
    )
    # Allow a few seconds of clock/setup slack around the 900s target.
    assert 870 <= lifetime_s <= 900
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -e POSTGRES_DB=app_test \
  -v "$(pwd -W)/backend/tests:/app/backend/tests" \
  -v "$(pwd -W)/backend/app:/app/backend/app" \
  backend pytest backend/tests/api/routes/test_auth_refresh.py -q
```
Expected: the two new tests FAIL — current `max-age=604800` (7 days) and access lifetime ≈ 8 days.

- [ ] **Step 3: Change the TTLs**

In `backend/app/core/config.py`, replace lines 35-39:

```python
    # Access tokens are short-lived (15 min); the frontend transparently
    # refreshes them via /login/refresh-token while the user is active.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    # 12 hours. Rotated + re-set (max_age) on every /login/refresh-token call,
    # so this is a SLIDING inactivity window, not a fixed session length:
    # the clock resets on activity and only expires after 12h of silence.
    # This is the concrete mechanism behind PRD §8.3 (12h idle auto-logout).
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 12
```

- [ ] **Step 4: Run the tests to verify they pass (and nothing regressed)**

Run:
```bash
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -e POSTGRES_DB=app_test \
  -v "$(pwd -W)/backend/tests:/app/backend/tests" \
  -v "$(pwd -W)/backend/app:/app/backend/app" \
  backend pytest backend/tests/api/routes/test_auth_refresh.py \
  backend/tests/api/test_auth_token_status.py \
  backend/tests/api/test_refresh_bearer_rejected.py -q
```
Expected: all PASS (both new tests green; the existing refresh/rotation/logout/401 tests unchanged).

- [ ] **Step 5: Lint/type-check**

Run (inside the backend container or via the same bind-mount pattern): `ruff check backend/app/core/config.py && ruff format --check backend/app/core/config.py`.
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py backend/tests/api/routes/test_auth_refresh.py
git commit -m "feat(auth): 15-min access + 12h sliding refresh window (PRD §8.3)"
```

---

## Task 2: Silent refresh — `auth-session.ts` + 401 interceptor + `handleApiError`

Deliverable: an active user never sees a login screen for a mere access-token expiry (refresh-then-retry), and a genuinely dead session redirects to `/login` exactly once.

**Files:**
- Create: `frontend/src/lib/auth-session.ts`
- Modify: `frontend/src/main.tsx:14-22`
- Modify: `frontend/src/lib/query-client.ts:12-20`
- Test: `frontend/tests/auth-session.spec.ts` (new)

**Interfaces:**
- Consumes: `LoginService.refreshAccessToken()` (SDK, no args — uses the httponly cookie via `CREDENTIALS:'include'`); `OpenAPI.interceptors.response.use()`; the `axios` default instance.
- Produces (used by Tasks 3 & 4):
  - `ensureValidSession(): Promise<boolean>` — true if a usable access token is held (refreshing if needed), else false.
  - `refreshAccessToken(): Promise<boolean>` — single-flight; on success writes `localStorage.access_token` and returns true.
  - `endSession(): void` — clears `access_token` and hard-redirects to `/login` (guarded against redirect loops).
  - `installAuthInterceptor(): void` — registers the 401 refresh-then-retry response interceptor.

- [ ] **Step 1: Write the failing E2E tests**

Create `frontend/tests/auth-session.spec.ts`:

```typescript
import { expect, test } from "@playwright/test"

// These tests start from the authenticated storageState (auth.setup.ts logs in
// as the superuser: valid access token in localStorage + httponly refresh
// cookie in the context). We simulate access-token expiry by corrupting the
// stored token — to the interceptor a 401 is a 401 regardless of the cause.

test.describe("Idle auth / sliding refresh", () => {
  test("active user: an expired access token is refreshed transparently (no logout)", async ({
    page,
  }) => {
    await page.goto("/")
    // Corrupt the access token → the next authenticated request 401s.
    // The refresh cookie is still valid, so the interceptor should refresh+retry.
    await page.evaluate(() =>
      localStorage.setItem("access_token", "not-a-valid-jwt"),
    )
    await page.reload()

    // We stay on the app (readUserMe succeeded after a transparent refresh),
    // NOT bounced to /login.
    await expect(page).toHaveURL(/\/$/)
    // The token was replaced with a fresh, valid one.
    const token = await page.evaluate(() =>
      localStorage.getItem("access_token"),
    )
    expect(token).not.toBe("not-a-valid-jwt")
    expect(token).toBeTruthy()
  })

  test("idle: with the refresh token gone, a request redirects to /login", async ({
    page,
  }) => {
    await page.goto("/")
    // Simulate 12h idle: the browser has dropped the refresh cookie AND the
    // access token is dead. Refresh must fail → session ends.
    await page.context().clearCookies()
    await page.evaluate(() =>
      localStorage.setItem("access_token", "not-a-valid-jwt"),
    )
    await page.reload()

    await expect(page).toHaveURL(/\/login/)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm -e E2E_SKIP_DB_RESET=1 playwright bunx playwright test tests/auth-session.spec.ts --project=chromium`
Expected: BOTH fail — today there is no refresh wiring, so the corrupted token 401s and `handleApiError` redirects to `/login` in *both* tests (the first should have stayed on `/`).

- [ ] **Step 3a: Create the `auth-session.ts` module**

Create `frontend/src/lib/auth-session.ts`:

```typescript
import axios, { type AxiosResponse } from "axios"
import { ApiError, LoginService, OpenAPI } from "@/client"

const TOKEN_KEY = "access_token"
// Refresh a little before real expiry so an in-flight request never races it.
const EXPIRY_SKEW_MS = 30_000

/** Decode a JWT's `exp` (seconds since epoch); null if unparseable. */
function decodeExp(token: string): number | null {
  try {
    const payload = token.split(".")[1]
    const json = JSON.parse(
      atob(payload.replace(/-/g, "+").replace(/_/g, "/")),
    ) as { exp?: number }
    return typeof json.exp === "number" ? json.exp : null
  } catch {
    return null
  }
}

/** True if a stored access token exists and is not within the skew of expiry. */
export function isAccessTokenValid(): boolean {
  const token = localStorage.getItem(TOKEN_KEY)
  if (!token) return false
  const exp = decodeExp(token)
  if (exp === null) return false
  return exp * 1000 - EXPIRY_SKEW_MS > Date.now()
}

// Single-flight: concurrent callers (e.g. many queued mutations replaying at
// once) share ONE in-flight refresh instead of stampeding the endpoint.
let inFlight: Promise<boolean> | null = null

/**
 * Exchange the httponly refresh cookie for a new access token. Writes the new
 * token to localStorage on success. Returns false on any failure (dead/absent
 * refresh cookie = the 12h idle window has elapsed). Single-flight.
 */
export function refreshAccessToken(): Promise<boolean> {
  if (inFlight) return inFlight
  inFlight = (async () => {
    try {
      const { access_token } = await LoginService.refreshAccessToken()
      localStorage.setItem(TOKEN_KEY, access_token)
      return true
    } catch (err) {
      if (err instanceof ApiError) return false
      throw err
    } finally {
      inFlight = null
    }
  })()
  return inFlight
}

/** True if we can make authenticated calls now: valid token, or a fresh one. */
export async function ensureValidSession(): Promise<boolean> {
  if (isAccessTokenValid()) return true
  return refreshAccessToken()
}

/** End the session: drop the token and send the user to /login (loop-guarded). */
export function endSession(): void {
  localStorage.removeItem(TOKEN_KEY)
  if (!window.location.pathname.startsWith("/login")) {
    window.location.href = "/login"
  }
}

/**
 * Register a response interceptor that owns refresh-then-retry. axios returns
 * the 401 response (it does not throw at send), so this runs BEFORE the SDK
 * converts a 401 into an ApiError. On 401 (except on the auth endpoints
 * themselves, and never twice for one request) it refreshes once and retries
 * the original request with the new token; on refresh failure the 401 passes
 * through unchanged → ApiError → handleApiError → endSession.
 */
export function installAuthInterceptor(): void {
  OpenAPI.interceptors.response.use(async (response: AxiosResponse) => {
    const config = response.config as typeof response.config & {
      _authRetried?: boolean
    }
    const url = config.url ?? ""
    const isAuthEndpoint = /\/login\/(access-token|refresh-token|logout)/.test(
      url,
    )
    if (
      response.status !== 401 ||
      isAuthEndpoint ||
      config._authRetried === true
    ) {
      return response
    }
    const refreshed = await refreshAccessToken()
    if (!refreshed) return response
    config._authRetried = true
    const token = localStorage.getItem(TOKEN_KEY)
    config.headers.Authorization = `Bearer ${token}`
    return axios.request(config)
  })
}
```

- [ ] **Step 3b: Wire the interceptor in `main.tsx`**

In `frontend/src/main.tsx`, replace lines 14-22:

```typescript
OpenAPI.BASE = import.meta.env.VITE_API_URL
OpenAPI.TOKEN = async () => {
  return localStorage.getItem("access_token") || ""
}
// Refresh-then-retry on 401: an active user's short access token is renewed
// transparently; only a dead refresh cookie (12h idle) reaches endSession.
installAuthInterceptor()

// Replay offline-queued mutations as soon as the network returns — but only
// once we hold a valid session, so a replay never fires with a dead token
// (which would error the mutation out of the queue and lose the sale).
window.addEventListener("online", async () => {
  if (await ensureValidSession()) queryClient.resumePausedMutations()
})
```

Add to the imports at the top of `main.tsx`:

```typescript
import { ensureValidSession, installAuthInterceptor } from "./lib/auth-session"
```

(The `PersistQueryClientProvider onSuccess` resume gating is Task 3.)

- [ ] **Step 3c: Simplify `handleApiError` in `query-client.ts`**

In `frontend/src/lib/query-client.ts`, replace `handleApiError` (lines 12-20):

```typescript
import { endSession } from "./auth-session"

const handleApiError = (error: Error) => {
  // By the time a 401 reaches here, the request-boundary interceptor has
  // already attempted a refresh and failed — so the session is genuinely dead.
  // 403 = authenticated but under-privileged (e.g. staff hitting an admin
  // route); never log those out.
  if (error instanceof ApiError && error.status === 401) {
    endSession()
  }
}
```

- [ ] **Step 4: Run the E2E tests to verify they pass**

Run: `docker compose run --rm -e E2E_SKIP_DB_RESET=1 playwright bunx playwright test tests/auth-session.spec.ts --project=chromium`
Expected: both PASS — test 1 stays on `/` with a refreshed token; test 2 redirects to `/login`.

- [ ] **Step 5: Lint/type-check**

Run: `cd frontend && bun run lint && bunx tsc -p tsconfig.build.json --noEmit`
Expected: clean (no biome errors; no type errors).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/auth-session.ts frontend/src/main.tsx frontend/src/lib/query-client.ts frontend/tests/auth-session.spec.ts
git commit -m "feat(auth): transparent refresh-then-retry on 401 (sliding session)"
```

---

## Task 3: Gate offline replay on a valid session (zero-loss offline)

Deliverable: offline <12h reconnect replays with zero friction; offline >12h forces re-login but the queued sale survives and replays after login. This is the decisive offline safety behavior.

**Files:**
- Modify: `frontend/src/main.tsx:34-42` (the `PersistQueryClientProvider onSuccess`)
- Modify: `frontend/src/hooks/useAuth.ts:27-40` (`login` flushes the queue after re-login)
- Test: `frontend/tests/sale.spec.ts` (append two tests; reuses `seedSellableUnit`, `scanBarcode`, `waitForPersistedPausedMutation` already in the file)

**Interfaces:**
- Consumes: `ensureValidSession` (Task 2); existing `queryClient.resumePausedMutations()`; `SearchService.searchSerial` (already used in `sale.spec.ts`).
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing E2E tests**

Append to the `test.describe("Sale screen", ...)` block in `frontend/tests/sale.spec.ts`:

```typescript
  // Offline < 12h: access token expired but the refresh cookie is still valid.
  // On reconnect, ensureValidSession() refreshes silently and the queued sale
  // replays with the fresh token — no re-login, no data loss.
  test("offline < 12h → reconnect refreshes silently → sale replays once", async ({
    page,
  }) => {
    const { barcode, customerName } = await seedSellableUnit()

    await page.goto("/sale")
    await page.getByRole("combobox", { name: "Customer" }).click()
    await page.getByRole("option", { name: customerName, exact: true }).click()
    await scanBarcode(page, barcode)
    await expect(
      page.getByRole("cell", { name: barcode, exact: true }),
    ).toBeVisible()

    // Queue the sale offline.
    await page.evaluate(() => window.dispatchEvent(new Event("offline")))
    await page.getByRole("button", { name: "Complete sale" }).click()
    await expect(page.getByText(/Offline — 1 change queued/i)).toBeVisible()

    // Simulate an expired access token (refresh cookie left intact), then
    // reconnect via reload.
    await waitForPersistedPausedMutation(page)
    await page.evaluate(() =>
      localStorage.setItem("access_token", "not-a-valid-jwt"),
    )
    await page.reload()

    // Stayed logged in; the replay committed exactly once.
    await expect(page).toHaveURL(/\/sale/)
    await expect
      .poll(
        async () =>
          (await SearchService.searchSerial({ barcode })).current_state,
        { timeout: 15_000, intervals: [500, 1_000] },
      )
      .toBe("SOLD")
    const res = await SearchService.searchSerial({ barcode })
    expect(res.movements.filter((m) => m.event_type === "SOLD")).toHaveLength(1)
  })

  // Offline > 12h: the refresh cookie is gone. On reconnect the session can't
  // be revived → redirect to /login, but the queued sale stays PAUSED (never
  // fired, never errored). After re-login it replays exactly once.
  test("offline > 12h → reconnect forces re-login → queue survives → replays once", async ({
    page,
  }) => {
    const { barcode, customerName } = await seedSellableUnit()

    await page.goto("/sale")
    await page.getByRole("combobox", { name: "Customer" }).click()
    await page.getByRole("option", { name: customerName, exact: true }).click()
    await scanBarcode(page, barcode)
    await expect(
      page.getByRole("cell", { name: barcode, exact: true }),
    ).toBeVisible()

    await page.evaluate(() => window.dispatchEvent(new Event("offline")))
    await page.getByRole("button", { name: "Complete sale" }).click()
    await expect(page.getByText(/Offline — 1 change queued/i)).toBeVisible()
    await waitForPersistedPausedMutation(page)

    // 12h idle: drop the refresh cookie and kill the access token.
    await page.context().clearCookies()
    await page.evaluate(() =>
      localStorage.setItem("access_token", "not-a-valid-jwt"),
    )
    await page.reload()

    // Forced re-login; the queued mutation is still persisted (not errored).
    await expect(page).toHaveURL(/\/login/)
    await waitForPersistedPausedMutation(page)

    // Log back in via the UI; after landing on the app the queue flushes.
    await page.getByTestId("email-input").fill(firstSuperuser)
    await page.getByTestId("password-input").fill(firstSuperuserPassword)
    await page.getByRole("button", { name: "Log In" }).click()
    await page.waitForURL("/")

    await expect
      .poll(
        async () =>
          (await SearchService.searchSerial({ barcode })).current_state,
        { timeout: 15_000, intervals: [500, 1_000] },
      )
      .toBe("SOLD")
    const res = await SearchService.searchSerial({ barcode })
    expect(res.movements.filter((m) => m.event_type === "SOLD")).toHaveLength(1)
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm -e E2E_SKIP_DB_RESET=1 playwright bunx playwright test tests/sale.spec.ts --project=chromium`
Expected: the two new tests FAIL — today the rehydrate `onSuccess` resumes unconditionally, so the >12h replay fires with a dead token, errors out, and the sale never becomes `SOLD`; the post-login flush isn't wired.

- [ ] **Step 3a: Gate the rehydrate resume in `main.tsx`**

In `frontend/src/main.tsx`, replace the `onSuccess` handler (lines 37-41):

```typescript
        onSuccess={async () => {
          // Only replay once we hold a valid session. If the refresh token has
          // expired (12h idle), leave the mutations PAUSED — they survive to
          // replay after the user logs back in (idempotency keys dedupe).
          if (await ensureValidSession()) {
            queryClient.resumePausedMutations()
          }
        }}
```

- [ ] **Step 3b: Flush the queue after re-login in `useAuth.ts`**

In `frontend/src/hooks/useAuth.ts`, update the `login` function (lines 27-32) and its import so a successful login resumes any mutation held back during a forced logout:

```typescript
  const login = async (data: AccessToken) => {
    const response = await LoginService.loginAccessToken({
      formData: data,
    })
    localStorage.setItem("access_token", response.access_token)
    // Flush any offline mutation that was paused through a forced logout.
    await queryClient.resumePausedMutations()
  }
```

Add the import near the top of `useAuth.ts`:

```typescript
import { queryClient } from "@/lib/query-client"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm -e E2E_SKIP_DB_RESET=1 playwright bunx playwright test tests/sale.spec.ts --project=chromium`
Expected: all `sale.spec.ts` tests PASS (the two new ones plus the pre-existing online/offline sale tests — confirming no regression to the replay path).

- [ ] **Step 5: Lint/type-check**

Run: `cd frontend && bun run lint && bunx tsc -p tsconfig.build.json --noEmit`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/main.tsx frontend/src/hooks/useAuth.ts frontend/tests/sale.spec.ts
git commit -m "feat(auth): gate offline replay on valid session; flush queue post-login"
```

---

## Task 4: True logout (clear the server refresh cookie)

Deliverable: an explicit logout ends the session on the server too — a subsequent refresh cannot revive it. Fixes the current gap where `logout()` clears only localStorage and leaves the httponly refresh cookie alive.

**Files:**
- Modify: `frontend/src/hooks/useAuth.ts:42-45` (`logout`)
- Test: `frontend/tests/auth-session.spec.ts` (append one test)

**Interfaces:**
- Consumes: `LoginService.logout()` (SDK, clears the cookie server-side); `endSession` (Task 2).
- Produces: nothing new.

- [ ] **Step 1: Write the failing E2E test**

Append inside the `test.describe("Idle auth / sliding refresh", ...)` block in `frontend/tests/auth-session.spec.ts`:

```typescript
  test("explicit logout clears the server refresh cookie (true logout)", async ({
    page,
  }) => {
    await page.goto("/")
    // Open the user menu and log out. (User menu → "Log out".)
    await page.getByTestId("user-menu").click()
    await page.getByRole("menuitem", { name: /log ?out/i }).click()
    await expect(page).toHaveURL(/\/login/)

    // The refresh cookie is gone: a refresh attempt now fails.
    const cookies = await page.context().cookies()
    expect(cookies.find((c) => c.name === "refresh_token")).toBeUndefined()
  })
```

> Selectors verified against `frontend/src/components/Sidebar/User.tsx`: the trigger already carries `data-testid="user-menu"` (line 66) and the logout item renders text "Log Out" (line 90). No component change is needed for the test.

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose run --rm -e E2E_SKIP_DB_RESET=1 playwright bunx playwright test tests/auth-session.spec.ts --project=chromium -g "true logout"`
Expected: FAIL — today `logout()` never calls `/login/logout`, so the `refresh_token` cookie is still present.

- [ ] **Step 3: Make `logout` a true logout**

In `frontend/src/hooks/useAuth.ts`, replace `logout` (lines 42-45):

```typescript
  const logout = async () => {
    // Clear the httponly refresh cookie server-side; ignore failures (e.g.
    // offline) — we still end the local session below.
    try {
      await LoginService.logout()
    } catch {
      // best-effort: a network failure must not trap the user in the app
    }
    endSession()
  }
```

Add `endSession` to the `auth-session` import in `useAuth.ts`:

```typescript
import { endSession } from "@/lib/auth-session"
```

Call site is already compatible: `User.tsx` calls `logout()` fire-and-forget inside its own `handleLogout` (line 54-56); `logout` becoming `async` returns a floating promise that the existing handler already ignores. No `User.tsx` change required.

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose run --rm -e E2E_SKIP_DB_RESET=1 playwright bunx playwright test tests/auth-session.spec.ts --project=chromium`
Expected: all three `auth-session.spec.ts` tests PASS.

- [ ] **Step 5: Lint/type-check**

Run: `cd frontend && bun run lint && bunx tsc -p tsconfig.build.json --noEmit`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useAuth.ts frontend/tests/auth-session.spec.ts
git commit -m "fix(auth): logout clears the server refresh cookie (true logout)"
```

---

## Final verification (before PR)

- [ ] **Full backend auth suite (against `app_test`):**
  ```bash
  MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -e POSTGRES_DB=app_test \
    -v "$(pwd -W)/backend/tests:/app/backend/tests" \
    -v "$(pwd -W)/backend/app:/app/backend/app" \
    backend pytest backend/tests/api -q
  ```
  Expected: all PASS.
- [ ] **Full E2E auth + sale specs (never resetting `app`):**
  ```bash
  docker compose run --rm -e E2E_SKIP_DB_RESET=1 playwright \
    bunx playwright test tests/auth-session.spec.ts tests/sale.spec.ts tests/login.spec.ts --project=chromium
  ```
  Expected: all PASS (including `login.spec.ts` — confirms the login flow and any logout UI it exercises still work).
- [ ] **Review stage (mandatory for auth):** run `requesting-code-review`, then `ecc:security-reviewer` (belt-and-suspenders on auth). Address findings.
- [ ] **Ship:** `create-pr` into `dev` (branch `feat/idle-auto-logout`). One PR for the whole feature.

## Mapping to spec success criteria (§6)

| Spec §6 criterion | Task / test |
|---|---|
| Refresh re-sets `max_age ≈ 12h` | Task 1 · `test_refresh_cookie_max_age_is_12h` |
| Existing 401/refresh/wrong-type tests stay green | Task 1 Step 4 |
| E2E 1 — access expiry invisible | Task 2 · "expired access token is refreshed transparently" |
| E2E 2 — idle → logout | Task 2 · "refresh token gone → redirect to /login" |
| E2E 3 — offline <12h zero loss, no re-login | Task 3 · "offline < 12h → reconnect refreshes silently" |
| E2E 4 — offline >12h re-login → replay | Task 3 · "offline > 12h → forces re-login → replays once" |
| E2E 5 — explicit logout is a true logout | Task 4 · "explicit logout clears the server refresh cookie" |
| Access-token lifetime = 15 min | Task 1 · `test_access_token_lifetime_is_15_minutes` |
