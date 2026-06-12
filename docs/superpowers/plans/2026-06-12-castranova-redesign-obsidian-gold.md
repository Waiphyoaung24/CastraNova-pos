# CastraNova POS — "Obsidian & Gold" Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-skin the CastraNova POS frontend around the CASTRA NOVA brand (gold-on-black luxury), dark-only, with the brand mark wired into the app — without changing flows, features, or the backend.

**Architecture:** The redesign is **token-driven**. The bulk of the work is one CSS file (`index.css`): remap the shadcn design tokens to an Obsidian & Gold dark palette + new fonts, and most of the ~22 pages and every shadcn primitive inherit the new look automatically (e.g. the Sale screen's checkout button already uses the `cta` token, page `<h1>`s pick up the display font from a base rule). On top of that: convert the app to dark-only (remove the theme toggle), swap the FastAPI placeholder logo for the CASTRA NOVA JPG, and apply focused polish to the sidebar, auth, and dashboard screens.

**Tech Stack:** React + TypeScript, TanStack Router/Query, Tailwind v4 (`@theme` CSS tokens), shadcn/ui, Vite + vite-plugin-pwa, Playwright (E2E). Package manager: **bun**.

**Spec:** `docs/superpowers/specs/2026-06-12-castranova-redesign-obsidian-gold-design.md`

---

## Prerequisites

- Work happens on branch **`feat/redesign-obsidian-gold`** (already created off `dev`, spec already committed there). Confirm with `git branch --show-current` before starting.
- This is a **frontend-only** change set: do **not** run `generate-client`, touch `backend/`, edit `frontend/src/client/`, or edit `routeTree.gen.ts`.
- No component unit-test harness exists (tests are Playwright E2E). Per-task verification is therefore: **typecheck + biome + run the dev server and look**. The existing E2E suite is the integration gate in the final task.

**Verify commands (run from `frontend/`):**
- Typecheck: `bunx tsc -p tsconfig.build.json --noEmit`
- Lint/format (auto-fixes): `bun run lint`
- Dev server (visual check): `bun run dev` → open the printed URL
- Full E2E (final task; needs the dev stack up): `bun run test`

## File map

| File | Change | Task |
|---|---|---|
| `frontend/src/index.css` | Obsidian & Gold tokens, fonts, base heading rule, sidebar active-bar | 1, 4 |
| `frontend/index.html` | font links (Inter/Space Grotesk), tab title, favicon | 1, 3 |
| `frontend/src/components/theme-provider.tsx` | rewrite → dark-only provider, stable `useTheme` API | 2 |
| `frontend/src/components/Common/Appearance.tsx` | **delete** | 2 |
| `frontend/src/components/Common/AuthLayout.tsx` | drop `Appearance`; luxury backdrop | 2, 5 |
| `frontend/src/components/Sidebar/AppSidebar.tsx` | drop `SidebarAppearance`; sectioned groups | 2, 4 |
| `frontend/tests/user-settings.spec.ts` | replace 3 theme-toggle tests with 1 dark-only test | 2 |
| `frontend/src/components/Common/Logo.tsx` | rewrite → CASTRA NOVA JPG | 3 |
| `frontend/public/assets/images/castranova-logo.jpg` | **add** (brand asset) | 3 |
| `frontend/vite.config.ts` | PWA manifest name/theme_color/icon | 3 |
| `frontend/src/components/Common/Footer.tsx` | rebrand text, drop FastAPI socials | 3 |
| `frontend/src/components/Sidebar/Main.tsx` | optional group label | 4 |
| `frontend/src/routes/login.tsx` | title + heading polish | 5 |
| `frontend/src/routes/_layout/index.tsx` | dashboard → branded quick-action cards | 6 |

> **Covered automatically by Task 1 (no dedicated task):** `routes/_layout/sale.tsx` checkout button (`bg-cta` → gold), all page `<h1>` headings (display font via base rule), every shadcn primitive's primary/focus colors. These are checked in Task 7's visual pass.

---

### Task 1: Brand foundation — Obsidian & Gold tokens + fonts

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/index.html:11-14` (font link)

- [ ] **Step 1: Swap the web-font link**

In `frontend/index.html`, replace the Fira link (lines 11-14) with Inter + Space Grotesk + Fira Code (Fira Code stays for tabular `.num`):

```html
    <link
      href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap"
      rel="stylesheet"
    />
```

- [ ] **Step 2: Add the display font token**

In `frontend/src/index.css`, inside the `@theme inline { ... }` block, replace the two `--font-*` lines (currently lines 8-9) with three:

```css
  /* Fonts */
  --font-sans: "Inter", ui-sans-serif, system-ui, sans-serif;
  --font-display: "Space Grotesk", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "Fira Code", ui-monospace, "SFMono-Regular", monospace;
```

- [ ] **Step 3: Replace the light `:root` palette with the Obsidian & Gold dark palette**

Replace the entire `:root { ... }` block (currently lines 56/57–116, the "Light mode" block) with this dark-only token set:

```css
/* ── Obsidian & Gold (dark-only) ──────────────────────────────────────────── */
:root {
  --radius: 0.625rem;

  /* Surfaces */
  --background: #0B0B0D;
  --foreground: #ECECEC;
  --card: #16161A;
  --card-foreground: #ECECEC;
  --popover: #16161A;
  --popover-foreground: #ECECEC;

  /* Gold is the single primary accent (black text for AA on gold) */
  --primary: #D4AF37;
  --primary-foreground: #0B0B0D;

  --secondary: #1C1C20;
  --secondary-foreground: #ECECEC;
  --muted: #1C1C20;
  --muted-foreground: #9A9A9A;

  /* shadcn accent: subtle raised bg */
  --accent: #1C1C20;
  --accent-foreground: #ECECEC;

  --destructive: #E5484D;

  --border: oklch(1 0 0 / 8%);
  --input: oklch(1 0 0 / 14%);
  --ring: #D4AF37;                 /* gold focus ring */

  /* Charts — gold-led, distinguishable */
  --chart-1: #D4AF37;
  --chart-2: #46C46E;
  --chart-3: #E0A82E;
  --chart-4: #7BA7D9;
  --chart-5: #C77DFF;

  /* Sidebar */
  --sidebar: #0E0E11;
  --sidebar-foreground: #ECECEC;
  --sidebar-primary: #D4AF37;
  --sidebar-primary-foreground: #0B0B0D;
  --sidebar-accent: rgba(212, 175, 55, 0.12);   /* gold-tinted active bg */
  --sidebar-accent-foreground: #F5D76E;          /* gold active text */
  --sidebar-border: rgba(212, 175, 55, 0.14);
  --sidebar-ring: #D4AF37;

  /* CTA (checkout) — gold, matching primary */
  --cta: #D4AF37;
  --cta-foreground: #0B0B0D;

  /* Semantic status (tuned for dark) */
  --success: #46C46E;
  --success-foreground: #0B0B0D;
  --warn: #E0A82E;
  --warn-foreground: #0B0B0D;
}
```

- [ ] **Step 4: Delete the now-redundant `.dark` override block**

The app is dark-only and `:root` now carries the dark values, so the separate `.dark { ... }` block (currently the "Dark mode (data-dense, industrial)" block, ~lines 118-176) is redundant. **Delete the entire `.dark { ... }` block.** (Components still use `dark:`-prefixed Tailwind utilities like `dark:bg-input/30`; those keep working because Task 2 forces the `.dark` class onto `<html>` — they reference Tailwind's own colors, not this block.)

- [ ] **Step 5: Add a base heading rule so every page `<h1>`–`<h4>` uses the display font**

In `index.css`, extend the existing `@layer base { ... }` block by adding a heading rule after the `body` rule:

```css
  h1, h2, h3, h4 {
    font-family: var(--font-display);
    letter-spacing: -0.01em;
  }
```

- [ ] **Step 6: Typecheck + lint**

Run: `bunx tsc -p tsconfig.build.json --noEmit`
Expected: no errors.
Run: `bun run lint`
Expected: clean (no diagnostics).

- [ ] **Step 7: Visual check**

Run: `bun run dev`, open the app, log in. Expected: dark background everywhere, gold primary buttons, gold focus rings on inputs, headings in Space Grotesk, body in Inter. (Some `dark:` utilities only fully resolve after Task 2 forces `.dark`; that's fine.)

- [ ] **Step 8: Commit**

```bash
git add frontend/src/index.css frontend/index.html
git commit -m "feat(ui): Obsidian & Gold design tokens + Space Grotesk/Inter fonts

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Convert to dark-only (remove theme toggle)

**Files:**
- Modify: `frontend/src/components/theme-provider.tsx` (rewrite)
- Delete: `frontend/src/components/Common/Appearance.tsx`
- Modify: `frontend/src/components/Sidebar/AppSidebar.tsx:24,97`
- Modify: `frontend/src/components/Common/AuthLayout.tsx`
- Modify: `frontend/tests/user-settings.spec.ts:205-256`

- [ ] **Step 1: Rewrite the theme provider as dark-only**

Replace the **entire** contents of `frontend/src/components/theme-provider.tsx` with:

```tsx
import { createContext, useContext, useEffect } from "react"

// The app is dark-only. This provider exists so `useTheme()` consumers
// (sonner toaster, etc.) keep a stable API; it always forces the `dark` class.
type ThemeProviderState = {
  theme: "dark"
  resolvedTheme: "dark"
  setTheme: () => void
}

const initialState: ThemeProviderState = {
  theme: "dark",
  resolvedTheme: "dark",
  setTheme: () => null,
}

const ThemeProviderContext = createContext<ThemeProviderState>(initialState)

export function ThemeProvider({
  children,
}: {
  children: React.ReactNode
  // Accepted for call-site compatibility (main.tsx passes these); ignored.
  defaultTheme?: string
  storageKey?: string
}) {
  useEffect(() => {
    const root = window.document.documentElement
    root.classList.remove("light")
    root.classList.add("dark")
  }, [])

  return (
    <ThemeProviderContext.Provider value={initialState}>
      {children}
    </ThemeProviderContext.Provider>
  )
}

export const useTheme = () => useContext(ThemeProviderContext)
```

- [ ] **Step 2: Delete the Appearance component**

```bash
git rm frontend/src/components/Common/Appearance.tsx
```

- [ ] **Step 3: Remove `SidebarAppearance` from the sidebar**

In `frontend/src/components/Sidebar/AppSidebar.tsx`:
- Delete the import line: `import { SidebarAppearance } from "@/components/Common/Appearance"`
- In `SidebarFooter`, delete the `<SidebarAppearance />` line so it reads:

```tsx
      <SidebarFooter>
        <User user={currentUser} />
      </SidebarFooter>
```

- [ ] **Step 4: Remove `Appearance` from the auth layout**

In `frontend/src/components/Common/AuthLayout.tsx`:
- Delete the import line: `import { Appearance } from "@/components/Common/Appearance"`
- Delete the toggle container so the right column starts directly with the centered form:

```tsx
      <div className="flex flex-col gap-4 p-6 md:p-10">
        <div className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-xs">{children}</div>
        </div>
        <Footer />
      </div>
```

- [ ] **Step 5: Replace the three theme-toggle E2E tests with one dark-only test**

In `frontend/tests/user-settings.spec.ts`, replace the three tests at lines 205-256 (`"Appearance button is visible in sidebar"`, `"User can switch between theme modes"`, `"Selected mode is preserved across sessions"`) with this single test:

```ts
test("App is dark-only (no theme toggle)", async ({ page }) => {
  await page.goto("/settings")
  await expect(page.locator("html")).toHaveClass(/dark/)
  await expect(page.getByTestId("theme-button")).toHaveCount(0)
})
```

- [ ] **Step 6: Verify no stragglers reference the removed APIs**

Run (from repo root): `git grep -nE "Appearance|theme-button|light-mode|dark-mode|setTheme" -- frontend/src frontend/tests`
Expected: no matches in `frontend/src` (the `theme-button` testid only survives inside the new dark-only test in `frontend/tests/user-settings.spec.ts`, asserting it is absent). If anything else matches, remove it.

- [ ] **Step 7: Typecheck + lint**

Run: `bunx tsc -p tsconfig.build.json --noEmit` → no errors.
Run: `bun run lint` → clean.

- [ ] **Step 8: Visual check**

Run `bun run dev`. Expected: no "Appearance" item in the sidebar footer, no toggle on the login page, `<html>` always has the `dark` class (DevTools → Elements).

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(ui): dark-only theme; remove appearance toggle

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Logo & app identity (CASTRA NOVA)

**Files:**
- Add: `frontend/public/assets/images/castranova-logo.jpg`
- Modify: `frontend/src/components/Common/Logo.tsx` (rewrite)
- Modify: `frontend/index.html:5,7,8` (title + favicon)
- Modify: `frontend/vite.config.ts:24-33` (manifest)
- Modify: `frontend/src/components/Common/Footer.tsx`

- [ ] **Step 1: Copy the brand asset into the repo**

PowerShell (run from repo root):

```powershell
Copy-Item "C:\Users\wai19\Downloads\653699374_122123042949065484_354138185532947125_n.jpg" `
  "frontend\public\assets\images\castranova-logo.jpg"
```

Verify it exists: `Test-Path "frontend\public\assets\images\castranova-logo.jpg"` → `True`.

- [ ] **Step 2: Rewrite the Logo component to use the JPG**

Replace the **entire** contents of `frontend/src/components/Common/Logo.tsx` with:

```tsx
import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"
import logo from "/assets/images/castranova-logo.jpg"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

// The brand mark is a gold-on-black JPG. `mix-blend-lighten` drops the pure-black
// background against the app's dark surfaces so only the gold mark shows.
const BLEND = "mix-blend-lighten"

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content =
    variant === "responsive" ? (
      <>
        <img
          src={logo}
          alt="CASTRA NOVA"
          className={cn(
            BLEND,
            "h-10 w-auto group-data-[collapsible=icon]:hidden",
            className,
          )}
        />
        <img
          src={logo}
          alt="CASTRA NOVA"
          className={cn(
            BLEND,
            "size-7 hidden group-data-[collapsible=icon]:block",
            className,
          )}
        />
      </>
    ) : (
      <img
        src={logo}
        alt="CASTRA NOVA"
        className={cn(BLEND, variant === "full" ? "h-12 w-auto" : "size-7", className)}
      />
    )

  if (!asLink) {
    return content
  }

  return <Link to="/">{content}</Link>
}
```

- [ ] **Step 3: Update the tab title and favicon**

In `frontend/index.html`:
- Delete the stray Vite icon line: `<link rel="icon" type="image/svg+xml" href="/vite.svg" />` (line 5).
- Change the title (line 7) to: `<title>CASTRA NOVA</title>`
- Change the favicon line (line 8) to: `<link rel="icon" type="image/jpeg" href="/assets/images/castranova-logo.jpg" />`

- [ ] **Step 4: Update the PWA manifest**

In `frontend/vite.config.ts`, update the `workbox` glob to include jpg and the `manifest` block:

```ts
      workbox: {
        globPatterns: ["**/*.{js,css,html,ico,png,jpg,svg,woff2}"],
      },
      manifest: {
        name: "CASTRA NOVA POS",
        short_name: "CASTRA NOVA",
        theme_color: "#0B0B0D",
        background_color: "#0B0B0D",
        display: "standalone",
        start_url: "/",
        icons: [
          {
            src: "/assets/images/castranova-logo.jpg",
            sizes: "512x512",
            type: "image/jpeg",
            purpose: "any",
          },
        ],
      },
```

- [ ] **Step 5: Rebrand the footer**

Replace the **entire** contents of `frontend/src/components/Common/Footer.tsx` with a minimal brand line (the old footer linked to FastAPI's own socials, which aren't this product's):

```tsx
export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="border-t py-4 px-6">
      <p className="text-muted-foreground text-center text-sm tracking-wide">
        CASTRA NOVA · {currentYear}
      </p>
    </footer>
  )
}
```

- [ ] **Step 6: Typecheck + lint**

Run: `bunx tsc -p tsconfig.build.json --noEmit` → no errors.
Run: `bun run lint` → clean.

- [ ] **Step 7: Visual check**

Run `bun run dev`. Expected: CASTRA NOVA mark in the sidebar header and on the login screen (gold, no black box around it — the blend should make the black seamless on the dark surface; if any black halo shows, switch `mix-blend-lighten` → `mix-blend-screen`). Browser tab reads "CASTRA NOVA". Footer reads "CASTRA NOVA · <year>".

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(brand): CASTRA NOVA logo, favicon, PWA manifest, footer

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Sidebar navigation polish

**Files:**
- Modify: `frontend/src/components/Sidebar/Main.tsx`
- Modify: `frontend/src/components/Sidebar/AppSidebar.tsx:82-101`
- Modify: `frontend/src/index.css` (append active-bar rule)

- [ ] **Step 1: Add an optional section label to `Main`**

In `frontend/src/components/Sidebar/Main.tsx`:
- Add `SidebarGroupLabel` to the existing import from `@/components/ui/sidebar`.
- Add an optional `label` to the props and render it. The full updated file:

```tsx
import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import type { LucideIcon } from "lucide-react"

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

export type Item = {
  icon: LucideIcon
  title: string
  path: string
}

interface MainProps {
  items: Item[]
  label?: string
}

export function Main({ items, label }: MainProps) {
  const { isMobile, setOpenMobile } = useSidebar()
  const router = useRouterState()
  const currentPath = router.location.pathname

  const handleMenuClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  return (
    <SidebarGroup>
      {label ? <SidebarGroupLabel>{label}</SidebarGroupLabel> : null}
      <SidebarGroupContent>
        <SidebarMenu>
          {items.map((item) => {
            const isActive = currentPath === item.path

            return (
              <SidebarMenuItem key={item.title}>
                <SidebarMenuButton
                  tooltip={item.title}
                  isActive={isActive}
                  asChild
                >
                  <RouterLink to={item.path} onClick={handleMenuClick}>
                    <item.icon />
                    <span>{item.title}</span>
                  </RouterLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            )
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}
```

- [ ] **Step 2: Render two labeled groups in `AppSidebar`**

In `frontend/src/components/Sidebar/AppSidebar.tsx`, remove the merged `items` variable and render base + admin as labeled groups (same items, same order, paths unchanged):

```tsx
export function AppSidebar() {
  const { user: currentUser } = useAuth()
  const { isAdmin } = useRole()

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main items={baseItems} label="Workspace" />
        {isAdmin ? <Main items={adminItems} label="Admin" /> : null}
      </SidebarContent>
      <SidebarFooter>
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}
```

(Leave the `baseItems` / `adminItems` definitions and all other imports unchanged.)

- [ ] **Step 3: Add the gold active-bar rule to `index.css`**

Append to `frontend/src/index.css` (after the `.num` utility block):

```css
/* ── Sidebar: gold left bar on the active item ───────────────────────────── */
@layer components {
  [data-slot="sidebar-menu-button"][data-active="true"] {
    position: relative;
  }
  [data-slot="sidebar-menu-button"][data-active="true"]::before {
    content: "";
    position: absolute;
    left: 0;
    top: 6px;
    bottom: 6px;
    width: 3px;
    border-radius: 0 3px 3px 0;
    background: linear-gradient(180deg, #F5D76E, #AA771C);
  }
}
```

- [ ] **Step 4: Typecheck + lint**

Run: `bunx tsc -p tsconfig.build.json --noEmit` → no errors.
Run: `bun run lint` → clean.

- [ ] **Step 5: Visual check**

Run `bun run dev`. Expected: sidebar shows a "Workspace" group (and "Admin" group for admins); the current route's item has a gold-tinted background, gold text, and a gold left bar. Collapse the sidebar (rail toggle) → only the small square logo shows, tooltips still work.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(ui): sidebar gold active state + sectioned nav groups

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Login / auth polish

**Files:**
- Modify: `frontend/src/components/Common/AuthLayout.tsx`
- Modify: `frontend/src/routes/login.tsx:44-50,77-79`

- [ ] **Step 1: Give the auth hero a luxury backdrop**

In `frontend/src/components/Common/AuthLayout.tsx`, replace the left hero panel's classes (the `bg-muted dark:bg-zinc-900 …` div) with a subtle radial gold glow on near-black, and size the logo up:

```tsx
      <div className="relative hidden lg:flex lg:items-center lg:justify-center bg-[radial-gradient(120%_120%_at_50%_0%,#15130b_0%,#0B0B0D_60%)] border-r border-[rgba(212,175,55,0.14)]">
        <Logo variant="full" className="h-20" asLink={false} />
      </div>
```

(Keep the rest of the file as left by Task 2.)

- [ ] **Step 2: Brand the login heading + tab title**

In `frontend/src/routes/login.tsx`:
- Change the head title (line ~47) to: `title: "Log In · CASTRA NOVA",`
- Replace the heading block (lines ~77-79) with a branded welcome:

```tsx
          <div className="flex flex-col items-center gap-1 text-center">
            <h1 className="text-2xl font-bold">Welcome back</h1>
            <p className="text-muted-foreground text-sm">
              Sign in to your CASTRA NOVA account
            </p>
          </div>
```

- [ ] **Step 3: Typecheck + lint**

Run: `bunx tsc -p tsconfig.build.json --noEmit` → no errors.
Run: `bun run lint` → clean.

- [ ] **Step 4: Visual check**

Run `bun run dev`, open `/login` (log out first if needed). Expected: large CASTRA NOVA mark on a softly gold-lit dark hero (desktop), "Welcome back" heading in Space Grotesk, gold "Log In" button. No theme toggle.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(ui): branded login hero + welcome heading

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Dashboard — branded quick-action cards

> **Scope note (read this):** The approved mockup showed live revenue/orders KPIs, but those need backend aggregation endpoints that don't exist — out of this frontend-only pass (spec §6). The current dashboard is a bare stub. This task replaces it with a **branded landing of quick-action navigation cards** (frontend-only, no fabricated numbers), which is the honest in-scope win. Live KPI tiles are a recommended follow-up that requires a backend endpoint.

**Files:**
- Modify: `frontend/src/routes/_layout/index.tsx` (rewrite the component)

- [ ] **Step 1: Rewrite the dashboard as a branded quick-action grid**

Replace the **entire** contents of `frontend/src/routes/_layout/index.tsx` with (uses the existing shadcn `Card` + base-nav routes only, so it's safe for both roles):

```tsx
import { Link, createFileRoute } from "@tanstack/react-router"
import {
  AlertTriangle,
  Bell,
  ClipboardList,
  PackagePlus,
  Search,
  ShoppingCart,
  Warehouse,
  Wrench,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { Card, CardContent } from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [{ title: "Dashboard · CASTRA NOVA" }],
  }),
})

type Action = { icon: LucideIcon; title: string; desc: string; path: string }

const actions: Action[] = [
  { icon: ShoppingCart, title: "New Sale", desc: "Scan and check out", path: "/sale" },
  { icon: Search, title: "Search", desc: "Find products & serials", path: "/search" },
  { icon: Warehouse, title: "Stock", desc: "On-hand by location", path: "/stock" },
  { icon: AlertTriangle, title: "Low Stock", desc: "Items below reorder", path: "/low-stock" },
  { icon: PackagePlus, title: "Receive", desc: "Log incoming inventory", path: "/receive" },
  { icon: Wrench, title: "Tickets", desc: "Service & repair", path: "/tickets" },
  { icon: ClipboardList, title: "Pulls", desc: "Fulfil pull requests", path: "/pulls" },
  { icon: Bell, title: "Notifications", desc: "Alerts & opt-in", path: "/notifications" },
]

function Dashboard() {
  const { user: currentUser } = useAuth()
  const name = currentUser?.full_name || currentUser?.email

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          Welcome back, {name}
        </h1>
        <p className="text-muted-foreground">Jump straight into a task.</p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        {actions.map((a) => (
          <Link key={a.path} to={a.path} className="group">
            <Card className="h-full transition-colors hover:border-primary/60">
              <CardContent className="flex flex-col gap-3 p-5">
                <span className="flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary/20">
                  <a.icon className="size-5" />
                </span>
                <div>
                  <div className="font-medium">{a.title}</div>
                  <div className="text-muted-foreground text-sm">{a.desc}</div>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Typecheck + lint**

Run: `bunx tsc -p tsconfig.build.json --noEmit` → no errors.
Run: `bun run lint` → clean.

- [ ] **Step 3: Visual check**

Run `bun run dev`, open `/`. Expected: "Welcome back, <name>" heading; a responsive grid of cards each with a gold icon chip; hovering a card highlights its border gold and the chip deepens; clicking navigates to the route.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(ui): branded dashboard with quick-action cards

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Final verification + inherited-screen visual pass

**Files:** none (verification only)

- [ ] **Step 1: Clean typecheck + lint across the change set**

Run: `bunx tsc -p tsconfig.build.json --noEmit` → no errors.
Run: `bun run lint` → clean.

- [ ] **Step 2: Production build sanity**

Run: `bun run build`
Expected: build succeeds (this runs the strict `tsconfig.build.json` typecheck + Vite build, and confirms the new font links, logo import, and manifest are valid).

- [ ] **Step 3: Run the E2E suite (needs the dev stack up)**

Bring the stack up if it isn't (`docker compose watch` per CLAUDE.md), then run:
`bun run test`
Expected: all pass. Pay attention to `tests/user-settings.spec.ts` — the new `"App is dark-only (no theme toggle)"` test should pass and the three removed theme tests should be gone. If any test fails on a selector tied to the old toggle/light-mode classes, fix the test to match the dark-only design (not the app).

- [ ] **Step 4: Inherited-screen visual pass**

Run `bun run dev` and eyeball the screens that were re-skinned purely by tokens (no dedicated task):
- `/sale` — checkout button is gold (was `bg-cta`); "Sale" heading in Space Grotesk; cart legible.
- `/products`, `/stock`, `/suppliers` — tables readable on dark; headers, badges, and primary buttons gold; focus rings gold.
- `/settings` — no Appearance toggle; forms styled.
Confirm contrast reads well (gold text/icons on dark, black text on gold buttons). Note any screen that looks wrong for a later per-page polish pass — do **not** expand scope here.

- [ ] **Step 5: Final review + push**

```bash
git status            # working tree clean
git log --oneline dev..HEAD   # review the redesign commits
git push -u origin feat/redesign-obsidian-gold
```

Then open a PR into `dev` (per CLAUDE.md flow). Use the Review stage skills (`requesting-code-review` + `ecc:react-reviewer`, `ecc:typescript-reviewer`) before merging.

---

## Self-Review

**Spec coverage (spec §-by-§):**
- §3 tokens (palette, gold primary, `--cta` gold, gold ring, charts, fonts) → Task 1. ✓
- §3 dark-only (`:root` = dark, drop `.dark` block, force `.dark` class) → Task 1 + Task 2. ✓
- §4 logo/identity (JPG, blend, favicon, PWA, CASTRA NOVA text) → Task 3. ✓
- §5.1 sidebar (gold active + left bar, sectioned groups, brand header) → Task 4. ✓
- §5.2 login/auth → Task 5. ✓
- §5.3 dashboard → Task 6 (with an explicit scope note: nav cards now, live KPIs deferred — flagged for the user). ✓
- §5.4 Sale screen → inherits via Task 1 (`bg-cta` → gold, `<h1>` display font); verified in Task 7. ✓
- §5.5 shared shadcn primitives → token-driven via Task 1; verified in Task 7. ✓
- §6 scope discipline (no SDK regen / backend / generated files) → stated in Prerequisites. ✓
- §7 verification (tsc, biome, Playwright, visual, contrast) → per-task + Task 7. ✓
- §8 risks (toggle removal touches theme-provider/AppSidebar/AuthLayout; E2E test on toggle) → handled in Task 2. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has expected output. ✓

**Type/name consistency:** `useTheme()` keeps `{ theme, resolvedTheme, setTheme }` (sonner-compatible); `Logo` keeps its `{ variant, className, asLink }` props; `Main` gains an optional `label` and all call sites updated; deleted `Appearance.tsx` has all imports removed (verified by Step 2.6 grep). ✓

**Known intentional deviation from the mockup:** live dashboard KPIs are deferred (Task 6 scope note) because they require backend aggregation that is out of this frontend-only pass.
