# CastraNova POS — UI/UX Redesign: "Obsidian & Gold"

**Date:** 2026-06-12
**Status:** Approved (brainstorming) — pending implementation plan
**Owner:** wai1998
**Brand asset:** `653699374_122123042949065484_354138185532947125_n.jpg` (CASTRA NOVA — gold wings + wordmark on black)

---

## 1. Goal

Re-skin CastraNova POS around the CASTRA NOVA brand mark (gold-on-black, aviation-wing
luxury) to deliver a cohesive, premium, more legible interface — **without** changing
application flows, features, data, or the backend.

"Better UI/UX performance" here = visual cohesion + interaction polish (focus/hover/
empty/loading states) + readable data density. It does **not** mean re-architecting
navigation or workflows in this pass.

## 2. Approved decisions

| Decision | Choice |
|---|---|
| Visual direction | **A · Obsidian & Gold** — dark luxury, gold as a disciplined accent |
| Color mode | **Dark-only** — remove light mode and the appearance toggle |
| Scope sequencing | **Foundation + key screens first**; remaining ~16 pages inherit via tokens, polished later on demand |
| Typography | **Space Grotesk** (display/headings/nav/large numbers) + **Inter** (body); **Fira Code** retained for `.num` tabular figures |
| Logo asset | **Use the provided JPG as-is** on dark surfaces (blended to drop the black), plus favicon + PWA icon |
| Wordmark text | **CASTRA NOVA** (uppercase) in tab title, PWA name, auth, footer |
| Accent strategy | **Gold is the single primary + CTA accent** — no separate orange |

## 3. Brand foundation — design tokens (`frontend/src/index.css`)

The token layer is the engine: re-skinning here propagates to every shadcn component and
therefore to most of the ~22 pages with no per-page edits.

**Palette (dark-only).** Make `:root` carry the Obsidian & Gold values and remove the
separate light-mode block; keep/force the dark theme so existing `.dark`-scoped rules
still apply (or collapse `.dark` and `:root` to the same values).

- Surfaces: background `#0B0B0D`, card/popover `#16161A`, raised/secondary/muted `#1C1C20`
- Borders: hairline `white / 8%`; gold-tinted `rgba(212,175,55,.16)` on brand edges (sidebar, key panels)
- Foreground `#ECECEC`, muted `#9A9A9A`, faint `#6C6C70`
- **Gold ramp:** base `#D4AF37`, bright `#F5D76E`, deep `#AA771C` (gradients = bright→base→deep)

**Token remaps (values change; token names stay, so usages auto-update):**
- `--primary` → gold; `--primary-foreground` → near-black `#0B0B0D` (AA on gold)
- `--cta` / `--cta-foreground` → gold / near-black (checkout becomes gold; no orange)
- `--ring` → gold (focus rings)
- `--sidebar-primary` / active accents → gold
- `--success`, `--warn`, `--destructive` → retuned green/amber/red for the dark backdrop
- Charts (`--chart-1..5`) → a gold-led palette with supporting tints

**Typography tokens:**
- `--font-sans: "Inter", …` (body)
- add `--font-display: "Space Grotesk", …` (headings, nav, KPI numbers, buttons)
- `--font-mono: "Fira Code", …` (unchanged; powers `.num` tabular)
- Headings (`h1–h3`, KPI numbers, sidebar nav, buttons) use `--font-display`.

**Fonts loaded** via the project's existing mechanism (Google Fonts link in `index.html`
or bundled), matching how Fira Sans/Code are loaded today.

## 4. Logo & app identity

- Copy the JPG into `frontend/public/assets/images/` (e.g. `castranova-logo.jpg`).
- Rewrite `components/Common/Logo.tsx` to use it (drop the FastAPI SVG imports). On dark
  surfaces apply `mix-blend-mode: lighten` (or `screen`) so the pure-black background
  disappears and only the gold mark shows — crisp on `#0B0B0D` with no fringe.
- Collapsed sidebar / very small contexts: show the gold **CASTRA NOVA** wordmark as live
  Space Grotesk text (gold gradient) where the raster wordmark would be illegible.
- Favicon (`public/assets/images/favicon.png` ref in `index.html`) and PWA manifest icon →
  the square logo. Tab `<title>`, PWA `name`/`short_name`, auth heading, footer → **CASTRA NOVA**.

## 5. Key screens (the "foundation" PR)

1. **Sidebar / nav** (`components/Sidebar/AppSidebar.tsx`, `components/ui/sidebar.tsx`):
   gold active state with a left gold bar, uppercase section labels, gold avatar, brand
   header using the logo.
2. **Login / auth** (`routes/login.tsx`, `components/Common/AuthLayout.tsx`): centered logo
   on the luxury dark backdrop, gold primary button, refined inputs.
3. **Dashboard** (`routes/_layout/index.tsx`): gold KPI numbers, recent-sales table,
   low-stock panel — per the approved mockup.
4. **POS Sale screen + cart** (`routes/_layout/sale.tsx`, `components/pos/ScanCart.tsx` and
   siblings): gold checkout CTA, refined cart line/total styling.
5. **Shared shadcn primitives** (`components/ui/`: button, card, table, badge, input, tabs):
   gold focus rings, table-header treatment, gold price emphasis. These propagate to all
   remaining pages.

## 6. Scope discipline (CLAUDE.md §2–§3)

**In scope:** token re-skin; logo/identity; visual + interaction polish on the 5 screen
groups above; the dark-only conversion (removing the light palette + appearance toggle).

**Out of scope (this pass):**
- No navigation/IA or workflow changes; no new features.
- No backend, model, migration, or SDK changes; **no `generate-client`** (purely frontend).
- No edits to auto-generated files (`client/`, `routeTree.gen.ts`).
- Deep per-page polish for the other ~16 pages → later on-demand phase (they inherit the
  token re-skin meanwhile).

## 7. Verification

- `tsc` typecheck clean; `biome` lint/format clean.
- Existing Playwright E2E suite stays green — the re-skin must not break test selectors
  (watch for any tests asserting on the removed appearance toggle or light-mode classes).
- Manual visual pass on: login, dashboard, sale, sidebar, and 2–3 inherited pages
  (products, stock) to confirm the token re-skin reads correctly.
- Contrast spot-check: gold-on-dark text/icons and black-on-gold buttons meet WCAG AA.

## 8. Risks & notes

- **Appearance toggle removal** may touch `components/Common/Appearance.tsx`,
  `components/theme-provider.tsx`, and `routes/_layout/settings.tsx`; confirm no E2E test
  depends on toggling theme.
- **JPG blend approach** is dark-only by design — if a light surface ever reappears, the
  logo needs a transparent/vector version. Acceptable given the dark-only decision.
- Raster logo won't scale crisply at large sizes; fine for sidebar/login/favicon scale.
- Charts currently use a generic multi-hue palette; a gold-led recolor is included but
  must preserve series distinguishability.

## 9. Out-of-band follow-ups (not this pass)

- Optional future: commission/recreate a true vector (SVG) logo for crisp scaling and a
  proper maskable PWA icon.
- Per-page polish backlog for the remaining ~16 routes.
