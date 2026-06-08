import { expect, test } from "@playwright/test"
import { roleFlags } from "../src/hooks/useRole"

// Pure-logic coverage of roleFlags helper (Task 2.2).
// No browser / auth / backend required — mirrors scanner.spec.ts pattern.

test("superuser with no role → isAdmin true, isStaff false", () => {
  expect(roleFlags({ is_superuser: true })).toEqual({
    isAdmin: true,
    isStaff: false,
    role: null,
  })
})

test("superuser with BKK_ADMIN role → isAdmin true, isStaff false", () => {
  expect(roleFlags({ is_superuser: true, role: "BKK_ADMIN" })).toEqual({
    isAdmin: true,
    isStaff: false,
    role: "BKK_ADMIN",
  })
})

test("superuser with YGN_STAFF role → isAdmin true, isStaff false (superuser wins)", () => {
  expect(roleFlags({ is_superuser: true, role: "YGN_STAFF" })).toEqual({
    isAdmin: true,
    isStaff: false,
    role: "YGN_STAFF",
  })
})

test("BKK_ADMIN (not superuser) → isAdmin true, isStaff false", () => {
  expect(roleFlags({ is_superuser: false, role: "BKK_ADMIN" })).toEqual({
    isAdmin: true,
    isStaff: false,
    role: "BKK_ADMIN",
  })
})

test("YGN_STAFF (not superuser) → isStaff true, isAdmin false", () => {
  expect(roleFlags({ is_superuser: false, role: "YGN_STAFF" })).toEqual({
    isAdmin: false,
    isStaff: true,
    role: "YGN_STAFF",
  })
})

test("no role + not superuser → both false, role null", () => {
  expect(roleFlags({ is_superuser: false })).toEqual({
    isAdmin: false,
    isStaff: false,
    role: null,
  })
})

test("null user → both false, role null", () => {
  expect(roleFlags(null)).toEqual({
    isAdmin: false,
    isStaff: false,
    role: null,
  })
})

test("undefined user → both false, role null", () => {
  expect(roleFlags(undefined)).toEqual({
    isAdmin: false,
    isStaff: false,
    role: null,
  })
})
