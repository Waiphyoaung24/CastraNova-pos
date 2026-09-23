import { describe, expect, it } from "vitest"

import type {
  ProjectPullLinePublic,
  ProjectPullPublic,
} from "@/client/types.gen"
import { projectItemTotals } from "./project-dashboard"

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
    ...over,
  }
}

function pull(
  state: ProjectPullPublic["state"],
  lines: ProjectPullLinePublic[],
): ProjectPullPublic {
  return { state, lines } as ProjectPullPublic
}

describe("projectItemTotals", () => {
  it("sums each product across requests, skipping cancelled ones", () => {
    const { rows, totals } = projectItemTotals([
      pull("FULFILLED", [line({ returnable_qty: 3 })]), // 2 came back
      pull("PENDING", [line({ requested_qty: 4, fulfilled_qty: 0 })]),
      pull("CANCELLED", [line({ requested_qty: 9, fulfilled_qty: 0 })]),
      pull("SHORT", [
        line({
          line_kind: "UNIT",
          product_id: "cmp",
          product_sku: "C-1",
          model_name: "Compressor",
          unit_serial: "CN-1",
          requested_qty: null,
          fulfilled_qty: 1,
          returnable_qty: 1,
        }),
      ]),
    ])
    expect(rows).toEqual([
      {
        productId: "bolt",
        label: "Bolt (B-1)",
        allocated: 9,
        supplied: 5,
        returned: 2,
        inUse: 3,
      },
      {
        productId: "cmp",
        label: "Compressor (C-1)",
        allocated: 1,
        supplied: 1,
        returned: 0,
        inUse: 1,
      },
    ])
    expect(totals).toEqual({
      allocated: 10,
      supplied: 6,
      returned: 2,
      inUse: 4,
    })
  })

  it("is empty with no requests", () => {
    expect(projectItemTotals([]).rows).toEqual([])
  })
})
