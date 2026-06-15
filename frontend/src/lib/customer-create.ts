import type { CustomerCreate, CustomerType } from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure form logic for customer creation (FR-007 + D25). Shared by the inline
// "+ New customer" dialog (Sale/Tickets) and the admin Customers screen.
// Mirrors the backend CustomerCreate: only `name` is required; `type` is always
// sent (UI default END_CUSTOMER); blank optionals are dropped so submit only
// produces a body the server will accept.
// ---------------------------------------------------------------------------

export interface CustomerDraft {
  name: string
  type: CustomerType
  contact?: string
  country?: string
  notes?: string
}

export function canCreateCustomer(d: CustomerDraft): boolean {
  return d.name.trim() !== ""
}

export function buildCustomerPayload(d: CustomerDraft): CustomerCreate {
  const payload: CustomerCreate = { name: d.name.trim(), type: d.type }
  const country = d.country?.trim()
  const contact = d.contact?.trim()
  const notes = d.notes?.trim()
  if (country) payload.country = country
  if (contact) payload.contact = contact
  if (notes) payload.notes = notes
  return payload
}
