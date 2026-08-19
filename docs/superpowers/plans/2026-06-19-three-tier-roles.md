# Three-tier Roles (Superuser → Admin → Staff) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the system's latent three-tier privilege model in the UI — let a Superuser create Admins/Staff via a role dropdown, show the correct tier everywhere, and restrict user management to Superusers only.

**Architecture:** Frontend-only. The backend already carries `role: UserRole` on `UserBase` (so `UserCreate`/`UserUpdate`/`UserPublic` and the generated SDK already type it) and already gates user-management routes on `get_current_active_superuser`. We add a `tierLabel`/`isSuperuser` helper, a `requireSuperuser` route guard, swap the "Is superuser?" checkbox for an Admin/Staff `<Select>` in the Add/Edit dialogs, render a three-state role badge, and gate the Users page + nav entry on Superuser.

**Tech Stack:** React + TypeScript, TanStack Router/Query, shadcn/ui (`Select`), react-hook-form + zod, Playwright (pure-logic unit specs + E2E). Enum values stay `BKK_ADMIN`/`YGN_STAFF`; UI labels are "Admin"/"Staff".

**Reference spec:** `docs/superpowers/specs/2026-06-19-three-tier-roles-design.md`

---

## File Structure

- `frontend/src/hooks/useRole.ts` — add `isSuperuser` to `roleFlags` return; add exported `tierLabel(user)` pure helper.
- `frontend/tests/useRole.spec.ts` — update existing `toEqual` expectations for the new `isSuperuser` field; add `tierLabel` cases.
- `frontend/src/lib/route-guards.ts` — add `requireSuperuser()`.
- `frontend/src/components/Admin/AddUser.tsx` — replace superuser checkbox with required Role select.
- `frontend/src/components/Admin/EditUser.tsx` — replace superuser checkbox with Role select; lock it for the superuser target; stop submitting `is_superuser`.
- `frontend/src/components/Admin/columns.tsx` — three-state role badge.
- `frontend/src/routes/_layout/admin.tsx` — `UserCard` badge → three-state; route guard → `requireSuperuser`; Alert copy refresh.
- `frontend/src/components/Sidebar/AppSidebar.tsx` — split the "Admin" (Users) nav entry out of `adminItems` so only Superusers see it.
- `frontend/tests/roles.spec.ts` — new E2E coverage.

---

## Task 1: `useRole` — `isSuperuser` flag + `tierLabel` helper

**Files:**
- Modify: `frontend/src/hooks/useRole.ts`
- Test: `frontend/tests/useRole.spec.ts`

Note: `roleFlags` currently returns `{ isAdmin, isStaff, role }` and the existing
spec asserts with exact `toEqual`. Adding `isSuperuser` changes the shape, so the
existing expectations MUST be updated in the same task.

- [ ] **Step 1: Update existing tests + add `tierLabel` tests (failing)**

Replace the entire contents of `frontend/tests/useRole.spec.ts` with:

```ts
import { expect, test } from "@playwright/test"
import { roleFlags, tierLabel } from "../src/hooks/useRole"

// Pure-logic coverage of roleFlags + tierLabel helpers.
// No browser / auth / backend required — mirrors scanner.spec.ts pattern.

test("superuser with no role → isAdmin/isSuperuser true, isStaff false", () => {
  expect(roleFlags({ is_superuser: true })).toEqual({
    isAdmin: true,
    isStaff: false,
    isSuperuser: true,
    role: null,
  })
})

test("superuser with BKK_ADMIN role → isAdmin/isSuperuser true", () => {
  expect(roleFlags({ is_superuser: true, role: "BKK_ADMIN" })).toEqual({
    isAdmin: true,
    isStaff: false,
    isSuperuser: true,
    role: "BKK_ADMIN",
  })
})

test("superuser with YGN_STAFF role → superuser wins", () => {
  expect(roleFlags({ is_superuser: true, role: "YGN_STAFF" })).toEqual({
    isAdmin: true,
    isStaff: false,
    isSuperuser: true,
    role: "YGN_STAFF",
  })
})

test("BKK_ADMIN (not superuser) → isAdmin true, isSuperuser false", () => {
  expect(roleFlags({ is_superuser: false, role: "BKK_ADMIN" })).toEqual({
    isAdmin: true,
    isStaff: false,
    isSuperuser: false,
    role: "BKK_ADMIN",
  })
})

test("YGN_STAFF (not superuser) → isStaff true, isAdmin/isSuperuser false", () => {
  expect(roleFlags({ is_superuser: false, role: "YGN_STAFF" })).toEqual({
    isAdmin: false,
    isStaff: true,
    isSuperuser: false,
    role: "YGN_STAFF",
  })
})

test("no role + not superuser → all false, role null", () => {
  expect(roleFlags({ is_superuser: false })).toEqual({
    isAdmin: false,
    isStaff: false,
    isSuperuser: false,
    role: null,
  })
})

test("null user → all false, role null", () => {
  expect(roleFlags(null)).toEqual({
    isAdmin: false,
    isStaff: false,
    isSuperuser: false,
    role: null,
  })
})

test("undefined user → all false, role null", () => {
  expect(roleFlags(undefined)).toEqual({
    isAdmin: false,
    isStaff: false,
    isSuperuser: false,
    role: null,
  })
})

test("tierLabel: superuser → 'Superuser'", () => {
  expect(tierLabel({ is_superuser: true })).toBe("Superuser")
})

test("tierLabel: superuser wins over staff role", () => {
  expect(tierLabel({ is_superuser: true, role: "YGN_STAFF" })).toBe("Superuser")
})

test("tierLabel: BKK_ADMIN (not superuser) → 'Admin'", () => {
  expect(tierLabel({ is_superuser: false, role: "BKK_ADMIN" })).toBe("Admin")
})

test("tierLabel: YGN_STAFF → 'Staff'", () => {
  expect(tierLabel({ is_superuser: false, role: "YGN_STAFF" })).toBe("Staff")
})

test("tierLabel: no role + not superuser → 'Staff' (least privilege)", () => {
  expect(tierLabel({ is_superuser: false })).toBe("Staff")
})

test("tierLabel: null user → 'Staff'", () => {
  expect(tierLabel(null)).toBe("Staff")
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && bun run test tests/useRole.spec.ts`
Expected: FAIL — `tierLabel` is not exported, and `roleFlags` results lack `isSuperuser`.

- [ ] **Step 3: Implement `isSuperuser` + `tierLabel`**

Replace the contents of `frontend/src/hooks/useRole.ts` with:

```ts
import type { UserRole } from "@/client"
import useAuth from "./useAuth"

type UserLike = { is_superuser?: boolean; role?: UserRole | null } | null | undefined

/**
 * Pure helper — unit-testable without React.
 * Admin = superuser OR BKK_ADMIN. No role + not superuser → least-privilege.
 * Note: `is_superuser` absent/undefined is treated as non-admin (least-privilege); a backend
 * schema regression that drops the field will silently downgrade the user — intentional fail-safe.
 */
export function roleFlags(user: UserLike): {
  isAdmin: boolean
  isStaff: boolean
  isSuperuser: boolean
  role: UserRole | null
} {
  const isSuperuser = !!user && user.is_superuser === true
  const isAdmin = isSuperuser || (!!user && user.role === "BKK_ADMIN")
  const isStaff = !!user && user.role === "YGN_STAFF" && !isAdmin
  return { isAdmin, isStaff, isSuperuser, role: user?.role ?? null }
}

/**
 * Friendly tier label for display. Superuser wins; then BKK_ADMIN → "Admin";
 * everything else (including missing role) → "Staff" (least-privilege default).
 */
export function tierLabel(user: UserLike): "Superuser" | "Admin" | "Staff" {
  const { isSuperuser, isAdmin } = roleFlags(user)
  if (isSuperuser) return "Superuser"
  if (isAdmin) return "Admin"
  return "Staff"
}

/** React hook — thin wrapper over roleFlags + useAuth. */
export function useRole() {
  const { user } = useAuth()
  return roleFlags(user)
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && bun run test tests/useRole.spec.ts`
Expected: PASS (14 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useRole.ts frontend/tests/useRole.spec.ts
git commit -m "feat(roles): add isSuperuser flag + tierLabel helper to useRole"
```

---

## Task 2: `requireSuperuser` route guard

**Files:**
- Modify: `frontend/src/lib/route-guards.ts`

- [ ] **Step 1: Add the guard**

Append this function to `frontend/src/lib/route-guards.ts` (after `requireAdmin`):

```ts
/**
 * Superuser-only guard for user management (the Admin/Users page). Plain Admins
 * (BKK_ADMIN) are redirected to "/". The backend user routes are already gated on
 * `get_current_active_superuser`; this mirrors that on the client for clean UX.
 */
export async function requireSuperuser(): Promise<void> {
  if (!isLoggedIn()) {
    throw redirect({ to: "/login" })
  }
  const user = await UsersService.readUserMe()
  if (!roleFlags(user).isSuperuser) {
    throw redirect({ to: "/" })
  }
}
```

- [ ] **Step 2: Verify typecheck/lint**

Run: `cd frontend && bunx tsc --noEmit`
Expected: PASS (no type errors in `route-guards.ts`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/route-guards.ts
git commit -m "feat(roles): add requireSuperuser route guard"
```

---

## Task 3: AddUser — Role select (Admin / Staff)

**Files:**
- Modify: `frontend/src/components/Admin/AddUser.tsx`

Behaviour: a required Role select replaces the "Is superuser?" checkbox. The form
always submits `is_superuser: false` (kept in the schema/defaults, just no UI) plus
the chosen `role`. The "Is active?" checkbox is left exactly as-is. Superuser is
never offered.

- [ ] **Step 1: Add the `role` field to the zod schema**

In `frontend/src/components/Admin/AddUser.tsx`, change the `formSchema` object so it
includes `role` (place it next to `is_superuser`):

```ts
    is_superuser: z.boolean(),
    is_active: z.boolean(),
    role: z.enum(["BKK_ADMIN", "YGN_STAFF"]),
```

- [ ] **Step 2: Default the new field**

In the `useForm` `defaultValues`, add `role` (default Staff):

```ts
      is_superuser: false,
      is_active: false,
      role: "YGN_STAFF",
```

- [ ] **Step 3: Import the Select primitives**

Add this import block alongside the existing UI imports:

```ts
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
```

- [ ] **Step 4: Replace the "Is superuser?" FormField with the Role select**

Delete the entire `<FormField ... name="is_superuser" ...>...</FormField>` block and
replace it with:

```tsx
              <FormField
                control={form.control}
                name="role"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      Role <span className="text-destructive">*</span>
                    </FormLabel>
                    <Select
                      value={field.value}
                      onValueChange={field.onChange}
                    >
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="BKK_ADMIN">Admin</SelectItem>
                        <SelectItem value="YGN_STAFF">Staff</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
```

(The `is_active` FormField directly below stays unchanged.)

- [ ] **Step 5: Remove the now-unused Checkbox import if orphaned**

The `is_active` field still uses `Checkbox`, so the import stays. Verify with:

Run: `cd frontend && grep -c "Checkbox" src/components/Admin/AddUser.tsx`
Expected: ≥ 2 (import + the `is_active` usage). If only the import remains, remove it.

- [ ] **Step 6: Verify typecheck**

Run: `cd frontend && bunx tsc --noEmit`
Expected: PASS. (`UserCreate` already includes `role?: UserRole`, so `mutate(data)` still types.)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Admin/AddUser.tsx
git commit -m "feat(roles): add Admin/Staff role select to AddUser form"
```

---

## Task 4: EditUser — Role select with Superuser lock

**Files:**
- Modify: `frontend/src/components/Admin/EditUser.tsx`

Behaviour: same Role select. When the target user is a superuser, the select is
replaced by a disabled "Superuser" display and `role` is NOT submitted (cannot demote
the seed god account). `is_superuser` is removed from the schema/submit entirely so it
is never sent — `crud.update_user` is `exclude_unset`, so the existing value is
preserved.

- [ ] **Step 1: Swap `is_superuser` for `role` in the zod schema**

In `frontend/src/components/Admin/EditUser.tsx`, replace this schema line:

```ts
    is_superuser: z.boolean().optional(),
```

with:

```ts
    role: z.enum(["BKK_ADMIN", "YGN_STAFF"]).optional(),
```

- [ ] **Step 2: Swap the default value**

In `useForm` `defaultValues`, replace:

```ts
      is_superuser: user.is_superuser,
```

with:

```ts
      role: user.role ?? "YGN_STAFF",
```

- [ ] **Step 3: Import the Select primitives**

Add alongside the existing UI imports:

```ts
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
```

- [ ] **Step 4: Never submit `role` for a superuser**

In `onSubmit`, after the existing password-stripping block, add a superuser guard:

```ts
  const onSubmit = (data: FormData) => {
    // exclude confirm_password from submission data and remove password if empty
    const { confirm_password: _, ...submitData } = data
    if (!submitData.password) {
      delete submitData.password
    }
    // Never change the seed superuser's tier: drop role so exclude_unset preserves it.
    if (user.is_superuser) {
      delete submitData.role
    }
    mutation.mutate(submitData)
  }
```

- [ ] **Step 5: Replace the "Is superuser?" FormField**

Delete the entire `<FormField ... name="is_superuser" ...>...</FormField>` block and
replace it with a conditional: a locked display for the superuser, else the select:

```tsx
              {user.is_superuser ? (
                <FormItem>
                  <FormLabel>Role</FormLabel>
                  <FormControl>
                    <Input value="Superuser" disabled readOnly />
                  </FormControl>
                </FormItem>
              ) : (
                <FormField
                  control={form.control}
                  name="role"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Role</FormLabel>
                      <Select
                        value={field.value}
                        onValueChange={field.onChange}
                      >
                        <FormControl>
                          <SelectTrigger className="w-full">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="BKK_ADMIN">Admin</SelectItem>
                          <SelectItem value="YGN_STAFF">Staff</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
```

(`Input` is already imported in EditUser. The `is_active` FormField below stays.)

- [ ] **Step 6: Verify typecheck**

Run: `cd frontend && bunx tsc --noEmit`
Expected: PASS. `UserUpdate` includes `role?: UserRole` and no longer requires
`is_superuser` in `submitData`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Admin/EditUser.tsx
git commit -m "feat(roles): add role select to EditUser with superuser lock"
```

---

## Task 5: Three-state role badge (table + mobile card)

**Files:**
- Modify: `frontend/src/components/Admin/columns.tsx`
- Modify: `frontend/src/routes/_layout/admin.tsx`

- [ ] **Step 1: Use `tierLabel` in the table "Role" column**

In `frontend/src/components/Admin/columns.tsx`, add the import:

```ts
import { tierLabel } from "@/hooks/useRole"
```

Then replace the `is_superuser` "Role" column cell:

```tsx
  {
    accessorKey: "is_superuser",
    header: "Role",
    cell: ({ row }) => (
      <Badge variant={row.original.is_superuser ? "default" : "secondary"}>
        {row.original.is_superuser ? "Superuser" : "User"}
      </Badge>
    ),
  },
```

with:

```tsx
  {
    accessorKey: "is_superuser",
    header: "Role",
    cell: ({ row }) => {
      const label = tierLabel(row.original)
      return (
        <Badge variant={label === "Staff" ? "secondary" : "default"}>
          {label}
        </Badge>
      )
    },
  },
```

- [ ] **Step 2: Use `tierLabel` in the mobile `UserCard`**

In `frontend/src/routes/_layout/admin.tsx`, add `tierLabel` to the existing useRole
import. Find:

```ts
import useAuth from "@/hooks/useAuth"
```

and add below it:

```ts
import { tierLabel } from "@/hooks/useRole"
```

Then in `UserCard`, replace:

```tsx
        <Badge variant={user.is_superuser ? "default" : "secondary"}>
          {user.is_superuser ? "Superuser" : "User"}
        </Badge>
```

with:

```tsx
        <Badge variant={tierLabel(user) === "Staff" ? "secondary" : "default"}>
          {tierLabel(user)}
        </Badge>
```

- [ ] **Step 3: Verify typecheck**

Run: `cd frontend && bunx tsc --noEmit`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Admin/columns.tsx frontend/src/routes/_layout/admin.tsx
git commit -m "feat(roles): show three-state tier badge in users table + card"
```

---

## Task 6: Gate Users page + nav entry on Superuser

**Files:**
- Modify: `frontend/src/routes/_layout/admin.tsx`
- Modify: `frontend/src/components/Sidebar/AppSidebar.tsx`

- [ ] **Step 1: Switch the Users route guard to superuser-only**

In `frontend/src/routes/_layout/admin.tsx`, change the guard import. Replace:

```ts
import { requireAdmin } from "@/lib/route-guards"
```

with:

```ts
import { requireSuperuser } from "@/lib/route-guards"
```

Then in the route definition, replace:

```ts
  beforeLoad: () => requireAdmin(),
```

with:

```ts
  beforeLoad: () => requireSuperuser(),
```

- [ ] **Step 2: Refresh the Alert copy to describe three tiers**

In `admin.tsx`, replace the `<AlertDescription>` text with:

```tsx
        <AlertDescription>
          Add teammates with Add User and pick a role — Admins see financial
          reports, overrides, and config; Staff get day-to-day POS access. Only
          Superusers (the primary account) manage user accounts. Use the row menu
          to edit or deactivate an account. Every user's stock actions stay
          traceable in the Audit ledger.
        </AlertDescription>
```

- [ ] **Step 3: Move the "Admin"/Users nav entry to a superuser-only list**

In `frontend/src/components/Sidebar/AppSidebar.tsx`, remove this last entry from the
`adminItems` array:

```ts
  { icon: Users, title: "Admin", path: "/admin" },
```

Add a new array immediately after `adminItems` closes:

```ts
// User-management page — Superuser-only (Superuser owns user management).
const superuserItems: Entry[] = [
  { icon: Users, title: "Admin", path: "/admin" },
]
```

- [ ] **Step 4: Render the superuser list only for superusers**

In `AppSidebar`, replace:

```tsx
  const { isAdmin } = useRole()
```

with:

```tsx
  const { isAdmin, isSuperuser } = useRole()
```

Then replace:

```tsx
        {isAdmin ? <Main entries={adminItems} label="Admin" /> : null}
```

with:

```tsx
        {isAdmin ? <Main entries={adminItems} label="Admin" /> : null}
        {isSuperuser ? <Main entries={superuserItems} label="Users" /> : null}
```

- [ ] **Step 5: Verify typecheck**

Run: `cd frontend && bunx tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/_layout/admin.tsx frontend/src/components/Sidebar/AppSidebar.tsx
git commit -m "feat(roles): restrict Users page + nav entry to Superusers"
```

---

## Task 7: E2E coverage

**Files:**
- Create: `frontend/tests/roles.spec.ts`

This verifies the three-tier UX end-to-end. It assumes the suite's standard login
helpers/fixtures; mirror the auth setup already used by the existing E2E specs in
`frontend/tests/` (read a neighbouring spec such as `audit.spec.ts` for the exact
login helper and superuser credentials before writing this file).

- [ ] **Step 1: Read an existing E2E spec for the login/fixture pattern**

Run: `cd frontend && sed -n '1,40p' tests/audit.spec.ts`
Expected: shows the import of the shared login helper + how a superuser session is
established. Reuse that exact helper in the new spec.

- [ ] **Step 2: Write the E2E spec**

Create `frontend/tests/roles.spec.ts`. Use the login helper discovered in Step 1
(shown below as `loginAsSuperuser(page)` — replace with the real helper name/signature):

```ts
import { expect, test } from "@playwright/test"
// import { loginAsSuperuser } from "./<helper-from-step-1>"

test("superuser can create an Admin via the role select", async ({ page }) => {
  // await loginAsSuperuser(page)
  await page.goto("/admin")
  await page.getByRole("button", { name: "Add User" }).click()

  const unique = `admin+${Date.now()}@example.com`
  await page.getByLabel("Email").fill(unique)
  await page.getByLabel("Set Password").fill("changethis123")
  await page.getByLabel("Confirm Password").fill("changethis123")

  // Open the Role select and choose Admin.
  await page.getByRole("combobox").click()
  await page.getByRole("option", { name: "Admin" }).click()

  await page.getByRole("button", { name: "Save" }).click()

  // The new user appears with an "Admin" tier badge.
  const row = page.getByRole("row", { name: new RegExp(unique) })
  await expect(row.getByText("Admin", { exact: true })).toBeVisible()
})

test("Add User role select offers only Admin and Staff (no Superuser)", async ({
  page,
}) => {
  // await loginAsSuperuser(page)
  await page.goto("/admin")
  await page.getByRole("button", { name: "Add User" }).click()
  await page.getByRole("combobox").click()

  await expect(page.getByRole("option", { name: "Admin" })).toBeVisible()
  await expect(page.getByRole("option", { name: "Staff" })).toBeVisible()
  await expect(
    page.getByRole("option", { name: "Superuser" }),
  ).toHaveCount(0)
})
```

- [ ] **Step 3: Run the E2E spec**

Run: `cd frontend && bun run test tests/roles.spec.ts`
Expected: PASS. (If the dev stack / DB reset harness is required, follow the same
pre-conditions the other E2E specs document.)

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/roles.spec.ts
git commit -m "test(roles): E2E coverage for role select + tier badges"
```

---

## Final verification

- [ ] **Step 1: Full frontend typecheck + lint**

Run: `cd frontend && bunx tsc --noEmit && bun run lint`
Expected: PASS.

- [ ] **Step 2: Full unit + targeted E2E**

Run: `cd frontend && bun run test tests/useRole.spec.ts tests/roles.spec.ts`
Expected: PASS.

- [ ] **Step 3: Confirm no SDK regen needed**

Run: `cd frontend && grep -n "role" src/client/types.gen.ts | grep -iE "UserCreate|UserUpdate|UserPublic" -A0 || grep -n "UserRole" src/client/types.gen.ts | head`
Expected: `role?: UserRole` already present on the user create/update/public types
(no `bun run generate-client` required because no backend schema changed).

---

## Notes / backlog (from the spec)

- Renaming `UserRole` enum to `ADMIN`/`STAFF` — out of scope.
- Backend "cannot demote the last superuser" guard — out of scope; the UI lock +
  `exclude_unset` cover the realistic path.
- No change to AddUser's `is_active` default (left as today).
