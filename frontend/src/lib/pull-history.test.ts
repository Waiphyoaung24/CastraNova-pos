import { describe, expect, it } from "vitest"

import type {
  ProjectPullLinePublic,
  ProjectPullPublic,
} from "@/client/types.gen"
import { groupPullsByProject, pullTotals } from "./pull-history"

function line(over: Partial<ProjectPullLinePublic>): ProjectPullLinePublic {
  return {
    id: crypto.randomUUID(),
    line_kind: "PART",
    product_id: "bolt",
    product_sku: "B-1",
    model_name: "Bolt",
    unit_serial: null,
    requested_qty: 5,
    fulfilled_qty: 5,
    line_state: "FULFILLED",
    returnable_qty: 5,
    returned_qty: 0,
    ...over,
  }
}

function pull(
  state: ProjectPullPublic["state"],
  lines: ProjectPullLinePublic[],
  over: Partial<ProjectPullPublic> = {},
): ProjectPullPublic {
  return { state, lines, ...over } as ProjectPullPublic
}

describe("pullTotals", () => {
  it("sums requests from the ledger numbers", () => {
    expect(
      pullTotals([
        // 2 came back, 3 still out
        pull("FULFILLED", [line({ returnable_qty: 3, returned_qty: 2 })]),
        // Waiting: deducted at create, so out of stock but not supplied yet
        pull("PENDING", [
          line({ requested_qty: 4, fulfilled_qty: 0, returnable_qty: 4 }),
        ]),
        // Cancelled while waiting: its stock went back as RETURNED movements,
        // but nothing was supplied, so nothing counts as allocated or returned
        pull("CANCELLED", [
          line({ fulfilled_qty: 0, returnable_qty: 0, returned_qty: 5 }),
        ]),
        // A UNIT line is one serial
        pull("SHORT", [
          line({
            line_kind: "UNIT",
            requested_qty: null,
            fulfilled_qty: 1,
            returnable_qty: 1,
          }),
        ]),
      ]),
    ).toEqual({ allocated: 10, supplied: 6, returned: 2, stillOut: 8 })
  })

  it("keeps a short hand-out's surplus out until it is returned", () => {
    expect(
      pullTotals([
        pull("SHORT", [line({ fulfilled_qty: 3, returnable_qty: 5 })]),
      ]),
    ).toEqual({ allocated: 5, supplied: 3, returned: 0, stillOut: 5 })
  })
})

describe("groupPullsByProject", () => {
  const at = (
    project_id: string,
    created_at: string,
    l: ProjectPullLinePublic,
  ) =>
    pull("FULFILLED", [l], {
      id: crypto.randomUUID(),
      project_id,
      project_name: `Site ${project_id}`,
      project_code: `PRJ-${project_id}`,
      customer_name: `Cust ${project_id}`,
      created_at,
    })

  it("groups newest-first pulls per project, keeping order and totals", () => {
    const a2 = at("a", "2026-09-03T00:00:00Z", line({}))
    const b1 = at(
      "b",
      "2026-09-02T00:00:00Z",
      line({ returnable_qty: 1, returned_qty: 4 }),
    )
    const a1 = at("a", "2026-09-01T00:00:00Z", line({}))
    const groups = groupPullsByProject([a2, b1, a1])
    expect(groups.map((g) => g.projectId)).toEqual(["a", "b"])
    expect(groups[0]).toMatchObject({
      name: "Site a",
      code: "PRJ-a",
      customerName: "Cust a",
      lastAt: "2026-09-03T00:00:00Z",
      pulls: [a2, a1],
      totals: { allocated: 10, supplied: 10, returned: 0, stillOut: 10 },
    })
    expect(groups[1].totals).toEqual({
      allocated: 5,
      supplied: 5,
      returned: 4,
      stillOut: 1,
    })
  })
})
