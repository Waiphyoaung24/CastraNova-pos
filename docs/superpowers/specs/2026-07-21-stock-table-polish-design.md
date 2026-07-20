# Stock Table Polish Design

## Goal

Make the Stock-on-Hand table easier to scan by removing the clipped overflow
mark beside the row expander, giving supplier-scoped quantities a clear
responsive context, and placing product identity columns in the requested
order.

## Desktop table

The column order is:

1. Expand
2. SKU
3. Brand
4. Model
5. Category
6. In stock
7. Labels

The expander cell uses narrower horizontal padding so its existing 32px button
fits within the existing expander column. The chevron, click target, keyboard
behaviour, and accessible label stay unchanged. Brand retains its current 15%
width and Model retains its current 23% width when their positions are swapped.

The quantity column header always reads `In stock`. It does not contain the
selected supplier name, because supplier names do not fit reliably in that
column.

## Supplier context

When an administrator selects a supplier, a visible context badge above the
table reads `Showing stock from: <supplier name>`. The badge is absent when no
supplier is selected. The selected supplier remains controlled by the existing
admin-only supplier filter, and quantities retain their existing
supplier-scoped backend semantics.

On mobile cards, the quantity caption continues to read
`from <supplier name>` when scoped and `in stock` when unscoped. The remainder
of the mobile card layout is unchanged.

## Scope and verification

This is a frontend-only presentation change. It does not alter API contracts,
filtering, authorization, pagination, or inventory calculations.

Verification covers the supplier-context rendering and desktop column order,
plus the production TypeScript/Vite build and Biome checks. Database-resetting
Playwright setup must not run against the shared development database for this
change.
