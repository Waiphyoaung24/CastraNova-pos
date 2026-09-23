import type {
  ProjectConsumptionRowPublic,
  ProjectDashboardAdminPublic,
  ProjectDashboardStaffPublic,
  ProjectPullPublic,
} from "@/client/types.gen"
import { returnedQty } from "@/lib/pull-return"

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
  /** Supplied and not yet back. */
  inUse: number
}

export interface ItemTotalsRow extends ItemTotals {
  productId: string
  label: string
}

/**
 * Per-product totals across a project's requests, plus the grand total.
 * Cancelled requests allocated nothing, so they are left out. A UNIT line is
 * one serial, so it allocates one.
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
    inUse: 0,
  }
  for (const pull of pulls) {
    if (pull.state === "CANCELLED") continue
    for (const line of pull.lines) {
      const row = byProduct.get(line.product_id) ?? {
        productId: line.product_id,
        label: `${line.model_name} (${line.product_sku})`,
        allocated: 0,
        supplied: 0,
        returned: 0,
        inUse: 0,
      }
      const add: ItemTotals = {
        allocated: line.requested_qty ?? 1,
        supplied: line.fulfilled_qty,
        returned: returnedQty(pull, line),
        inUse: line.fulfilled_qty - returnedQty(pull, line),
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
