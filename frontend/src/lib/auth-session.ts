import axios, { type AxiosError, type AxiosResponse } from "axios"
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
    // Mirror the SDK's sendRequest: axios rejects on non-2xx by default, but
    // the SDK's response pipeline expects a resolved response (it converts
    // non-2xx to ApiError downstream). Return the error response so a retried
    // request that legitimately 4xx/5xxs still flows through ApiError, not a
    // raw AxiosError.
    try {
      return await axios.request(config)
    } catch (err) {
      const axiosErr = err as AxiosError
      if (axiosErr.response) return axiosErr.response
      throw err
    }
  })
}
