# CastraNova-POS — Customer Creation (inline + admin screen)

**Date:** 2026-06-16
**Status:** Approved (design)
**Author:** pairing session (wai1998)

## Problem

There is no way to create a customer through the app. Every customer-consuming
screen — Sale (`sale.tsx`), Tickets (`tickets.tsx`), Projects (`projects.tsx`) —
only **picks** an existing customer from a `<Select>` dropdown. There is no
"Customers" sidebar entry, no create form, and no inline-create affordance.

`CustomersService.createCustomer` exists in the generated SDK but is **never
called anywhere in the app** (only the generated client files reference it).

This is a dead-end UX: if the needed customer is not already in the dropdown
(and on a fresh DB the list can be empty — there is no seeded "walk-in"
customer, so `findWalkIn` never matches), the user cannot complete a sale, open
a ticket, or create a project, with no path forward.

### Root cause

The "create customer inline during a sale" capability specified by **FR-007 +
D25** (system-design `2026-05-23-…-system-design.md` §4.2 line 152, §5 Flow A
line 245, §8 line 539: *"customers … staff read + create … Inline-create per
FR-007"*) was **never implemented in the frontend**. The backend is complete:
`POST /customers` is open to `get_current_user` (staff + admin), `GET /customers`
and `PATCH /customers/{id}` (admin) exist.

## Scope

Frontend-only. **No backend, migration, or SDK changes** — the endpoints and
SDK methods already exist.

Decision (user): build **both** an inline create (point of need) and an admin
management screen (list / create / edit).

## Backend contract (existing — for reference)

`CustomerCreate` / `CustomerBase` fields (`backend/app/models.py`):

| Field     | Type                              | Required | Limit |
|-----------|-----------------------------------|----------|-------|
| `name`    | `str`                             | yes      | ≤255  |
| `country` | `str \| None`                     | no       | ≤64   |
| `contact` | `str \| None`                     | no       | ≤255  |
| `type`    | `CustomerType` (`DEALER` / `END_CUSTOMER`) | no (default `END_CUSTOMER`) | — |
| `notes`   | `str \| None`                     | no       | ≤1024 |

Endpoints: `POST /customers` (staff+admin), `GET /customers` (auth),
`PATCH /customers/{id}` (admin).

## Components

### 1. `frontend/src/lib/customer-create.ts` (pure, testable)

Mirrors `lib/supplier-create.ts`.

```
interface CustomerDraft { name; country?; contact?; type; notes? }
canCreateCustomer(d): boolean        // true iff d.name.trim() !== ""
buildCustomerPayload(d): CustomerCreate  // trims; omits blank optionals; type defaults END_CUSTOMER
```

This is the unit-tested core (TDD).

### 2. `frontend/src/components/pos/CustomerCreateDialog.tsx` (inline)

- shadcn `Dialog` (existing `ui/dialog.tsx`).
- Fields (lean for counter speed): **Name** (required), **Type** (Select:
  DEALER / END_CUSTOMER, default END_CUSTOMER), **Contact** (optional).
  Country / Notes are intentionally **admin-screen only**.
- On submit: `CustomersService.createCustomer({ requestBody })` →
  `queryClient.invalidateQueries(["customers"])` → `onCreated(customer)` so the
  caller can auto-select the new customer → close dialog, reset fields.
- Error → `useCustomToast` error toast; submit disabled while pending /
  `!canCreateCustomer`.

Trigger: a **"+ New customer" button rendered beside the existing `<Select>`**
(NOT inside `SelectContent` — Radix Select + Dialog focus traps conflict).

Wired into:
- **Sale** — `CheckoutPanel` (desktop pane + mobile sticky footer instances).
- **Tickets** — `CustomerPicker` (desktop + mobile instances).

Available to staff + admin (both routes are `requireAuth`), per FR-007/D25.

### 3. `frontend/src/routes/_layout/customers.tsx` (admin)

- Mirrors `suppliers.tsx`: `beforeLoad: requireAdmin`, list + create form.
- Create form fields: Name, Type, Contact, Country, Notes.
- List columns: Name, Type, Contact, Country, + per-row **Edit** button.
- Edit: opens a dialog reusing the form, submits `CustomersService.updateCustomer`
  (admin PATCH). Reuses `canCreateCustomer` for enable-gating.
- Invalidate `["customers"]` on create/edit success.

### 4. Sidebar — `frontend/src/components/Sidebar/AppSidebar.tsx`

Add to the **Catalog** group, between Suppliers and Projects:

```
{ icon: Contact, title: "Customers", path: "/customers" }
```

(`Contact` from `lucide-react`; `Users` is already taken by Admin.)

`routeTree.gen.ts` regenerates automatically (never hand-edited).

## Data flow

```
Sale/Tickets picker  ──"+ New customer"──▶ CustomerCreateDialog
        ▲                                        │ POST /customers
        │ auto-select new customer  ◀────────────┘ invalidate ["customers"]

Sidebar ▶ /customers (admin) ─ create/edit ─▶ POST / PATCH /customers
                                              invalidate ["customers"]
```

The `["customers"]` query key is shared by Sale, Tickets, Projects and the new
admin screen, so any create/edit refreshes every dropdown.

## Error handling

- Network/validation failure → error toast, dialog/form stays open, fields
  preserved, submit re-enabled.
- Submit disabled unless `canCreateCustomer` and not pending.

## Testing

- **Mandatory (TDD):** `lib/customer-create.test.ts` — `canCreateCustomer`
  (empty/whitespace name → false; valid → true) and `buildCustomerPayload`
  (trims, drops blank optionals, defaults type).
- **Recommended:** one Playwright E2E — inline create during a sale auto-selects
  the new customer; admin Customers create appears in the list.
- Not "high-risk" per CLAUDE.md (no FIFO / ledger / money), so the
  database-reviewer + security-reviewer belt-and-suspenders gate is not required;
  standard `requesting-code-review` applies.

## Out of scope (follow-ups)

- **Seeded "walk-in" customer.** `findWalkIn` only matches an existing
  customer; nothing seeds one. Worth adding to `initial_data.py` so the Sale
  default works on a fresh DB — tracked separately, not in this change.
- Inline create on the Projects screen (admin uses the new Customers screen).
- Customer dedup / merge (already deferred to v1.1, S3/D34).
```
