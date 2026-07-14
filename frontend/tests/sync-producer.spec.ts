import { expect, test } from "@playwright/test"
import {
  buildSyncReviewItem,
  isStale,
  type Queued,
  SYNC_STALE_MS,
  shouldDivertConflict,
  staleItemFor,
} from "../src/lib/sync-producer"

// Pure-logic coverage of the offline sync-review producer. No browser/React/
// backend required — mirrors receive-form.spec.ts.

const NOW = 1_000_000_000_000 // fixed clock; Date.now() is never called here.

function q(
  body: unknown,
  meta: Partial<Queued<unknown>["meta"]>,
): Queued<unknown> {
  return {
    body,
    meta: {
      submittedAt: NOW,
      queuedOffline: true,
      idempotencyKey: "idem-1",
      ...meta,
    },
  }
}

// --- isStale ---------------------------------------------------------------

test("isStale: false just under the 7-day cap", () => {
  expect(isStale(NOW - (SYNC_STALE_MS - 60_000), NOW)).toBe(false)
})

test("isStale: true just over the 7-day cap", () => {
  expect(isStale(NOW - (SYNC_STALE_MS + 60_000), NOW)).toBe(true)
})

test("isStale: false for undefined submittedAt", () => {
  expect(isStale(undefined, NOW)).toBe(false)
})

// --- buildSyncReviewItem ---------------------------------------------------

test("buildSyncReviewItem maps kind, payload, key, reason", () => {
  const item = buildSyncReviewItem(
    ["pull-fulfill"],
    q({ pullId: "p1", body: { lines: [] } }, { idempotencyKey: "k9" }),
    "CONFLICT",
  )
  expect(item).toEqual({
    idempotency_key: "k9",
    mutation_kind: "pull-fulfill",
    payload: { pullId: "p1", body: { lines: [] } },
    reason: "CONFLICT",
  })
})

test("buildSyncReviewItem returns null when meta or key is missing", () => {
  expect(buildSyncReviewItem(["sales"], undefined, "STALE")).toBeNull()
  expect(buildSyncReviewItem(undefined, q({}, {}), "STALE")).toBeNull()
  expect(buildSyncReviewItem([], q({}, {}), "STALE")).toBeNull()
})

// --- staleItemFor ----------------------------------------------------------

test("staleItemFor diverts a paused, stale mutation as STALE", () => {
  const item = staleItemFor(
    true,
    ["sales"],
    q(
      { x: 1 },
      { submittedAt: NOW - (SYNC_STALE_MS + 1), idempotencyKey: "s1" },
    ),
    NOW,
  )
  expect(item).toEqual({
    idempotency_key: "s1",
    mutation_kind: "sales",
    payload: { x: 1 },
    reason: "STALE",
  })
})

test("staleItemFor ignores a fresh mutation", () => {
  expect(
    staleItemFor(true, ["sales"], q({ x: 1 }, { submittedAt: NOW }), NOW),
  ).toBeNull()
})

test("staleItemFor ignores a non-paused (in-flight) mutation", () => {
  expect(
    staleItemFor(
      false,
      ["sales"],
      q({ x: 1 }, { submittedAt: NOW - (SYNC_STALE_MS + 1) }),
      NOW,
    ),
  ).toBeNull()
})

// --- shouldDivertConflict --------------------------------------------------

test("shouldDivertConflict: offline-origin 409 diverts", () => {
  expect(
    shouldDivertConflict(409, {
      submittedAt: NOW,
      queuedOffline: true,
      idempotencyKey: "i",
    }),
  ).toBe(true)
})

test("shouldDivertConflict: online 409 does not divert", () => {
  expect(
    shouldDivertConflict(409, {
      submittedAt: NOW,
      queuedOffline: false,
      idempotencyKey: "i",
    }),
  ).toBe(false)
})

test("shouldDivertConflict: non-409 does not divert", () => {
  expect(
    shouldDivertConflict(400, {
      submittedAt: NOW,
      queuedOffline: true,
      idempotencyKey: "i",
    }),
  ).toBe(false)
})

test("shouldDivertConflict: undefined meta does not divert", () => {
  expect(shouldDivertConflict(409, undefined)).toBe(false)
})
