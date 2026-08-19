# Shared `<PageHeader>` Across All Tab Pages — Design

**Date:** 2026-06-18
**Status:** Approved (design)
**Scope:** Frontend only. Pure presentational refactor — no behavior change.

## Problem

All 24 routes under `frontend/src/routes/_layout/` hand-roll the same page-header
block at the top of each page:

```tsx
<div className="flex flex-col gap-6">
  <div>
    <h1 className="text-2xl font-bold tracking-tight">{Title}</h1>
    <p className="text-muted-foreground">{Description}</p>
  </div>
  {/* ...page content... */}
</div>
```

The duplication has drifted: `receive.tsx` carries an extra `py-4` variant,
descriptions wrap inconsistently, and the special pages each diverge further.
There is no single source of truth for "what a page header looks like."

## Goal

Extract one shared `<PageHeader>` component that **every** tab page uses, so the
header renders identically and future changes happen in one place. Cover all 24
pages, including the special cases (dashboard, detail pages with back-links and
inline badges).

## Header shapes observed

| Shape | Pages | Extra elements |
|---|---|---|
| Standard | ~20 pages | title + description only |
| With action | `admin` | right-side button (`<AddUser />`), `flex items-center justify-between` |
| Dashboard | `index` | responsive title `text-xl sm:text-2xl break-words`, right-side status pill, `items-start` truncation |
| Detail | `customer.$customerId`, `project.$projectId` | eyebrow back-link above title; inline `<Badge>` beside title; (project) sub-link below description; (project) `num` title class |

## Component

**File:** `frontend/src/components/Common/PageHeader.tsx` (matches existing
`Common/` convention: `Footer`, `Logo`).

**Renders only the header block** — the inner `<div>`, *not* the page's outer
`flex flex-col gap-6` wrapper. Each page keeps its own outer wrapper, because the
wrapper legitimately varies (`gap-6` vs `gap-6 sm:gap-8`). This keeps the change
surgical.

### Props (slot-based — composition over config)

```tsx
interface PageHeaderProps {
  title: React.ReactNode          // required
  description?: React.ReactNode   // muted subtitle
  actions?: React.ReactNode       // right-aligned: buttons (admin), status pill (dashboard)
  badge?: React.ReactNode         // inline beside the title (detail pages)
  backLink?: React.ReactNode      // eyebrow link above the title (detail pages)
  footer?: React.ReactNode        // sub-link below description (project "View customer")
  titleClassName?: string         // num, responsive overrides — merged via cn
}
```

Every slot maps to a real, in-use need today — no speculative flexibility.

### Skeleton (fixed; slots render only when provided — no layout branching)

```tsx
<div>
  {backLink}
  <div className="flex items-start justify-between gap-3">
    <div className="min-w-0">
      <div className="flex items-center gap-3">
        <h1 className={cn("text-2xl font-bold tracking-tight", titleClassName)}>
          {title}
        </h1>
        {badge}
      </div>
      {description && <p className="text-muted-foreground">{description}</p>}
      {footer}
    </div>
    {actions}
  </div>
</div>
```

- `h1` base class merges with `titleClassName` via `cn` (tailwind-merge resolves
  conflicts, so `text-xl sm:text-2xl` overrides `text-2xl`, and `num` composes).
- The fixed skeleton renders correctly for the standard case too: a single
  left-aligned title block (no `actions`), title in a single-item flex row
  (no `badge`) — visually identical to today's markup.
- When `backLink` is present, the title row gets `mt-2` to preserve the existing
  spacing on detail pages.

## Per-page mapping (all 24)

- **~20 standard pages** → `title` + `description`.
- **`admin`** → + `actions={<AddUser />}`.
- **`index`** (dashboard) → `title="Welcome back, {name}"`, `actions={statusPill}`,
  `titleClassName` for the responsive size. **Intentional tweak:** its description
  drops the `text-sm sm:text-base` sizing and uses the default muted size. (Approved.)
- **`customer.$customerId`** → `backLink`, `badge`, `description`.
- **`project.$projectId`** → `backLink`, `badge`, `description`,
  `footer` (View customer link), `titleClassName="num"`.

## Behavior change

None. Pure presentational extraction — same DOM and styles, centralized.

## Verification

No component-unit harness exists in this repo (frontend testing is Playwright E2E
only per CLAUDE.md), and TDD does not cleanly apply to a no-behavior-change
extraction. Verification is therefore:

1. `tsc` / build green.
2. biome clean.
3. Existing E2E smoke passes.
4. Visual spot-check of: a standard page (`products`), the action page (`admin`),
   and the two detail pages (`customer`, `project`).

## Out of scope

- No visual redesign (no new card shell / border treatment).
- No change to the outer page wrappers or page content.
- No new tests harness; rely on existing E2E + typecheck.
