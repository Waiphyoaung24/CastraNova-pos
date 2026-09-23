import type {
  ProjectConsumptionRowPublic,
  ProjectDashboardAdminPublic,
  ProjectDashboardStaffPublic,
  ProjectPullLinePublic,
  ProjectPullPublic,
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

/**
 * How a consumed-items row identifies itself: a SERIALIZED unit is its serial
 * (that is the piece that left the warehouse), a QUANTITY part is its model and
 * SKU. Mirrors the pull-fulfill panel's line label so the two screens name the
 * same item the same way.
 */
export function consumedItemLabel(row: ProjectConsumptionRowPublic): string {
  if (row.line_kind === "UNIT") return row.unit_serial ?? "(no serial)"
  return `${row.model_name} (${row.product_sku})`
}

export interface ItemTotals {
  allocated: number
  supplied: number
  returned: number
  /** Out of stock on this project and not back yet (ledger, not inferred). */
  stillOut: number
}

/**
 * Returns of what was actually handed over. A cancel (or a return of a short
 * hand-out's surplus) also writes RETURNED movements, but that stock never
 * reached the project, so it doesn't read as "returned".
 */
export function suppliedReturned(line: ProjectPullLinePublic): number {
  return Math.min(line.returned_qty ?? 0, line.fulfilled_qty)
}

export interface ItemTotalsRow extends ItemTotals {
  productId: string
  label: string
}

/**
 * Per-product totals across a project's requests, plus the grand total.
 * Returned and still-out come from the ledger (a short hand-out keeps its
 * surplus out until returned). A cancelled request allocated only what it
 * handed out before closing. A UNIT line is one serial, so it allocates one.
 */
export function projectItemTotals(pulls: ProjectPullPublic[]): {
  rows: ItemTotalsRow[]
  totals: ItemTotals
} {
  const byProduct = new Map<string, ItemTotalsRow>()
  const totals: ItemTotals = {
    allocated: 0,
    supplied: 0,
    returned: 0,
    stillOut: 0,
  }
  for (const pull of pulls) {
    const cancelled = pull.state === "CANCELLED"
    for (const line of pull.lines) {
      const row = byProduct.get(line.product_id) ?? {
        productId: line.product_id,
        label: `${line.model_name} (${line.product_sku})`,
        allocated: 0,
        supplied: 0,
        returned: 0,
        stillOut: 0,
      }
      const add: ItemTotals = {
        allocated: cancelled ? line.fulfilled_qty : (line.requested_qty ?? 1),
        supplied: line.fulfilled_qty,
        returned: suppliedReturned(line),
        stillOut: line.returnable_qty ?? 0,
      }
      for (const k of Object.keys(add) as (keyof ItemTotals)[]) {
        row[k] += add[k]
        totals[k] += add[k]
      }
      byProduct.set(line.product_id, row)
    }
  }
  return { rows: [...byProduct.values()], totals }
}

export interface ProjectPullGroup {
  projectId: string
  label: string
  customerName: string
  /** Newest request first, as the list came in. */
  pulls: ProjectPullPublic[]
  lastAt: string
  totals: ItemTotals
}

/** Newest-first pulls grouped per project, projects ordered by latest request. */
export function groupPullsByProject(
  pulls: ProjectPullPublic[],
): ProjectPullGroup[] {
  const byProject = new Map<string, ProjectPullPublic[]>()
  for (const pull of pulls) {
    byProject.set(pull.project_id, [
      ...(byProject.get(pull.project_id) ?? []),
      pull,
    ])
  }
  return [...byProject.values()].map((group) => ({
    projectId: group[0].project_id,
    label: `${group[0].project_name} (${group[0].project_code})`,
    customerName: group[0].customer_name,
    pulls: group,
    lastAt: group[0].created_at,
    totals: projectItemTotals(group).totals,
  }))
}
