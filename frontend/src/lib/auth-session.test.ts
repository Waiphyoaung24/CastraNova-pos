import { beforeEach, describe, expect, it, vi } from "vitest"

import { ApiError } from "@/client/core/ApiError"

// Only the network call is faked; ApiError and OpenAPI stay real so the
// `err instanceof ApiError` branch under test is the genuine one.
const refreshCall = vi.fn()
vi.mock("@/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/client")>()
  return {
    ...actual,
    LoginService: { ...actual.LoginService, refreshAccessToken: refreshCall },
  }
})

const { markSessionAlive, refreshAccessToken } = await import("./auth-session")

function apiError(status: number): ApiError {
  return new ApiError(
    { method: "POST", url: "/api/v1/login/refresh-token" },
    { url: "", ok: false, status, statusText: "", body: undefined },
    "boom",
  )
}

describe("refresh single-flight and dead-session latch", () => {
  beforeEach(() => {
    refreshCall.mockReset()
    markSessionAlive()
  })

  it("stops calling the endpoint once a 401 has proved the session dead", async () => {
    refreshCall.mockRejectedValue(apiError(401))

    expect(await refreshAccessToken()).toBe(false)
    expect(await refreshAccessToken()).toBe(false)
    expect(await refreshAccessToken()).toBe(false)

    // Without the latch each sequential caller re-hits /login/refresh-token —
    // that is the storm in open-issues-2026-07-29 §1.
    expect(refreshCall).toHaveBeenCalledTimes(1)
  })

  it("collapses concurrent callers into one in-flight request", async () => {
    refreshCall.mockRejectedValue(apiError(401))

    const results = await Promise.all([
      refreshAccessToken(),
      refreshAccessToken(),
      refreshAccessToken(),
    ])

    expect(results).toEqual([false, false, false])
    expect(refreshCall).toHaveBeenCalledTimes(1)
  })

  it("does not latch on a transient server error, so a retry can still succeed", async () => {
    refreshCall.mockRejectedValue(apiError(500))

    expect(await refreshAccessToken()).toBe(false)
    expect(await refreshAccessToken()).toBe(false)

    expect(refreshCall).toHaveBeenCalledTimes(2)
  })

  it("re-arms after a fresh login", async () => {
    refreshCall.mockRejectedValue(apiError(401))
    await refreshAccessToken()
    expect(refreshCall).toHaveBeenCalledTimes(1)

    markSessionAlive()
    await refreshAccessToken()

    expect(refreshCall).toHaveBeenCalledTimes(2)
  })

  it("propagates a non-ApiError (offline) instead of ending the session", async () => {
    refreshCall.mockRejectedValue(new TypeError("Network Error"))

    await expect(refreshAccessToken()).rejects.toThrow(TypeError)
    // A network blip must not latch — reconnecting has to be able to recover.
    refreshCall.mockRejectedValue(apiError(500))
    expect(await refreshAccessToken()).toBe(false)
  })
})
