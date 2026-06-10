import { expect, test } from "@playwright/test"
import {
  buildSupplierPayload,
  canCreateSupplier,
} from "../src/lib/supplier-create"

// Pure form logic for the admin Suppliers create form (FR-003). Only `name` is
// required; blank optional fields are normalized to undefined so the payload
// matches what the backend accepts.

test("canCreateSupplier requires a non-blank name", () => {
  expect(canCreateSupplier({ name: "Acme", country: "", contact: "" })).toBe(
    true,
  )
  expect(canCreateSupplier({ name: "  ", country: "TH", contact: "x" })).toBe(
    false,
  )
})

test("buildSupplierPayload trims and drops blank optionals", () => {
  expect(
    buildSupplierPayload({ name: "  Acme ", country: " TH ", contact: "" }),
  ).toEqual({ name: "Acme", country: "TH" })
  expect(
    buildSupplierPayload({ name: "Acme", country: "", contact: "" }),
  ).toEqual({ name: "Acme" })
})
