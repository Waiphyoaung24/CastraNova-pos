import type { UserRole } from "@/client"
import useAuth from "./useAuth"

/**
 * Pure helper — unit-testable without React.
 * Admin = superuser OR BKK_ADMIN. No role + not superuser → least-privilege (both false).
 */
export function roleFlags(
  user: { is_superuser?: boolean; role?: UserRole | null } | null | undefined,
): { isAdmin: boolean; isStaff: boolean; role: UserRole | null } {
  const isAdmin =
    !!user && (user.is_superuser === true || user.role === "BKK_ADMIN")
  const isStaff = !!user && user.role === "YGN_STAFF" && !isAdmin
  return { isAdmin, isStaff, role: user?.role ?? null }
}

/** React hook — thin wrapper over roleFlags + useAuth. */
export function useRole() {
  const { user } = useAuth()
  return roleFlags(user)
}
