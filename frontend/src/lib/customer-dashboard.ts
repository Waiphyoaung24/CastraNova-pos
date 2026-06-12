import type {
  CustomerDashboardAdminPublic,
  CustomerDashboardStaffPublic,
} from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure helper for the customer-detail dashboard (FR-020, role-tiered).
//
// The backend returns the admin schema to admins and the redacted staff schema
// to staff; this discriminator lets the screen render lifetime revenue/COGS/
// margin only when those fields are actually present — belt-and-suspenders with
// the backend redaction so financials never reach a staff screen.
// ---------------------------------------------------------------------------

export type CustomerDashboard =
  | CustomerDashboardAdminPublic
  | CustomerDashboardStaffPublic

/** True when the payload carries admin-only lifetime financial fields. */
export function isAdminCustomerDashboard(
  data: CustomerDashboard,
): data is CustomerDashboardAdminPublic {
  return "lifetime_sale_revenue_thb" in data
}
