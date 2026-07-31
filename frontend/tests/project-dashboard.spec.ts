import { expect, test } from "@playwright/test"
import type {
  ProjectConsumptionRowPublic,
  ProjectDashboardAdminPublic,
  ProjectDashboardStaffPublic,
} from "../src/client/types.gen"
import {
  budgetRemaining,
  consumedItemLabel,
  isAdminProjectDashboard,
} from "../src/lib/project-dashboard"

// Pure-logic coverage of the role discriminator + budget math that the
// project-detail dashboard depends on (FR-020). The financial fields ONLY
// render for admin; the discriminator below is the belt-and-suspenders guard
// that, together with the backend redaction, keeps cost/budget off staff
// screens. The in-browser role/redaction E2E runs in the Part 5 E2E pass.

const STAFF: ProjectDashboardStaffPublic = {
  project: {
    id: "00000000-0000-0000-0000-000000000001",
    code: "PRJ-1",
    name: "Cold Room",
    customer_id: "00000000-0000-0000-0000-0000000000c1",
    start_date: null,
    end_date: null,
    status: "ACTIVE",
  },
  pulls: [],
}

const ADMIN: ProjectDashboardAdminPublic = {
  project: {
    code: "PRJ-1",
    name: "Cold Room",
    customer_id: "00000000-0000-0000-0000-0000000000c1",
    start_date: null,
    end_date: null,
    status: "ACTIVE",
    budget_thb: "1000.00",
    id: "00000000-0000-0000-0000-000000000001",
  },
  pulls: [],
  budget_thb: "1000.00",
  consumed_cost_thb: "600.50",
  consumed_items: [],
}

const row = (
  over: Partial<ProjectConsumptionRowPublic>,
): ProjectConsumptionRowPublic => ({
  line_kind: "PART",
  product_id: "00000000-0000-0000-0000-0000000000p1",
  product_sku: "CN-BLT-010",
  model_name: "Bolt",
  unit_serial: null,
  quantity: 20,
  occurred_at: "2026-07-04T09:31:00Z",
  project_pull_id: "00000000-0000-0000-0000-0000000000f1",
  total_cost_thb: "610.00",
  draws: [],
  ...over,
})

test("isAdminProjectDashboard is true for an admin payload", () => {
  expect(isAdminProjectDashboard(ADMIN)).toBe(true)
})

test("isAdminProjectDashboard is false for a staff payload", () => {
  expect(isAdminProjectDashboard(STAFF)).toBe(false)
})

test("budgetRemaining subtracts consumed from budget as a decimal string", () => {
  expect(budgetRemaining("1000.00", "600.50")).toBe("399.50")
})

test("budgetRemaining returns null when there is no budget", () => {
  expect(budgetRemaining(null, "600.50")).toBeNull()
})

// --- consumed-items row labels (FR-020) ------------------------------------

test("a PART row is labelled by model and SKU", () => {
  expect(consumedItemLabel(row({}))).toBe("Bolt (CN-BLT-010)")
})

test("a UNIT row is labelled by its serial, not the model", () => {
  expect(
    consumedItemLabel(row({ line_kind: "UNIT", unit_serial: "CN-4471-A" })),
  ).toBe("CN-4471-A")
})

test("a UNIT row with no serial falls back rather than rendering null", () => {
  expect(consumedItemLabel(row({ line_kind: "UNIT", unit_serial: null }))).toBe(
    "(no serial)",
  )
})
