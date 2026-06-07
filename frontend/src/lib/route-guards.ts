/**
 * Route-guard helpers for TanStack Router `beforeLoad`.
 *
 * Usage in a route file:
 *
 *   import { requireAdmin, requireAuth } from "@/lib/route-guards"
 *
 *   // Admin-only route:
 *   export const Route = createFileRoute("/_layout/some-admin-page")({
 *     beforeLoad: requireAdmin,
 *     component: SomePage,
 *   })
 *
 *   // Explicit auth guard (redundant under _layout, safe to use for parity):
 *   export const Route = createFileRoute("/_layout/some-page")({
 *     beforeLoad: requireAuth,
 *     component: SomePage,
 *   })
 */

import { redirect } from "@tanstack/react-router"

import { UsersService } from "@/client"
import { isLoggedIn } from "@/hooks/useAuth"
import { roleFlags } from "@/hooks/useRole"

/**
 * Mirrors `_layout.tsx`'s `beforeLoad` — ensures a token exists in
 * localStorage before the route loads.
 *
 * Note: `_layout.tsx` already guards every `/_layout/*` child, so this helper
 * is redundant there. It is provided for explicitness, testing parity, and
 * routes that may sit outside `_layout` in the future.
 */
export async function requireAuth(): Promise<void> {
  if (!isLoggedIn()) {
    throw redirect({ to: "/login" })
  }
}

/**
 * Mirrors (and extends) `admin.tsx`'s `beforeLoad` — fetches the current user
 * and redirects non-admins to "/".
 *
 * Admin predicate reuses `roleFlags` from `useRole.ts` (DRY):
 *   admin = is_superuser OR role === "BKK_ADMIN"
 *
 * Deviation from the existing `admin.tsx`: that route only checks
 * `is_superuser`; this helper also accepts `BKK_ADMIN` role, which aligns
 * with the Task 2.2 definition. Screen tasks should prefer this helper over
 * hand-rolling the predicate.
 */
export async function requireAdmin(): Promise<void> {
  const user = await UsersService.readUserMe()
  if (!roleFlags(user).isAdmin) {
    throw redirect({ to: "/" })
  }
}
