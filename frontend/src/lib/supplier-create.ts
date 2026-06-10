import type { SupplierCreate } from "@/client/types.gen"

// ---------------------------------------------------------------------------
// Pure form logic for the admin Suppliers create form (FR-003). Mirrors
// project-create.ts: only `name` is required; blank optionals are dropped.
// ---------------------------------------------------------------------------

export interface SupplierDraft {
  name: string
  country: string
  contact: string
}

export function canCreateSupplier(d: SupplierDraft): boolean {
  return d.name.trim() !== ""
}

export function buildSupplierPayload(d: SupplierDraft): SupplierCreate {
  const payload: SupplierCreate = { name: d.name.trim() }
  const country = d.country.trim()
  const contact = d.contact.trim()
  if (country) payload.country = country
  if (contact) payload.contact = contact
  return payload
}
