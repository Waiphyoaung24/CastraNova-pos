# Shared `<PageHeader>` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-rolled page-header block in all 24 `_layout` routes with one shared `<PageHeader>` component.

**Architecture:** A slot-based presentational component in `frontend/src/components/Common/PageHeader.tsx` renders the header block only (title + optional description/actions/badge/backLink/footer). Each page keeps its own outer `flex flex-col gap-6` wrapper and swaps its inner header `<div>` for `<PageHeader …>`. No behavior change.

**Tech Stack:** React + TypeScript, Tailwind v4, `cn` (clsx + tailwind-merge) from `@/lib/utils`. No unit-test framework in frontend — verification is `bun run build` (tsc) + `bun run lint` (biome).

**Spec:** `docs/superpowers/specs/2026-06-18-shared-page-header-design.md`

---

## File Structure

- **Create:** `frontend/src/components/Common/PageHeader.tsx` — the shared header component (single responsibility: render a page header).
- **Modify:** all 24 route files under `frontend/src/routes/_layout/` — swap inner header `<div>` for `<PageHeader>` and add the import.

Page classification:
- **Standard (20):** `audit`, `channel-margin`, `customers`, `holding-period`, `low-stock`, `notifications`, `override-exceptions`, `pricing-overrides`, `products`, `projects`, `pulls`, `receive`, `sale`, `search`, `settings`, `stock`, `stock-adjustment`, `suppliers`, `sync-review`, `tickets`.
- **Action (1):** `admin`.
- **Dashboard (1):** `index`.
- **Detail (2):** `customer.$customerId`, `project.$projectId`.

All commands run from `frontend/`.

---

### Task 1: Create the `PageHeader` component

**Files:**
- Create: `frontend/src/components/Common/PageHeader.tsx`

- [ ] **Step 1: Write the component**

```tsx
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

interface PageHeaderProps {
  title: ReactNode
  description?: ReactNode
  /** Right-aligned slot: action buttons or a status pill. */
  actions?: ReactNode
  /** Inline element rendered beside the title (e.g. a status Badge). */
  badge?: ReactNode
  /** Eyebrow link rendered above the title (e.g. a back-link). */
  backLink?: ReactNode
  /** Extra content below the description (e.g. a sub-link). */
  footer?: ReactNode
  /** Merged into the h1 class — for `num` or responsive size overrides. */
  titleClassName?: string
}

export function PageHeader({
  title,
  description,
  actions,
  badge,
  backLink,
  footer,
  titleClassName,
}: PageHeaderProps) {
  return (
    <div>
      {backLink}
      <div
        className={cn(
          "flex items-start justify-between gap-3",
          backLink && "mt-2",
        )}
      >
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h1
              className={cn(
                "text-2xl font-bold tracking-tight",
                titleClassName,
              )}
            >
              {title}
            </h1>
            {badge}
          </div>
          {description && (
            <p className="text-muted-foreground">{description}</p>
          )}
          {footer}
        </div>
        {actions}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Typecheck the component compiles**

Run: `bun run build`
Expected: build succeeds (no TS errors). The component is not yet imported anywhere, so this only confirms it type-checks.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Common/PageHeader.tsx
git commit -m "feat(page-header): add shared PageHeader component"
```

---

### Task 2: Migrate the 20 standard pages

**Files (Modify):** each of the 20 standard route files under `frontend/src/routes/_layout/`:
`audit.tsx`, `channel-margin.tsx`, `customers.tsx`, `holding-period.tsx`, `low-stock.tsx`, `notifications.tsx`, `override-exceptions.tsx`, `pricing-overrides.tsx`, `products.tsx`, `projects.tsx`, `pulls.tsx`, `receive.tsx`, `sale.tsx`, `search.tsx`, `settings.tsx`, `stock.tsx`, `stock-adjustment.tsx`, `suppliers.tsx`, `sync-review.tsx`, `tickets.tsx`.

Each of these has a header block of this exact shape near the top of its returned JSX (title/description text differs per file):

```tsx
<div className="flex flex-col gap-6">
  <div>
    <h1 className="text-2xl font-bold tracking-tight">TITLE</h1>
    <p className="text-muted-foreground">
      DESCRIPTION
    </p>
  </div>
  {/* …rest of page… */}
</div>
```

- [ ] **Step 1: For each of the 20 files, replace the inner header `<div>` with `<PageHeader>`**

Transform the inner block (keep the outer `<div className="flex flex-col gap-6">` wrapper and everything after the header untouched):

```tsx
// BEFORE
<div>
  <h1 className="text-2xl font-bold tracking-tight">TITLE</h1>
  <p className="text-muted-foreground">
    DESCRIPTION
  </p>
</div>

// AFTER
<PageHeader title="TITLE" description="DESCRIPTION" />
```

Rules:
- Preserve the existing `TITLE` and `DESCRIPTION` text **verbatim** from each file — do not reword.
- If `DESCRIPTION` is a plain text string (it is, for all 20), pass it as the `description` string prop. Keep the exact wording (a wrapped multi-line string becomes one string literal; collapse the surrounding whitespace only).
- A few titles wrap across lines in source (e.g. `override-exceptions` "Override exceptions"); the title text itself is unchanged.

- [ ] **Step 2: Add the import to each of the 20 files**

Add alongside the other `@/components/...` imports (biome will sort on lint):

```tsx
import { PageHeader } from "@/components/Common/PageHeader"
```

- [ ] **Step 3: Build to verify all 20 type-check**

Run: `bun run build`
Expected: build succeeds.

- [ ] **Step 4: Lint/format**

Run: `bun run lint`
Expected: biome reports no errors (it auto-sorts imports and formats).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/_layout
git commit -m "refactor(page-header): adopt PageHeader in 20 standard pages"
```

---

### Task 3: Migrate `admin` (action slot)

**Files (Modify):** `frontend/src/routes/_layout/admin.tsx`

Current header (around line 54-64):

```tsx
<div className="flex flex-col gap-6">
  <div className="flex items-center justify-between">
    <div>
      <h1 className="text-2xl font-bold tracking-tight">Users</h1>
      <p className="text-muted-foreground">
        Manage user accounts and permissions
      </p>
    </div>
    <AddUser />
  </div>
  <UsersTable />
</div>
```

- [ ] **Step 1: Replace the header block (keep the `flex flex-col gap-6` wrapper and `<UsersTable />`)**

```tsx
<div className="flex flex-col gap-6">
  <PageHeader
    title="Users"
    description="Manage user accounts and permissions"
    actions={<AddUser />}
  />
  <UsersTable />
</div>
```

- [ ] **Step 2: Add the import**

```tsx
import { PageHeader } from "@/components/Common/PageHeader"
```

(`AddUser` is already imported — keep it.)

- [ ] **Step 3: Build + lint**

Run: `bun run build && bun run lint`
Expected: both succeed.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/_layout/admin.tsx
git commit -m "refactor(page-header): adopt PageHeader in admin"
```

---

### Task 4: Migrate `index` (dashboard — responsive title + status pill)

**Files (Modify):** `frontend/src/routes/_layout/index.tsx`

Current header (around line 150-163):

```tsx
<div className="flex flex-col gap-6 sm:gap-8">
  <div className="flex items-start justify-between gap-3">
    <div className="min-w-0">
      <h1 className="text-xl font-bold tracking-tight break-words sm:text-2xl">
        Welcome back, {name}
      </h1>
      <p className="text-muted-foreground text-sm sm:text-base">
        Jump straight into a task.
      </p>
    </div>
    <span className="inline-flex shrink-0 items-center rounded-full border border-primary/30 bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
      {isAdmin ? "Admin" : "Staff"}
    </span>
  </div>

  {/* Featured: New Sale … (rest of dashboard) */}
```

- [ ] **Step 1: Replace the header block (keep the `flex flex-col gap-6 sm:gap-8` wrapper and everything after)**

The status pill moves into `actions`; the responsive title size is passed via `titleClassName` (tailwind-merge lets `text-xl sm:text-2xl` override the base `text-2xl`). Per the approved spec, the description drops its `text-sm sm:text-base` sizing and uses the component default muted size.

```tsx
<div className="flex flex-col gap-6 sm:gap-8">
  <PageHeader
    title={`Welcome back, ${name}`}
    titleClassName="text-xl break-words sm:text-2xl"
    description="Jump straight into a task."
    actions={
      <span className="inline-flex shrink-0 items-center rounded-full border border-primary/30 bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
        {isAdmin ? "Admin" : "Staff"}
      </span>
    }
  />

  {/* Featured: New Sale … (rest of dashboard, unchanged) */}
```

- [ ] **Step 2: Add the import**

```tsx
import { PageHeader } from "@/components/Common/PageHeader"
```

- [ ] **Step 3: Build + lint**

Run: `bun run build && bun run lint`
Expected: both succeed.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/_layout/index.tsx
git commit -m "refactor(page-header): adopt PageHeader in dashboard"
```

---

### Task 5: Migrate `customer.$customerId` (back-link + inline badge)

**Files (Modify):** `frontend/src/routes/_layout/customer.$customerId.tsx`

Current header (around line 61-78):

```tsx
<div className="flex flex-col gap-6">
  <div>
    {isAdmin && (
      <Link
        to="/projects"
        className="text-muted-foreground text-sm hover:underline"
      >
        ← Projects
      </Link>
    )}
    <div className="mt-2 flex items-center gap-3">
      <h1 className="text-2xl font-bold tracking-tight">{customer.name}</h1>
      <Badge variant="secondary">{customer.type ?? "END_CUSTOMER"}</Badge>
    </div>
    {(customer.contact || customer.country) && (
      <p className="text-muted-foreground">
        {[customer.contact, customer.country].filter(Boolean).join(" · ")}
      </p>
    )}
  </div>

  {/* …rest of page… */}
```

- [ ] **Step 1: Replace the header block (keep the `flex flex-col gap-6` wrapper and everything after)**

The `mt-2` spacing is now handled inside `PageHeader` (applied when `backLink` is present), so it is dropped from the call site. The conditional description is passed via a ternary expression (`PageHeader` renders nothing when `description` is falsy).

```tsx
<div className="flex flex-col gap-6">
  <PageHeader
    backLink={
      isAdmin && (
        <Link
          to="/projects"
          className="text-muted-foreground text-sm hover:underline"
        >
          ← Projects
        </Link>
      )
    }
    title={customer.name}
    badge={<Badge variant="secondary">{customer.type ?? "END_CUSTOMER"}</Badge>}
    description={
      customer.contact || customer.country
        ? [customer.contact, customer.country].filter(Boolean).join(" · ")
        : undefined
    }
  />

  {/* …rest of page… */}
```

- [ ] **Step 2: Add the import**

```tsx
import { PageHeader } from "@/components/Common/PageHeader"
```

(`Link` and `Badge` are already imported — keep them.)

- [ ] **Step 3: Build + lint**

Run: `bun run build && bun run lint`
Expected: both succeed.

- [ ] **Step 4: Commit**

```bash
git add "frontend/src/routes/_layout/customer.\$customerId.tsx"
git commit -m "refactor(page-header): adopt PageHeader in customer detail"
```

---

### Task 6: Migrate `project.$projectId` (back-link + inline badge + footer sub-link + num title)

**Files (Modify):** `frontend/src/routes/_layout/project.$projectId.tsx`

Current header (around line 61-83):

```tsx
<div className="flex flex-col gap-6">
  <div>
    {isAdmin && (
      <Link
        to="/projects"
        className="text-muted-foreground text-sm hover:underline"
      >
        ← Projects
      </Link>
    )}
    <div className="mt-2 flex items-center gap-3">
      <h1 className="num text-2xl font-bold tracking-tight">
        {project.code}
      </h1>
      <Badge variant="secondary">{project.status ?? "ACTIVE"}</Badge>
    </div>
    <p className="text-muted-foreground">{project.name}</p>
    <Link
      to="/customer/$customerId"
      params={{ customerId: project.customer_id }}
      className="text-sm hover:underline"
    >
      View customer
    </Link>
  </div>

  {/* …rest of page… */}
```

- [ ] **Step 1: Replace the header block (keep the `flex flex-col gap-6` wrapper and everything after)**

`num` moves to `titleClassName`; the "View customer" link becomes `footer`.

```tsx
<div className="flex flex-col gap-6">
  <PageHeader
    backLink={
      isAdmin && (
        <Link
          to="/projects"
          className="text-muted-foreground text-sm hover:underline"
        >
          ← Projects
        </Link>
      )
    }
    title={project.code}
    titleClassName="num"
    badge={<Badge variant="secondary">{project.status ?? "ACTIVE"}</Badge>}
    description={project.name}
    footer={
      <Link
        to="/customer/$customerId"
        params={{ customerId: project.customer_id }}
        className="text-sm hover:underline"
      >
        View customer
      </Link>
    }
  />

  {/* …rest of page… */}
```

- [ ] **Step 2: Add the import**

```tsx
import { PageHeader } from "@/components/Common/PageHeader"
```

(`Link` and `Badge` are already imported — keep them.)

- [ ] **Step 3: Build + lint**

Run: `bun run build && bun run lint`
Expected: both succeed.

- [ ] **Step 4: Commit**

```bash
git add "frontend/src/routes/_layout/project.\$projectId.tsx"
git commit -m "refactor(page-header): adopt PageHeader in project detail"
```

---

### Task 7: Final verification

**Files:** none (verification only).

- [ ] **Step 1: Confirm no hand-rolled headers remain**

Run: `grep -rln 'text-2xl font-bold tracking-tight' frontend/src/routes/_layout`
Expected: no output. (All `<h1>` styling now lives in `PageHeader`. Note: `index` and `project` overrides live in `titleClassName`, not the routes.) If any file is listed, it was missed — migrate it.

- [ ] **Step 2: Full build**

Run: `bun run build`
Expected: succeeds.

- [ ] **Step 3: Lint**

Run: `bun run lint`
Expected: no errors.

- [ ] **Step 4: Visual / E2E spot-check**

Start the app (`docker compose watch` or the project's dev command) and confirm the headers render unchanged on:
- `products` (standard),
- `admin` (action button, right-aligned),
- a customer detail page (back-link + badge),
- a project detail page (back-link + badge + `num` code + "View customer" link).

Run existing E2E smoke: `bun run test`
Expected: passes (no behavior changed).

- [ ] **Step 5: Commit (if any fixups were needed in Step 1)**

```bash
git add -A
git commit -m "refactor(page-header): final fixups"
```

---

## Self-Review Notes

- **Spec coverage:** Component (Task 1); all 24 pages — 20 standard (Task 2), admin (Task 3), index (Task 4), customer (Task 5), project (Task 6); verification path tsc+biome+E2E+visual (Task 7). Dashboard description tweak captured in Task 4. ✓
- **No placeholders:** every code step shows full before/after. ✓
- **Type consistency:** `PageHeaderProps` slot names (`title`, `description`, `actions`, `badge`, `backLink`, `footer`, `titleClassName`) used identically across Tasks 3-6. ✓
