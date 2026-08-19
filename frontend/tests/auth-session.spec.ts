import { expect, test } from "@playwright/test"

// These tests start from the authenticated storageState (auth.setup.ts logs in
// as the superuser: valid access token in localStorage + httponly refresh
// cookie in the context). We simulate access-token expiry by corrupting the
// stored token — to the interceptor a 401 is a 401 regardless of the cause.
//
// The refresh exchange here is REAL. The dev server proxies /api to the backend
// (vite.config.ts), so the app and the API share an origin and the browser will
// store and send the SameSite=lax refresh cookie. Before that proxy the harness
// was cross-site (app at 127.0.0.1:5173, API at backend:8000), the cookie was
// never stored at all, and these tests had to mock /login/refresh-token.

/** A corrupt token is swapped for a real one, so just check it changed shape. */
function looksLikeJwt(token: string | null): boolean {
  return token !== null && token.split(".").length === 3
}

test.describe("Idle auth / sliding refresh", () => {
  test("active user: an expired access token is refreshed transparently (no logout)", async ({
    page,
  }) => {
    await page.goto("/")
    // Corrupt the access token → the next authenticated request 401s, which the
    // interceptor answers by refreshing and retrying with the new token.
    await page.evaluate(() =>
      localStorage.setItem("access_token", "not-a-valid-jwt"),
    )
    await page.reload()

    // Refreshed transparently: the corrupt token is swapped for a live one and
    // we stay on the app, not bounced to /login. (Refresh is async — poll.)
    await expect
      .poll(async () =>
        looksLikeJwt(
          await page.evaluate(() => localStorage.getItem("access_token")),
        ),
      )
      .toBe(true)
    await expect(page).toHaveURL(/\/$/)
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

  test("a dead session costs ONE refresh attempt, not a storm", async ({
    page,
  }) => {
    // Regression guard for open-issues-2026-07-29 §1: a 401 used to be retried
    // by TanStack (3x per query, every query), and each retry started its own
    // refresh because single-flight only ever collapsed CONCURRENT callers.
    //
    // The session must die MID-SESSION, with a client-side navigation and no
    // reload. On a reload the boot check in main.tsx ends the session before a
    // single query mounts, so that path was never the storm. The reported cycle
    // was `channel-margin x2 -> me -> refresh-token`, repeating: /channel-margin
    // fires two queries (current + previous month) on top of `me`, and each one
    // retried independently.
    let refreshCalls = 0
    page.on("request", (req) => {
      if (req.url().includes("/login/refresh-token")) refreshCalls++
    })

    await page.goto("/channel-margin")
    await expect(
      page.getByRole("columnheader", { name: "Channel" }),
    ).toBeVisible()

    // Kill the session without reloading: cookie gone, access token dead.
    await page.context().clearCookies()
    await page.evaluate(() =>
      localStorage.setItem("access_token", "not-a-valid-jwt"),
    )
    refreshCalls = 0
    // Switching the group-by tab changes the query key, so both channel-margin
    // queries refetch in-place — the exact client-side path the report saw.
    await page.getByRole("tab", { name: "Product" }).click()

    // Generous timeout on purpose: unfixed, the app stayed on /channel-margin
    // for ~7s working through the retry backoff before it logged out at all.
    // We want it to get there so the COUNT below is what fails, not the clock.
    await expect(page).toHaveURL(/\/login/, { timeout: 20_000 })
    // Allow 2 for the race between the first two queries' 401s; the point is
    // that it is bounded and tiny, not one per query per retry.
    expect(refreshCalls).toBeLessThanOrEqual(2)
  })

  test("interceptor: a mid-session request that 401s is refreshed and retried (no reload)", async ({
    page,
  }) => {
    // Load with the valid storageState token so the boot check is a no-op.
    await page.goto("/")
    // "Stock" lives inside the collapsible "Inventory" group. Its open state is
    // restored from storageState and can vary, so expand only if it's closed.
    const stockLink = page.getByRole("link", { name: "Stock", exact: true })
    if (!(await stockLink.isVisible().catch(() => false))) {
      await page.getByRole("button", { name: "Inventory" }).click()
    }
    await expect(stockLink).toBeVisible()

    // Corrupt the token WITHOUT reloading — now ONLY an in-app request (not the
    // boot check) can trigger the refresh, isolating the interceptor path.
    await page.evaluate(() =>
      localStorage.setItem("access_token", "not-a-valid-jwt"),
    )

    // Client-side navigation to a data screen fires an authenticated query that
    // 401s; the interceptor must refresh and retry so the page loads.
    await stockLink.click()

    await expect
      .poll(async () =>
        looksLikeJwt(
          await page.evaluate(() => localStorage.getItem("access_token")),
        ),
      )
      .toBe(true)
    await expect(page).toHaveURL(/\/stock/)
  })

  test("explicit logout hits the server logout endpoint and clears the cookie", async ({
    page,
  }) => {
    await page.goto("/")

    // Spy on the server-side cookie-clearing call (let it through so the
    // backend actually clears the cookie).
    let logoutCalled = false
    await page.route("**/api/v1/login/logout", async (route) => {
      logoutCalled = true
      await route.continue()
    })

    // User menu → Log Out.
    await page.getByTestId("user-menu").click()
    await page.getByRole("menuitem", { name: /log ?out/i }).click()

    // True logout: server cookie-clear was called, session ended, token dropped
    // and — now that the cookie lives on the app's own origin — actually gone.
    await expect(page).toHaveURL(/\/login/)
    expect(logoutCalled).toBe(true)
    const token = await page.evaluate(() =>
      localStorage.getItem("access_token"),
    )
    expect(token).toBeNull()
    const cookies = await page.context().cookies()
    expect(cookies.some((c) => c.name === "refresh_token")).toBe(false)
  })
})
