import { expect, test } from "@playwright/test"
import {
  buildCustomerPayload,
  type CustomerDraft,
  canCreateCustomer,
} from "../src/lib/customer-create"

// Pure form logic for customer creation (FR-007 + D25), shared by the inline
// "+ New customer" dialog (Sale/Tickets) and the admin Customers screen. Only
// `name` is required; `type` is always sent (UI default END_CUSTOMER); blank
// optional fields are dropped so the payload matches what the backend accepts.

function draft(over: Partial<CustomerDraft>): CustomerDraft {
  return {
    name: "",
    type: "END_CUSTOMER",
    contact: "",
    country: "",
    notes: "",
    ...over,
  }
}

test("canCreateCustomer requires a non-blank name", () => {
  expect(canCreateCustomer(draft({ name: "Acme" }))).toBe(true)
  expect(canCreateCustomer(draft({ name: "  " }))).toBe(false)
  expect(canCreateCustomer(draft({ name: "" }))).toBe(false)
})

test("buildCustomerPayload trims name and always includes type", () => {
  expect(
    buildCustomerPayload(draft({ name: "  Acme ", type: "DEALER" })),
  ).toEqual({ name: "Acme", type: "DEALER" })
})

test("buildCustomerPayload drops blank optionals and keeps non-blank ones", () => {
  expect(
    buildCustomerPayload(
      draft({ name: "Acme", contact: " 0123 ", country: "", notes: "  " }),
    ),
  ).toEqual({ name: "Acme", type: "END_CUSTOMER", contact: "0123" })
})
