import axios, { type AxiosError, type AxiosResponse } from "axios"
import { ApiError, LoginService, OpenAPI } from "@/client"

const TOKEN_KEY = "access_token"
// Refresh a little before real expiry so an in-flight request never races it.
const EXPIRY_SKEW_MS = 30_000

/**
 * Routes a logged-out visitor is *supposed* to reach. Password recovery and
 * reset are reached with no session by definition — the reset link arrives by
 * email, so it is always a hard page load — and any session check on them ends
 * the session and redirects to /login, discarding the token in the URL. Used
 * both by the boot check and by endSession's redirect guard.
 */
const PUBLIC_PATHS = ["/login", "/recover-password", "/reset-password"]

/** True when the current URL is a public auth route (see PUBLIC_PATHS). */
export function isPublicAuthPath(
  pathname: string = window.location.pathname,
): boolean {
  return PUBLIC_PATHS.some((p) => pathname.startsWith(p))
}

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

// Single-flight only collapses CONCURRENT callers; it clears on settle, so a
// page whose queries fail in sequence used to re-ask forever against a session
// that can never come back. A 401 here is final — the refresh cookie is absent
// or rejected, and only a fresh login can change that — so latch it and answer
// later callers locally. Anything else (429, 5xx, offline) stays retryable.
let sessionDead = false

/** Re-arm refresh after a successful login (see the `sessionDead` latch). */
export function markSessionAlive(): void {
  sessionDead = false
}

/**
 * Exchange the httponly refresh cookie for a new access token. Writes the new
 * token to localStorage on success. Returns false on any failure (dead/absent
 * refresh cookie = the 12h idle window has elapsed). Single-flight, and a no-op
 * once a 401 has proved the session dead.
 */
export function refreshAccessToken(): Promise<boolean> {
  if (sessionDead) return Promise.resolve(false)
  if (inFlight) return inFlight
  inFlight = (async () => {
    try {
      const { access_token } = await LoginService.refreshAccessToken()
      localStorage.setItem(TOKEN_KEY, access_token)
      return true
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) sessionDead = true
        return false
      }
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
  // The navigation below is not instant, and every in-flight query that 401s
  // meanwhile would otherwise start its own refresh. The session is over —
  // latch it so those stragglers resolve locally instead of hitting the API.
  sessionDead = true
  localStorage.removeItem(TOKEN_KEY)
  // Never bounce off a public auth route: on /reset-password that would throw
  // away the token in the URL mid-reset.
  if (!isPublicAuthPath()) {
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
