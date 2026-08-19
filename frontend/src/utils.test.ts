import { AxiosError } from "axios"
import { describe, expect, it } from "vitest"
import type { ApiError } from "./client"
import { extractErrorMessage } from "./utils"

// `err.body` is whatever the server sent, parsed. It is genuinely `unknown` at
// runtime: FastAPI validation errors put an array of {loc,msg,type} in `detail`,
// hand-written HTTPExceptions put a string there, and a proxy or gateway can
// return a body with no `detail` at all. Every case must yield a plain string —
// callers pass the result straight to a toast.
const apiError = (body: unknown, status = 400): ApiError =>
  ({ status, body }) as ApiError

const FALLBACK = "Something went wrong."

describe("extractErrorMessage", () => {
  it("returns a string detail unchanged", () => {
    expect(extractErrorMessage(apiError({ detail: "Unit already SOLD" }))).toBe(
      "Unit already SOLD",
    )
  })

  it("returns the first message from a FastAPI validation array", () => {
    const body = {
      detail: [
        { loc: ["body", "email"], msg: "field required", type: "missing" },
      ],
    }
    expect(extractErrorMessage(apiError(body))).toBe("field required")
  })

  it("returns the first element when detail is an array of strings", () => {
    expect(extractErrorMessage(apiError({ detail: ["plain reason"] }))).toBe(
      "plain reason",
    )
  })

  it("falls back when an array element is null", () => {
    expect(extractErrorMessage(apiError({ detail: [null] }))).toBe(FALLBACK)
  })

  it("falls back when an array element has no usable message", () => {
    expect(extractErrorMessage(apiError({ detail: [{ loc: ["body"] }] }))).toBe(
      FALLBACK,
    )
  })

  it("falls back when detail is an object rather than rendering [object Object]", () => {
    const body = { detail: { code: "OUT_OF_STOCK", available: 2 } }
    expect(extractErrorMessage(apiError(body))).toBe(FALLBACK)
  })

  it("falls back when detail is an empty string rather than showing a blank toast", () => {
    expect(extractErrorMessage(apiError({ detail: "" }))).toBe(FALLBACK)
  })

  it("falls back when the first array element is an empty string", () => {
    expect(extractErrorMessage(apiError({ detail: [""] }))).toBe(FALLBACK)
  })

  it("falls back when detail is an empty array", () => {
    expect(extractErrorMessage(apiError({ detail: [] }))).toBe(FALLBACK)
  })

  it("falls back for a non-JSON body such as a proxy HTML page", () => {
    expect(extractErrorMessage(apiError("<html>502 Bad Gateway</html>"))).toBe(
      FALLBACK,
    )
  })

  it("falls back when the body has no detail", () => {
    expect(extractErrorMessage(apiError({}))).toBe(FALLBACK)
  })

  it("falls back when the body is undefined", () => {
    expect(extractErrorMessage(apiError(undefined))).toBe(FALLBACK)
  })

  // sale.tsx keys its "Insufficient Stock" toast title on
  // `extractErrorMessage(err).startsWith(INSUFFICIENT_STOCK_PREFIX)`. If this
  // parser ever stops returning the raw backend string for a plain 409, that
  // screen silently degrades to a generic toast — so pin the exact shape
  // consume_quantity_fifo produces (backend/app/crud.py).
  it("returns the oversell 409 detail verbatim so sale.tsx can match it", () => {
    const body = { detail: "Insufficient stock: have 0, need 1" }
    const message = extractErrorMessage(apiError(body, 409))
    expect(message).toBe("Insufficient stock: have 0, need 1")
    expect(message.startsWith("Insufficient stock")).toBe(true)
  })

  it("prefers the axios message for transport-level errors", () => {
    const err = new AxiosError("Network Error")
    expect(extractErrorMessage(err as unknown as ApiError)).toBe(
      "Network Error",
    )
  })
})
