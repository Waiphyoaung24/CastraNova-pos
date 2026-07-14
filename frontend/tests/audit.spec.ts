import { expect, test } from "@playwright/test"
import {
  buildAuditQuery,
  movementSource,
  summarizeAudit,
} from "../src/lib/audit"

// Pure-logic coverage for the admin audit ledger filters (FR-019). Blank
// filters are dropped so the request only constrains what the admin set.

test("buildAuditQuery drops blank filters", () => {
  expect(
    buildAuditQuery({
      eventType: "",
      fromDate: "",
      toDate: "",
      actorUserId: "",
      sku: "",
    }),
  ).toEqual({})
})

test("buildAuditQuery includes set filters", () => {
  expect(
    buildAuditQuery({
      eventType: "SOLD",
      fromDate: "2026-06-01",
      toDate: "2026-07-01",
      actorUserId: "u-1",
      sku: "ABC-123",
    }),
  ).toEqual({
    eventType: "SOLD",
    fromDate: "2026-06-01",
    toDate: "2026-07-01",
    actorUserId: "u-1",
    sku: "ABC-123",
  })
})

// --- movementSource ---------------------------------------------------------

test("movementSource maps the linked id to a labelled source, null when none", () => {
  expect(movementSource({ sale_id: "s-1" })).toEqual({
    kind: "sale",
    label: "Sale",
  })
  expect(movementSource({ service_ticket_id: "t-1" })).toEqual({
    kind: "ticket",
    label: "Service ticket",
  })
  expect(movementSource({ project_pull_id: "p-1" })).toEqual({
    kind: "pull",
    label: "Project pull",
  })
  expect(movementSource({ stock_adjustment_id: "a-1" })).toEqual({
    kind: "adjustment",
    label: "Adjustment",
  })
  expect(
    movementSource({
      sale_id: null,
      service_ticket_id: null,
      project_pull_id: null,
      stock_adjustment_id: null,
    }),
  ).toBeNull()
})

// --- summarizeAudit ---------------------------------------------------------

test("summarizeAudit counts movements, distinct actors, and in/out split", () => {
  const summary = summarizeAudit([
    { actor_user_id: "u-1", event_type: "RECEIVED" },
    { actor_user_id: "u-1", event_type: "SOLD" },
    { actor_user_id: "u-2", event_type: "ADJUSTED_OUT" },
    { actor_user_id: "u-2", event_type: "RECEIVED" },
  ])
  expect(summary).toEqual({
    total: 4,
    distinctActors: 2,
    received: 2,
    outflow: 2,
  })
})

test("summarizeAudit handles the empty page", () => {
  expect(summarizeAudit([])).toEqual({
    total: 0,
    distinctActors: 0,
    received: 0,
    outflow: 0,
  })
})
