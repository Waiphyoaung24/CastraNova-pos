import { AxiosError } from "axios"
import type { ApiError } from "./client"

// `err.body` is server-controlled and genuinely unknown at runtime: FastAPI
// validation puts an array of {loc,msg,type} in `detail`, hand-written
// HTTPExceptions put a string there, and a gateway can return a body with no
// `detail` at all. Narrow every branch — the result goes straight to a toast,
// so returning a non-string renders "[object Object]" or "undefined" to a user.
export function extractErrorMessage(err: ApiError): string {
  if (err instanceof AxiosError) {
    return err.message
  }

  const detail = (err.body as { detail?: unknown } | undefined)?.detail
  if (typeof detail === "string" && detail !== "") {
    return detail
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const first: unknown = detail[0]
    if (typeof first === "string" && first !== "") {
      return first
    }
    if (
      typeof first === "object" &&
      first !== null &&
      "msg" in first &&
      typeof first.msg === "string"
    ) {
      return first.msg
    }
  }
  return "Something went wrong."
}

export const handleError = function (
  this: (msg: string) => void,
  err: ApiError,
) {
  const errorMessage = extractErrorMessage(err)
  this(errorMessage)
}

export const getInitials = (name: string): string => {
  return name
    .split(" ")
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase()
}
