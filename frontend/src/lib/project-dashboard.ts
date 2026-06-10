import type {
  ProjectDashboardAdminPublic,
  ProjectDashboardStaffPublic,
} from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure helpers for the project-detail dashboard (FR-020, role-tiered).
//
// The backend returns the admin schema to admins and the redacted staff schema
// to staff; this discriminator lets the screen render budget/consumed-cost only
// when those fields are actually present — belt-and-suspenders with the backend
// redaction so cost never reaches a staff screen.
// ---------------------------------------------------------------------------

export type ProjectDashboard =
  | ProjectDashboardAdminPublic
  | ProjectDashboardStaffPublic

/** True when the payload carries admin-only financial fields. */
export function isAdminProjectDashboard(
  data: ProjectDashboard,
): data is ProjectDashboardAdminPublic {
  return "consumed_cost_thb" in data
}

/**
 * Budget minus consumed cost as a 2-dp decimal string (drops into formatThb),
 * or null when the project has no budget.
 */
export function budgetRemaining(
  budget: string | null,
  consumed: string,
): string | null {
  if (budget === null) return null
  return (Number(budget) - Number(consumed)).toFixed(2)
}
