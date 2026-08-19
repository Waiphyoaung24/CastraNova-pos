/**
 * The origin every browser-side API call goes through.
 *
 * In dev and E2E this is the empty string, so calls are same-origin and the
 * Vite dev server proxies `/api` to the backend (see `vite.config.ts`). That is
 * not a convenience: the refresh token is an httponly `SameSite=lax` cookie, so
 * if the page origin and the API origin differ the browser refuses to STORE it
 * at all, and `/login/refresh-token` then 401s for the whole session. The E2E
 * harness serves the app at `127.0.0.1:5173` against `backend:8000`, which is
 * exactly that cross-site pair (open-issues-2026-07-29 §1).
 *
 * Production builds keep the absolute `VITE_API_URL`: the API lives on the
 * `api.` subdomain of the app's own domain, which is same-site, so the cookie
 * is stored and sent normally there.
 */
export const API_BASE = import.meta.env.DEV ? "" : import.meta.env.VITE_API_URL
