import { expect, test } from "@playwright/test"
import { roleFlags, tierLabel } from "../src/hooks/useRole"

// Pure-logic coverage of roleFlags + tierLabel helpers.
// No browser / auth / backend required — mirrors scanner.spec.ts pattern.

test("superuser with no role → isAdmin/isSuperuser true, isStaff false", () => {
  expect(roleFlags({ is_superuser: true })).toEqual({
    isAdmin: true,
    isStaff: false,
    isSuperuser: true,
    role: null,
  })
})

test("superuser with BKK_ADMIN role → isAdmin/isSuperuser true", () => {
  expect(roleFlags({ is_superuser: true, role: "BKK_ADMIN" })).toEqual({
    isAdmin: true,
    isStaff: false,
    isSuperuser: true,
    role: "BKK_ADMIN",
  })
})

test("superuser with YGN_STAFF role → superuser wins", () => {
  expect(roleFlags({ is_superuser: true, role: "YGN_STAFF" })).toEqual({
    isAdmin: true,
    isStaff: false,
    isSuperuser: true,
    role: "YGN_STAFF",
  })
})

test("BKK_ADMIN (not superuser) → isAdmin true, isSuperuser false", () => {
  expect(roleFlags({ is_superuser: false, role: "BKK_ADMIN" })).toEqual({
    isAdmin: true,
    isStaff: false,
    isSuperuser: false,
    role: "BKK_ADMIN",
  })
})

test("YGN_STAFF (not superuser) → isStaff true, isAdmin/isSuperuser false", () => {
  expect(roleFlags({ is_superuser: false, role: "YGN_STAFF" })).toEqual({
    isAdmin: false,
    isStaff: true,
    isSuperuser: false,
    role: "YGN_STAFF",
  })
})

test("no role + not superuser → all false, role null", () => {
  expect(roleFlags({ is_superuser: false })).toEqual({
    isAdmin: false,
    isStaff: false,
    isSuperuser: false,
    role: null,
  })
})

test("null user → all false, role null", () => {
  expect(roleFlags(null)).toEqual({
    isAdmin: false,
    isStaff: false,
    isSuperuser: false,
    role: null,
  })
})

test("undefined user → all false, role null", () => {
  expect(roleFlags(undefined)).toEqual({
    isAdmin: false,
    isStaff: false,
    isSuperuser: false,
    role: null,
  })
})

test("tierLabel: superuser → 'Superuser'", () => {
  expect(tierLabel({ is_superuser: true })).toBe("Superuser")
})

test("tierLabel: superuser wins over staff role", () => {
  expect(tierLabel({ is_superuser: true, role: "YGN_STAFF" })).toBe("Superuser")
})

test("tierLabel: BKK_ADMIN (not superuser) → 'Admin'", () => {
  expect(tierLabel({ is_superuser: false, role: "BKK_ADMIN" })).toBe("Admin")
})

test("tierLabel: YGN_STAFF → 'Staff'", () => {
  expect(tierLabel({ is_superuser: false, role: "YGN_STAFF" })).toBe("Staff")
})

test("tierLabel: no role + not superuser → 'Staff' (least privilege)", () => {
  expect(tierLabel({ is_superuser: false })).toBe("Staff")
})

test("tierLabel: null user → 'Staff'", () => {
  expect(tierLabel(null)).toBe("Staff")
})
