import { describe, expect, it } from "vitest"

import { ApiError } from "@/client/core/ApiError"
import { shouldRetryRequest } from "./query-client"

function apiError(status: number): ApiError {
  return new ApiError(
    { method: "GET", url: "/api/v1/reports/channel-margin" },
    { url: "", ok: false, status, statusText: "", body: undefined },
    "boom",
  )
}

describe("query retry policy", () => {
  it("never retries a 401 — the refresh already failed, so it is not transient", () => {
    expect(shouldRetryRequest(0, apiError(401))).toBe(false)
  })

  it("never retries a 403 — under-privileged is not transient either", () => {
    expect(shouldRetryRequest(0, apiError(403))).toBe(false)
  })

  it("still retries a 500 up to the default three times", () => {
    expect(shouldRetryRequest(0, apiError(500))).toBe(true)
    expect(shouldRetryRequest(2, apiError(500))).toBe(true)
    expect(shouldRetryRequest(3, apiError(500))).toBe(false)
  })

  it("still retries a network error with no response", () => {
    expect(shouldRetryRequest(0, new TypeError("Network Error"))).toBe(true)
  })
})
