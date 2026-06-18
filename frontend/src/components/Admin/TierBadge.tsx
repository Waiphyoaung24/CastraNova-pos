import type { UserRole } from "@/client"
import { Badge } from "@/components/ui/badge"
import { tierLabel } from "@/hooks/useRole"

/** Role-tier badge shared by the desktop users table and the mobile user card,
 * so the Superuser/Admin/Staff styling stays in one place. */
export function TierBadge({
  user,
}: {
  user: { is_superuser?: boolean; role?: UserRole | null }
}) {
  const label = tierLabel(user)
  return (
    <Badge variant={label === "Staff" ? "secondary" : "default"}>{label}</Badge>
  )
}
