# Supplier & Project Edit Dialogs — Design

**Date:** 2026-06-19
**Status:** Approved (brainstorming)
**Scope:** Frontend-only. Admin-only `PATCH` endpoints already exist for both.

## Problem

The Suppliers and Projects admin pages can create + list records, but their tables
are read-only — no way to edit. (Customers **already has** a committed edit dialog,
`CustomerEditDialog`, so it is explicitly out of scope here.) Add per-row Edit
dialogs to Suppliers and Projects, mirroring the existing committed customer pattern.

## Reference pattern (already in the codebase — `customers.tsx`, committed)

`CustomerEditDialog({ customer, onClose })`:
- `useState` draft seeded from the entity.
- `useMutation` → `CustomersService.updateCustomer({ customerId, requestBody: buildCustomerPayload(draft) })`; `onSuccess` invalidates `["customers"]`, success toast, `onClose()`; `onError` error toast.
- `canSave = canCreateCustomer(draft) && !mutation.isPending`.
- Renders `<Dialog open onOpenChange={(next) => { if (!next) onClose() }}>` with the shared fieldset + a Save button.

Page wiring: `const [editing, setEditing] = useState<CustomerPublic | null>(null)`;
each table row has an Edit button `onClick={() => setEditing(c)}`; the page renders
`{editing && <CustomerEditDialog customer={editing} onClose={() => setEditing(null)} />}`.

**Suppliers and Projects will mirror this exactly.**

## Backend (already in place — no changes)

- `PATCH /suppliers/{id}` (admin) ← `SupplierUpdate { name, country, contact }`. SDK `SuppliersService.updateSupplier`.
- `PATCH /projects/{id}` (admin) ← `ProjectUpdate { code, name, customer_id, start_date, end_date, status, budget_thb }`. SDK `ProjectsService.updateProject`.
- `crud.update_*` use `model_dump(exclude_unset=True)`.

## Decisions (locked in brainstorming)

- **Supplier edit:** name (required), country, contact — all create-form fields.
- **Project edit:** name (required), customer (select), status (Active/Closed),
  start date, end date, budget. **Code is read-only** (project identity).
- **Edit trigger:** a per-row **Edit** button in the desktop **table**. The mobile
  card views on these pages are part of the user's uncommitted WIP; adding an Edit
  button there belongs with that WIP and is **out of scope** here (noted as
  follow-up) so the feature commit does not depend on WIP code.
- **Customers:** out of scope (already implemented + committed). `customers.tsx` is
  not touched.

## Components

### Supplier

1. **`SupplierEditDialog`** (new — colocate in `suppliers.tsx`, mirroring how
   `CustomerEditDialog` lives in `customers.tsx`).
   - Props `{ supplier: SupplierPublic, onClose: () => void }`.
   - Draft `{ name, country, contact }` seeded from `supplier`.
   - Reuses existing `canCreateSupplier` + `buildSupplierPayload` from
     `lib/supplier-create.ts` (Supplier create == update fields).
   - Mutation → `updateSupplier({ supplierId: supplier.id, requestBody })`;
     invalidate `["suppliers"]`; success/error toasts; `onClose`.
   - Inlines three labelled inputs (Name/Country/Contact) — same fields as the
     create card. (The create card is not refactored, to avoid touching WIP more
     than necessary.)
2. **`suppliers.tsx`** page: add `editing` state, an Edit button in each desktop
   table row (`onClick={() => setEditing(s)}`), and render the dialog when editing.

### Project

3. **`lib/project-edit.ts`** (new, pure — `product-edit.ts` style)
   - `ProjectEditDraft { name, customerId, status, startDate, endDate, budget }`
     (all strings; `status` is `ProjectStatus`).
   - `projectToEditDraft(p: ProjectPublic): ProjectEditDraft`.
   - `canSaveProject(d): boolean` — `name` non-empty, `customerId` non-empty, and
     (if `budget` non-blank) a valid non-negative number.
   - `buildProjectUpdate(d): ProjectUpdate` — `name` trimmed; `customer_id`;
     `status`; `start_date`/`end_date` → the trimmed `YYYY-MM-DD` string or `null`
     when blank; `budget_thb` → trimmed string when a valid non-negative number,
     else `null`. **Does not send `code`** (read-only).
4. **`ProjectEditDialog`** (new — colocate in `projects.tsx`, mirroring the customer
   pattern).
   - Props `{ project: ProjectPublic, customers: CustomerPublic[], onClose }`.
   - Draft via `projectToEditDraft`; Code shown read-only (disabled input).
   - Customer `<Select>` (options from the page's `["customers"]` query — already
     fetched on the projects page for the create form), Status `<Select>`
     (Active/Closed), two native date inputs, a budget number input.
   - Mutation → `updateProject({ projectId, requestBody: buildProjectUpdate(draft) })`;
     invalidate `["projects"]`; toasts; `onClose`. Save gated on `canSaveProject`
     plus a dirty-check (no no-op PATCH bumping `updated_at`).
5. **`projects.tsx`** page: add `editing` state + per-row Edit button + dialog render.

## Data flow

Edit click → `setEditing(row)` → dialog opens seeded from the row → admin edits →
Save → `PATCH /{id}` → list query invalidated → table reflects the change.

## Error handling

Backend 4xx → error toast (mirror the customer dialog's `onError`). Project budget
validated client-side (non-negative) before Save enables.

## Testing

- **Unit (Playwright pure-logic spec):** `buildProjectUpdate` + `canSaveProject` —
  required name/customer, budget validation (blank ok, negative/non-numeric rejected),
  blank dates → `null`, `code` never present, status passthrough. (Supplier reuses
  the already-tested `supplier-create` helpers, so no new unit test needed there.)
- **E2E:** (a) edit a supplier's contact and assert the table row updates;
  (b) edit a project's status/budget and assert the row updates. Mirror the auth
  setup used by existing specs.

## WIP isolation (the user's uncommitted refactor must stay untouched)

`suppliers.tsx` and `projects.tsx` carry uncommitted WIP (PageHeader Alert + mobile
card view). The controller adds the edit feature against the **committed (HEAD)**
version of each file and commits ONLY that, then restores the WIP and re-applies the
feature so the WIP stays uncommitted — verified with `git diff` after each (the
uncommitted diff must contain only the WIP, never the edit feature). `customers.tsx`
is not touched at all.

## Out of scope / backlog

- Customer edit (done). Editing project `code`. Edit buttons inside the mobile card
  views (belongs with the WIP that introduces those cards). Deleting/deactivating.
