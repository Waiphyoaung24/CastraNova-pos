import { expect, test } from "@playwright/test"

import { LoginService, OpenAPI } from "../src/client"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

// These tests start from the authenticated storageState (auth.setup.ts logs in
// as the superuser: valid access token in localStorage + httponly refresh
// cookie in the context). We simulate access-token expiry by corrupting the
// stored token — to the interceptor a 401 is a 401 regardless of the cause.
//
// Node-side SDK (mirrors sale.spec.ts) — used to mint a real access token that
// the mocked refresh endpoint hands back. It authenticates independently of the
// browser's storageState.
OpenAPI.BASE = `${process.env.VITE_API_URL}`

test.describe("Idle auth / sliding refresh", () => {
  test("active user: an expired access token is refreshed transparently (no logout)", async ({
    page,
  }) => {
    // Mock POST /login/refresh-token: the E2E harness is cross-site (the app is
    // served at 127.0.0.1:5173 but the API is backend:8000), so the browser
    // withholds the SameSite=lax refresh cookie and a real refresh can't
    // succeed here. Mocking isolates the frontend's refresh-then-retry wiring;
    // the real cookie exchange is covered by backend test_auth_refresh.py. We
    // return a genuinely valid access token so the retried request really 200s.
    const fresh = await LoginService.loginAccessToken({
      formData: {
        username: firstSuperuser,
        password: firstSuperuserPassword,
      },
    })
    await page.route("**/api/v1/login/refresh-token", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ access_token: fresh.access_token }),
      }),
    )

    await page.goto("/")
    // Corrupt the access token → the next authenticated request 401s, which the
    // interceptor answers by refreshing (mocked) and retrying with the new token.
    await page.evaluate(() =>
      localStorage.setItem("access_token", "not-a-valid-jwt"),
    )
    await page.reload()

    // Refreshed transparently: the corrupt token is swapped for the fresh one
    // and we stay on the app, not bounced to /login. (Refresh is async — poll.)
    await expect
      .poll(() => page.evaluate(() => localStorage.getItem("access_token")))
      .toBe(fresh.access_token)
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

  test("interceptor: a mid-session request that 401s is refreshed and retried (no reload)", async ({
    page,
  }) => {
    const fresh = await LoginService.loginAccessToken({
      formData: {
        username: firstSuperuser,
        password: firstSuperuserPassword,
      },
    })
    await page.route("**/api/v1/login/refresh-token", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ access_token: fresh.access_token }),
      }),
    )

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
    // 401s; the interceptor must refresh (mocked) and retry so the page loads.
    await stockLink.click()

    await expect
      .poll(() => page.evaluate(() => localStorage.getItem("access_token")))
      .toBe(fresh.access_token)
    await expect(page).toHaveURL(/\/stock/)
  })
})
