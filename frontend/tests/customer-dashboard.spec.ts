import { expect, test } from "@playwright/test"
import type {
  CustomerDashboardAdminPublic,
  CustomerDashboardStaffPublic,
} from "../src/client/types.gen"
import { isAdminCustomerDashboard } from "../src/lib/customer-dashboard"

// Pure-logic coverage of the role discriminator for the customer-detail
// dashboard (FR-020). Lifetime revenue/COGS/margin render ONLY for admin; this
// guard (with backend redaction) keeps those figures off staff screens. The
// in-browser role/redaction E2E runs in the Part 5 E2E pass.

const customer = {
  name: "Acme",
  country: null,
  contact: null,
  type: "DEALER" as const,
  notes: null,
  id: "00000000-0000-0000-0000-0000000000c1",
}

const STAFF: CustomerDashboardStaffPublic = {
  customer,
  transactions: [],
  active_projects: [],
  closed_projects: [],
}

const ADMIN: CustomerDashboardAdminPublic = {
  customer,
  transactions: [],
  active_projects: [],
  closed_projects: [],
  lifetime_sale_revenue_thb: "1000.00",
  lifetime_sale_cogs_thb: "600.00",
  lifetime_sale_margin_thb: "400.00",
  lifetime_maintenance_revenue_thb: "0.00",
  lifetime_maintenance_cogs_thb: "0.00",
  lifetime_maintenance_margin_thb: "0.00",
  lifetime_project_cogs_thb: "0.00",
}

test("isAdminCustomerDashboard is true for an admin payload", () => {
  expect(isAdminCustomerDashboard(ADMIN)).toBe(true)
})

test("isAdminCustomerDashboard is false for a staff payload", () => {
  expect(isAdminCustomerDashboard(STAFF)).toBe(false)
})
