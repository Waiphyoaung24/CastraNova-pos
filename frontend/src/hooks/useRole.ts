import type { UserRole } from "@/client"
import useAuth from "./useAuth"

type UserLike =
  | { is_superuser?: boolean; role?: UserRole | null }
  | null
  | undefined

/**
 * Pure helper — unit-testable without React.
 * Admin = superuser OR BKK_ADMIN. No role + not superuser → least-privilege.
 * Note: `is_superuser` absent/undefined is treated as non-admin (least-privilege); a backend
 * schema regression that drops the field will silently downgrade the user — intentional fail-safe.
 */
export function roleFlags(user: UserLike): {
  isAdmin: boolean
  isStaff: boolean
  isSuperuser: boolean
  role: UserRole | null
} {
  const isSuperuser = !!user && user.is_superuser === true
  const isAdmin = isSuperuser || (!!user && user.role === "BKK_ADMIN")
  const isStaff = !!user && user.role === "YGN_STAFF" && !isAdmin
  return { isAdmin, isStaff, isSuperuser, role: user?.role ?? null }
}

/**
 * Friendly tier label for display. Superuser wins; then BKK_ADMIN → "Admin";
 * everything else (including missing role) → "Staff" (least-privilege default).
 */
export function tierLabel(user: UserLike): "Superuser" | "Admin" | "Staff" {
  const { isSuperuser, isAdmin } = roleFlags(user)
  if (isSuperuser) return "Superuser"
  if (isAdmin) return "Admin"
  return "Staff"
}

/** React hook — thin wrapper over roleFlags + useAuth. */
export function useRole() {
  const { user } = useAuth()
  return roleFlags(user)
}
