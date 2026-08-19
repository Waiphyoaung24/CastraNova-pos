# Supplier & Project Edit Dialogs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-row Edit dialogs to the Suppliers and Projects admin pages (customers already has one), mirroring the committed `CustomerEditDialog` pattern.

**Architecture:** Frontend-only. Each dialog lives in its own clean component file (`{entity, onClose}` props), so the WIP-carrying page files (`suppliers.tsx`, `projects.tsx`) only receive a tiny import + `editing` state + Edit-button change (controller-isolated commit). Supplier reuses its create helpers; Project gets a new unit-tested `buildProjectUpdate`.

**Tech Stack:** React + TS, TanStack Query, shadcn/ui (Dialog/Input/Label/Select/Button), generated SDK, Playwright. Backend `update_supplier`/`update_project` (admin) already exist — no backend changes.

**Reference spec:** `docs/superpowers/specs/2026-06-19-supplier-project-edit-design.md`
**Reference pattern (committed):** `CustomerEditDialog` in `frontend/src/routes/_layout/customers.tsx`.

---

## File Structure

- `frontend/src/components/suppliers/SupplierEditDialog.tsx` — NEW (clean).
- `frontend/src/lib/project-edit.ts` — NEW (clean), pure helper.
- `frontend/tests/project-edit.spec.ts` — NEW (clean), unit tests.
- `frontend/src/components/projects/ProjectEditDialog.tsx` — NEW (clean).
- `frontend/src/routes/_layout/suppliers.tsx` — MODIFY (has WIP → controller-isolated).
- `frontend/src/routes/_layout/projects.tsx` — MODIFY (has WIP → controller-isolated).
- `frontend/tests/supplier-edit-flow.spec.ts`, `frontend/tests/project-edit-flow.spec.ts` — NEW E2E (clean). (Note: a product `product-edit-flow.spec.ts` already exists; these are distinct files.)

`customers.tsx` is NOT touched.

---

## Task 1: `SupplierEditDialog` component

**Files:**
- Create: `frontend/src/components/suppliers/SupplierEditDialog.tsx`

- [ ] **Step 1: Implement the component**

Create `frontend/src/components/suppliers/SupplierEditDialog.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useId, useState } from "react"

import { type SupplierPublic, SuppliersService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import useCustomToast from "@/hooks/useCustomToast"
import {
  buildSupplierPayload,
  canCreateSupplier,
  type SupplierDraft,
} from "@/lib/supplier-create"

export function SupplierEditDialog({
  supplier,
  onClose,
}: {
  supplier: SupplierPublic
  onClose: () => void
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const nameId = useId()
  const countryId = useId()
  const contactId = useId()
  const [draft, setDraft] = useState<SupplierDraft>({
    name: supplier.name,
    country: supplier.country ?? "",
    contact: supplier.contact ?? "",
  })

  const mutation = useMutation<SupplierPublic, Error, void>({
    mutationFn: () =>
      SuppliersService.updateSupplier({
        supplierId: supplier.id,
        requestBody: buildSupplierPayload(draft),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["suppliers"] })
      showSuccessToast("Supplier updated.")
      onClose()
    },
    onError: () =>
      showErrorToast("Could not update the supplier. Please try again."),
  })

  const canSave = canCreateSupplier(draft) && !mutation.isPending

  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit supplier</DialogTitle>
          <DialogDescription>Update this supplier's details.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor={nameId}>Name</Label>
            <Input
              id={nameId}
              value={draft.name}
              onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={countryId}>Country</Label>
            <Input
              id={countryId}
              value={draft.country}
              onChange={(e) =>
                setDraft((d) => ({ ...d, country: e.target.value }))
              }
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={contactId}>Contact</Label>
            <Input
              id={contactId}
              value={draft.contact}
              onChange={(e) =>
                setDraft((d) => ({ ...d, contact: e.target.value }))
              }
            />
          </div>
        </div>
        <DialogFooter>
          <Button type="button" disabled={!canSave} onClick={() => mutation.mutate()}>
            {mutation.isPending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 2: Typecheck + lint**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src/components/suppliers/SupplierEditDialog.tsx`
Expected: PASS / clean. (`buildSupplierPayload`/`canCreateSupplier`/`SupplierDraft` already exist in `lib/supplier-create.ts`.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/suppliers/SupplierEditDialog.tsx
git commit -m "feat(suppliers): add SupplierEditDialog"
```

---

## Task 2: `project-edit.ts` pure helper + unit tests

**Files:**
- Create: `frontend/src/lib/project-edit.ts`
- Test: `frontend/tests/project-edit.spec.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/tests/project-edit.spec.ts`:

```ts
import { expect, test } from "@playwright/test"
import type { ProjectPublic } from "../src/client/types.gen"
import {
  buildProjectUpdate,
  canSaveProject,
  type ProjectEditDraft,
  projectToEditDraft,
} from "../src/lib/project-edit"

const baseProject: ProjectPublic = {
  id: "pr1",
  code: "P-001",
  name: "Bakery fitout",
  customer_id: "c1",
  status: "ACTIVE",
  start_date: "2026-01-01",
  end_date: null,
  budget_thb: "5000.00",
}

const draft = (over: Partial<ProjectEditDraft> = {}): ProjectEditDraft => ({
  name: "Bakery fitout",
  customerId: "c1",
  status: "ACTIVE",
  startDate: "2026-01-01",
  endDate: "",
  budget: "5000",
  ...over,
})

test("projectToEditDraft maps a project to editable strings (no code)", () => {
  expect(projectToEditDraft(baseProject)).toEqual({
    name: "Bakery fitout",
    customerId: "c1",
    status: "ACTIVE",
    startDate: "2026-01-01",
    endDate: "",
    budget: "5000.00",
  })
})

test("canSaveProject requires name and customer", () => {
  expect(canSaveProject(draft())).toBe(true)
  expect(canSaveProject(draft({ name: "  " }))).toBe(false)
  expect(canSaveProject(draft({ customerId: "" }))).toBe(false)
})

test("canSaveProject rejects a negative/non-numeric budget but allows blank", () => {
  expect(canSaveProject(draft({ budget: "" }))).toBe(true)
  expect(canSaveProject(draft({ budget: "-1" }))).toBe(false)
  expect(canSaveProject(draft({ budget: "abc" }))).toBe(false)
})

test("buildProjectUpdate sends fields, never code, dates/budget as given", () => {
  expect(buildProjectUpdate(draft({ endDate: "2026-03-01" }))).toEqual({
    name: "Bakery fitout",
    customer_id: "c1",
    status: "ACTIVE",
    start_date: "2026-01-01",
    end_date: "2026-03-01",
    budget_thb: "5000",
  })
})

test("buildProjectUpdate sends null for blank dates and blank budget", () => {
  expect(
    buildProjectUpdate(draft({ startDate: "", endDate: "", budget: "  " })),
  ).toEqual({
    name: "Bakery fitout",
    customer_id: "c1",
    status: "ACTIVE",
    start_date: null,
    end_date: null,
    budget_thb: null,
  })
})

test("buildProjectUpdate never includes code", () => {
  expect("code" in buildProjectUpdate(draft())).toBe(false)
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && bun run test tests/project-edit.spec.ts`
Expected: FAIL — module `../src/lib/project-edit` does not exist.

- [ ] **Step 3: Implement the helper**

Create `frontend/src/lib/project-edit.ts`:

```ts
import type { ProjectPublic, ProjectStatus, ProjectUpdate } from "@/client/types.gen"

// Pure form logic for the admin project EDIT dialog. `code` is read-only (the
// project identity) and is never sent. name + customer are required; budget is
// an optional non-negative number; blank dates/budget are sent as null.

export interface ProjectEditDraft {
  name: string
  customerId: string
  status: ProjectStatus
  startDate: string
  endDate: string
  budget: string
}

function isValidBudget(value: string): boolean {
  const trimmed = value.trim()
  if (trimmed === "") return true // optional
  const n = Number(trimmed)
  return Number.isFinite(n) && n >= 0
}

export function projectToEditDraft(p: ProjectPublic): ProjectEditDraft {
  return {
    name: p.name,
    customerId: p.customer_id,
    status: p.status ?? "ACTIVE",
    startDate: p.start_date ?? "",
    endDate: p.end_date ?? "",
    budget: p.budget_thb != null ? String(p.budget_thb) : "",
  }
}

export function canSaveProject(d: ProjectEditDraft): boolean {
  return d.name.trim() !== "" && d.customerId !== "" && isValidBudget(d.budget)
}

export function buildProjectUpdate(d: ProjectEditDraft): ProjectUpdate {
  const start = d.startDate.trim()
  const end = d.endDate.trim()
  const budget = d.budget.trim()
  return {
    name: d.name.trim(),
    customer_id: d.customerId,
    status: d.status,
    start_date: start === "" ? null : start,
    end_date: end === "" ? null : end,
    budget_thb: budget === "" ? null : budget,
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && bun run test tests/project-edit.spec.ts`
Expected: PASS (6 tests).

- [ ] **Step 5: Typecheck + lint + commit**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src/lib/project-edit.ts tests/project-edit.spec.ts`
Expected: PASS / clean. If `ProjectUpdate` rejects `start_date: string` or `budget_thb: string`, STOP and report.

```bash
git add frontend/src/lib/project-edit.ts frontend/tests/project-edit.spec.ts
git commit -m "feat(projects): add pure project-edit helper + tests"
```

---

## Task 3: `ProjectEditDialog` component

**Files:**
- Create: `frontend/src/components/projects/ProjectEditDialog.tsx`

- [ ] **Step 1: Implement the component**

Create `frontend/src/components/projects/ProjectEditDialog.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useId, useState } from "react"

import {
  type CustomerPublic,
  type ProjectPublic,
  ProjectsService,
} from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import {
  buildProjectUpdate,
  canSaveProject,
  type ProjectEditDraft,
  projectToEditDraft,
} from "@/lib/project-edit"

export function ProjectEditDialog({
  project,
  customers,
  onClose,
}: {
  project: ProjectPublic
  customers: CustomerPublic[]
  onClose: () => void
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const codeId = useId()
  const nameId = useId()
  const customerId = useId()
  const statusId = useId()
  const startId = useId()
  const endId = useId()
  const budgetId = useId()
  const [draft, setDraft] = useState<ProjectEditDraft>(() =>
    projectToEditDraft(project),
  )

  function patch(p: Partial<ProjectEditDraft>) {
    setDraft((d) => ({ ...d, ...p }))
  }

  const mutation = useMutation<ProjectPublic, Error, void>({
    mutationFn: () =>
      ProjectsService.updateProject({
        projectId: project.id,
        requestBody: buildProjectUpdate(draft),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] })
      showSuccessToast("Project updated.")
      onClose()
    },
    onError: () =>
      showErrorToast("Could not update the project. Please try again."),
  })

  const isUnchanged =
    JSON.stringify(draft) === JSON.stringify(projectToEditDraft(project))
  const canSave = canSaveProject(draft) && !isUnchanged && !mutation.isPending

  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit project — {project.code}</DialogTitle>
          <DialogDescription>
            Update this project's details. Code can't be changed.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor={codeId}>Code</Label>
            <Input id={codeId} value={project.code} disabled readOnly />
          </div>
          <div className="space-y-2">
            <Label htmlFor={nameId}>Name</Label>
            <Input
              id={nameId}
              value={draft.name}
              onChange={(e) => patch({ name: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={customerId}>Customer</Label>
            <Select
              value={draft.customerId}
              onValueChange={(v) => patch({ customerId: v })}
            >
              <SelectTrigger id={customerId} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {customers.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor={statusId}>Status</Label>
            <Select
              value={draft.status}
              onValueChange={(v) => patch({ status: v as ProjectEditDraft["status"] })}
            >
              <SelectTrigger id={statusId} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ACTIVE">Active</SelectItem>
                <SelectItem value="CLOSED">Closed</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor={startId}>Start date</Label>
              <Input
                id={startId}
                type="date"
                value={draft.startDate}
                onChange={(e) => patch({ startDate: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor={endId}>End date</Label>
              <Input
                id={endId}
                type="date"
                value={draft.endDate}
                onChange={(e) => patch({ endDate: e.target.value })}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor={budgetId}>Budget (THB)</Label>
            <Input
              id={budgetId}
              type="number"
              min={0}
              inputMode="decimal"
              className="num"
              value={draft.budget}
              onChange={(e) => patch({ budget: e.target.value })}
            />
          </div>
        </div>
        <DialogFooter>
          <Button type="button" disabled={!canSave} onClick={() => mutation.mutate()}>
            {mutation.isPending ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 2: Typecheck + lint**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check src/components/projects/ProjectEditDialog.tsx`
Expected: PASS / clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/projects/ProjectEditDialog.tsx
git commit -m "feat(projects): add ProjectEditDialog"
```

---

## Task 4: Wire Edit into `suppliers.tsx` (CONTROLLER-ISOLATED)

> **CONTROLLER NOTE:** `suppliers.tsx` has uncommitted WIP. The controller performs this
> against the committed (HEAD) version: back up the working copy, `git checkout HEAD -- suppliers.tsx`,
> apply the edits below, commit ONLY this change, then restore the WIP copy and re-apply the
> edits so the WIP stays uncommitted. Verify with `git diff` that the uncommitted diff contains
> only the WIP, never the edit feature. Do NOT add the Edit button to the mobile card (WIP-owned).

**Files:**
- Modify: `frontend/src/routes/_layout/suppliers.tsx` (against HEAD)

- [ ] **Step 1: Imports** — add the dialog import, the `Pencil` icon, and `Dialog` is not needed (the dialog is self-contained). Add:

```ts
import { Pencil } from "lucide-react"
```
(after the existing first imports) and:
```ts
import { SupplierEditDialog } from "@/components/suppliers/SupplierEditDialog"
```
(with the other `@/components` imports). `SupplierPublic` is already imported.

- [ ] **Step 2: Editing state** — inside `function Suppliers()`, after the existing `useState` lines, add:

```ts
  const [editing, setEditing] = useState<SupplierPublic | null>(null)
```

- [ ] **Step 3: Actions column header** — in the desktop table header, after the `Contact` head, add an actions head:

```tsx
                <TableHead>Contact</TableHead>
                <TableHead className="text-right" />
```

- [ ] **Step 4: Edit button cell** — in the row, after the contact cell, add:

```tsx
                  <TableCell className="text-muted-foreground">
                    {s.contact ?? "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setEditing(s)}
                    >
                      <Pencil className="mr-1 size-4" />
                      Edit
                    </Button>
                  </TableCell>
```

- [ ] **Step 5: Render the dialog** — just before the final closing `</div>` of the component's return (after the table block), add:

```tsx
      {editing && (
        <SupplierEditDialog
          supplier={editing}
          onClose={() => setEditing(null)}
        />
      )}
```

- [ ] **Step 6: Controller verify + commit (clean HEAD base)**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check --write src/routes/_layout/suppliers.tsx`
Then stage + verify the staged diff is ONLY the edit wiring (no Alert/mobile WIP), and commit:

```bash
git add frontend/src/routes/_layout/suppliers.tsx
git diff --cached --stat -- frontend/src/routes/_layout/suppliers.tsx
git commit -m "feat(suppliers): add Edit button + dialog to the table"
```

- [ ] **Step 7: Restore WIP + re-apply** — `cp` the backed-up WIP version over the file, re-apply Steps 1–5 to it, run biome, then verify the uncommitted diff is WIP-only:

```bash
git diff -- frontend/src/routes/_layout/suppliers.tsx | grep -E "SupplierEditDialog|setEditing" || echo "edit feature fully committed; only WIP remains ✓"
```
Expected: the marker line prints "✓" (the edit wiring is committed and matches the working tree; only the Alert/mobile WIP is uncommitted).

---

## Task 5: Wire Edit into `projects.tsx` (CONTROLLER-ISOLATED)

> **CONTROLLER NOTE:** same isolation procedure as Task 4. `projects.tsx` already
> imports `Select`, has the `["customers"]` query as `customers`, and `ProjectPublic`/`CustomerPublic`
> types. Do NOT touch the mobile card (WIP).

**Files:**
- Modify: `frontend/src/routes/_layout/projects.tsx` (against HEAD)

- [ ] **Step 1: Imports** — add:

```ts
import { Pencil } from "lucide-react"
```
and
```ts
import { ProjectEditDialog } from "@/components/projects/ProjectEditDialog"
```
Ensure `CustomerPublic` is imported from `@/client` (add to the existing client import if missing — it's needed to type the dialog's `customers` prop; the page already fetches customers).

- [ ] **Step 2: Editing state** — after the existing `useState` lines in `function Projects()`:

```ts
  const [editing, setEditing] = useState<ProjectPublic | null>(null)
```

- [ ] **Step 3: Actions column header** — after the `Status` head:

```tsx
                <TableHead>Status</TableHead>
                <TableHead className="text-right" />
```

- [ ] **Step 4: Edit button cell** — after the status cell in the row (the cell that renders `<Badge variant="secondary">{p.status ?? "ACTIVE"}</Badge>`), add a new cell:

```tsx
                  <TableCell className="text-right">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setEditing(p)}
                    >
                      <Pencil className="mr-1 size-4" />
                      Edit
                    </Button>
                  </TableCell>
```

- [ ] **Step 5: Render the dialog** — before the component's final closing `</div>`:

```tsx
      {editing && (
        <ProjectEditDialog
          project={editing}
          customers={customers ?? []}
          onClose={() => setEditing(null)}
        />
      )}
```

- [ ] **Step 6: Controller verify + commit (clean HEAD base)**

Run: `cd frontend && bunx tsc --noEmit && bunx biome check --write src/routes/_layout/projects.tsx`

```bash
git add frontend/src/routes/_layout/projects.tsx
git diff --cached --stat -- frontend/src/routes/_layout/projects.tsx
git commit -m "feat(projects): add Edit button + dialog to the table"
```

- [ ] **Step 7: Restore WIP + re-apply** — `cp` the WIP backup over the file, re-apply Steps 1–5, biome, then verify uncommitted diff is WIP-only:

```bash
git diff -- frontend/src/routes/_layout/projects.tsx | grep -E "ProjectEditDialog|setEditing" || echo "edit feature fully committed; only WIP remains ✓"
```

---

## Task 6: E2E — edit a supplier and a project

**Files:**
- Create: `frontend/tests/supplier-edit-flow.spec.ts`
- Create: `frontend/tests/project-edit-flow.spec.ts`

- [ ] **Step 1: Discover the E2E auth pattern**

Run: `cd frontend && sed -n '1,30p' tests/product-edit-flow.spec.ts`
Expected: shows the global superuser `storageState` setup (tests just `page.goto`). Reuse it.

- [ ] **Step 2: Supplier E2E** — create `frontend/tests/supplier-edit-flow.spec.ts`:

```ts
import { expect, test } from "@playwright/test"

test("editing a supplier updates its row", async ({ page }) => {
  await page.goto("/suppliers")

  const name = `E2E-Sup-${Date.now()}`
  await page.getByLabel("Name").fill(name)
  await page.getByRole("button", { name: "Create supplier" }).click()

  const row = page.getByRole("row", { name: new RegExp(name) })
  await row.getByRole("button", { name: "Edit" }).click()

  const dialog = page.getByRole("dialog", { name: /Edit supplier/ })
  await dialog.getByLabel("Contact").fill("e2e@example.com")
  await dialog.getByRole("button", { name: "Save" }).click()

  await expect(page.getByText("Supplier updated.")).toBeVisible()
  await expect(
    page.getByRole("row", { name: new RegExp(name) }).getByText("e2e@example.com"),
  ).toBeVisible()
})
```

- [ ] **Step 3: Project E2E** — create `frontend/tests/project-edit-flow.spec.ts`. A project needs a customer; create one first via `/customers`, then a project via `/projects`, then edit its status. Adapt labels to the create forms (customers create has "Name"; projects create has "Code", "Name", and a customer select):

```ts
import { expect, test } from "@playwright/test"

test("editing a project's status updates its row", async ({ page }) => {
  // A customer is required to create a project.
  const customer = `E2E-Cust-${Date.now()}`
  await page.goto("/customers")
  await page.getByLabel("Name").first().fill(customer)
  await page.getByRole("button", { name: "Create customer" }).click()
  await expect(page.getByText(customer)).toBeVisible()

  // Create a project against that customer.
  const code = `E2E-${Date.now()}`
  await page.goto("/projects")
  await page.getByLabel("Code").fill(code)
  await page.getByLabel("Name").fill("E2E Project")
  await page.getByRole("combobox").click()
  await page.getByRole("option", { name: customer }).click()
  await page.getByRole("button", { name: "Create project" }).click()

  // Edit its status to Closed.
  const row = page.getByRole("row", { name: new RegExp(code) })
  await row.getByRole("button", { name: "Edit" }).click()
  const dialog = page.getByRole("dialog", { name: /Edit project/ })
  await dialog.getByLabel("Status").click()
  await page.getByRole("option", { name: "Closed" }).click()
  await dialog.getByRole("button", { name: "Save" }).click()

  await expect(page.getByText("Project updated.")).toBeVisible()
  await expect(
    page.getByRole("row", { name: new RegExp(code) }).getByText("CLOSED"),
  ).toBeVisible()
})
```

- [ ] **Step 3b: If a create-form label is ambiguous** (e.g. two "Name" fields on customers), scope with `.first()` or a more specific selector. The customers create form's first "Name" is the create card; use `.first()` as shown. Verify by reading the create form if a selector misses.

- [ ] **Step 4: Typecheck + run**

Run: `cd frontend && bunx tsc --noEmit && bun run test tests/supplier-edit-flow.spec.ts tests/project-edit-flow.spec.ts`
Expected: PASS against the running dev stack. If the stack/DB isn't up, that's an infra limit (DONE_WITH_CONCERNS); do not weaken assertions.

- [ ] **Step 5: Commit**

```bash
git add frontend/tests/supplier-edit-flow.spec.ts frontend/tests/project-edit-flow.spec.ts
git commit -m "test(suppliers,projects): E2E edit flows"
```

---

## Final verification

- [ ] **Step 1:** `cd frontend && bunx tsc --noEmit && bun run test tests/project-edit.spec.ts` → PASS.
- [ ] **Step 2:** Confirm `customers.tsx` was never touched: `git -C /Users/waiphyoaung/Desktop/CastraNova-POS/CastraNova-pos log --oneline -8 -- frontend/src/routes/_layout/customers.tsx` shows no new commits from this work, and `git status --short` shows `customers.tsx` unchanged from before (still whatever WIP it had).
- [ ] **Step 3:** Confirm `suppliers.tsx`/`projects.tsx` uncommitted diffs are WIP-only (no `*EditDialog`/`setEditing` in `git diff`).
- [ ] **Step 4:** Confirm no SDK regen needed: `grep -n "updateSupplier\|updateProject" frontend/src/client/sdk.gen.ts`.

---

## Notes / backlog

- Edit button inside the mobile card views (belongs with the WIP that adds those cards).
- A shared `LabeledInput` could DRY the supplier dialog's three inputs + the product dialog's `EditField`; defer until the create forms also adopt it.
