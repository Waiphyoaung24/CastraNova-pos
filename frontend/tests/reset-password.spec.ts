import { expect, test } from "@playwright/test"
import { findLastEmail } from "./utils/mailcatcher"
import { createUser } from "./utils/privateApi"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser } from "./utils/user"

test.use({ storageState: { cookies: [], origins: [] } })

test("Password Recovery title is visible", async ({ page }) => {
  await page.goto("/recover-password")

  await expect(
    page.getByRole("heading", { name: "Password Recovery" }),
  ).toBeVisible()
})

test("Input is visible, empty and editable", async ({ page }) => {
  await page.goto("/recover-password")

  await expect(page.getByTestId("email-input")).toBeVisible()
  await expect(page.getByTestId("email-input")).toHaveText("")
  await expect(page.getByTestId("email-input")).toBeEditable()
})

test("Continue button is visible", async ({ page }) => {
  await page.goto("/recover-password")

  await expect(page.getByRole("button", { name: "Continue" })).toBeVisible()
})

test("User can reset password successfully using the link", async ({
  page,
  request,
}) => {
  const email = randomEmail()
  const password = randomPassword()
  const newPassword = randomPassword()

  // Seed a user via the API (this app has no signup screen)
  await createUser({ email, password })

  await page.goto("/recover-password")
  await page.getByTestId("email-input").fill(email)

  await page.getByRole("button", { name: "Continue" }).click()

  const emailData = await findLastEmail({
    request,
    filter: (e) => e.recipients.includes(`<${email}>`),
    timeout: 5000,
  })

  await page.goto(
    `${process.env.MAILCATCHER_HOST}/messages/${emailData.id}.html`,
  )

  const selector = 'a[href*="/reset-password?token="]'

  const href = await page.getAttribute(selector, "href")
  if (!href) throw new Error("Password reset link not found in email")

  // The emailed link's host is FRONTEND_HOST, which need not match the host
  // the suite runs on — navigate to its path relative to our baseURL instead.
  const linkUrl = new URL(href, "http://localhost")

  // Set the new password and confirm it
  await page.goto(`${linkUrl.pathname}${linkUrl.search}`)

  await page.getByTestId("new-password-input").fill(newPassword)
  await page.getByTestId("confirm-password-input").fill(newPassword)
  await page.getByRole("button", { name: "Reset Password" }).click()
  await expect(page.getByText("Password updated successfully")).toBeVisible()

  // Check if the user is able to login with the new password
  await logInUser(page, email, newPassword)
})

// Regression (2026-08-01): the boot session check in main.tsx ran on every hard
// page load except /login. A logged-out visitor landing on a public auth route
// — which is exactly how the emailed reset link arrives — failed the check, was
// logged out and redirected to /login, discarding the token in the URL. The
// in-app "Forgot password?" link masked it, being a soft SPA navigation.
test("a hard load of a public auth route is not bounced to /login", async ({
  page,
}) => {
  for (const path of ["/recover-password", "/reset-password?token=sometoken"]) {
    await page.goto(path)
    // Give the module-level boot check time to fire and redirect if it would.
    await page.waitForTimeout(1000)
    expect(new URL(page.url()).pathname).not.toBe("/login")
  }
})

test("Expired or invalid reset link", async ({ page }) => {
  const password = randomPassword()
  const invalidUrl = "/reset-password?token=invalidtoken"

  await page.goto(invalidUrl)

  await page.getByTestId("new-password-input").fill(password)
  await page.getByTestId("confirm-password-input").fill(password)
  await page.getByRole("button", { name: "Reset Password" }).click()

  await expect(page.getByText("Invalid token")).toBeVisible()
})

test("Weak new password validation", async ({ page, request }) => {
  const email = randomEmail()
  const password = randomPassword()
  const weakPassword = "123"

  // Seed a user via the API (this app has no signup screen)
  await createUser({ email, password })

  await page.goto("/recover-password")
  await page.getByTestId("email-input").fill(email)
  await page.getByRole("button", { name: "Continue" }).click()

  const emailData = await findLastEmail({
    request,
    filter: (e) => e.recipients.includes(`<${email}>`),
    timeout: 5000,
  })

  await page.goto(
    `${process.env.MAILCATCHER_HOST}/messages/${emailData.id}.html`,
  )

  const selector = 'a[href*="/reset-password?token="]'
  const href = await page.getAttribute(selector, "href")
  if (!href) throw new Error("Password reset link not found in email")

  // Same baseURL-relative navigation as the successful-reset test above.
  const linkUrl = new URL(href, "http://localhost")

  // Set a weak new password
  await page.goto(`${linkUrl.pathname}${linkUrl.search}`)
  await page.getByTestId("new-password-input").fill(weakPassword)
  await page.getByTestId("confirm-password-input").fill(weakPassword)
  await page.getByRole("button", { name: "Reset Password" }).click()

  await expect(
    page.getByText("Password must be at least 8 characters"),
  ).toBeVisible()
})
