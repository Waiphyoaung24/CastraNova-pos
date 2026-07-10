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
