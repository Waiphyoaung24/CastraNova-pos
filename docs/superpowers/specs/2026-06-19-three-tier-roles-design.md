# Three-tier roles (Superuser → Admin → Staff) — Design

**Date:** 2026-06-19
**Status:** Approved (brainstorming)
**Scope:** Frontend-only. No DB migration, no `models.py` change, no new endpoints.

## Problem

The system has a latent three-tier privilege model that the UI never fully exposes:

- `User.is_superuser: bool` (template flag)
- `User.role: UserRole` enum with `BKK_ADMIN` / `YGN_STAFF`
- `deps.py`: admin = `is_superuser OR role == BKK_ADMIN`

Today the **Add User** form only offers an "Is superuser?" checkbox and never sets
`role`, so every created user silently defaults to `YGN_STAFF` (staff). Admins
(`BKK_ADMIN`) are **unreachable through the UI**. Effectively the live system is
two-tier (superuser/admin vs staff), and the Users page is open to anyone the
`requireAdmin` guard admits.

We want a clean, explicit **three-tier** model surfaced in the UI.

## Tier semantics

| Tier | Backing fields | Capabilities |
|---|---|---|
| **Superuser** | `is_superuser = true` | Everything an Admin can do **plus user management**. Reserved for the seed `admin@example.com`; **not creatable via the UI**. |
| **Admin** | `is_superuser = false`, `role = BKK_ADMIN` | Reports, overrides, system config — **but not user management**. |
| **Staff** | `is_superuser = false`, `role = YGN_STAFF` | Day-to-day POS access only. |

**Decisions locked during brainstorming:**

- *Superuser vs Admin:* Superuser owns user management; Admin gets everything else.
- *Form behaviour:* Role dropdown offering **Admin / Staff** only; Superuser stays
  reserved for the seed account and cannot be created via the UI.
- *Enum naming:* Keep `BKK_ADMIN` / `YGN_STAFF` in DB/API untouched; render plain
  "Admin" / "Staff" labels in the UI only (zero migration).

## Why frontend-only

`UserBase` already declares `role: UserRole`, so `UserCreate`, `UserUpdate`, and
`UserPublic` all carry `role` over the API and the generated SDK already types it.
The backend user-management routes use `get_current_active_superuser` (gated on
`is_superuser`), so a plain Admin already cannot hit them — the backend is already
consistent with "Superuser owns user management." `crud.update_user` uses
`model_dump(exclude_unset=True)`, so omitting `is_superuser` from an edit preserves
it (no accidental demotion).

## Components touched

1. **`frontend/src/hooks/useRole.ts`**
   - Add `isSuperuser: boolean` to the returned flags.
   - Add a `tierLabel(user)` helper returning `"Superuser" | "Admin" | "Staff"`
     (Superuser if `is_superuser`, else Admin if `role === "BKK_ADMIN"`, else Staff).
   - Keep `isAdmin` / `isStaff` semantics unchanged (backward compatible).

2. **`frontend/src/components/Admin/AddUser.tsx`**
   - Replace the "Is superuser?" checkbox with a **required Role `<Select>`**
     (options: Admin → `BKK_ADMIN`, Staff → `YGN_STAFF`; default Staff).
   - Submit always sends `is_superuser: false` plus the chosen `role`.
   - Leave the "Is active?" checkbox exactly as-is.

3. **`frontend/src/components/Admin/EditUser.tsx`**
   - Replace the "Is superuser?" checkbox with the same Role select.
   - **Superuser guard:** when the target user is a superuser, render the role as a
     disabled "Superuser" display and never submit `role` (cannot demote the seed
     god account). "Superuser" is never a selectable option.
   - Continue to omit `is_superuser` from the submit payload (preserved by
     `exclude_unset`).

4. **`frontend/src/components/Admin/columns.tsx` + `UserCard` in `admin.tsx`**
   - The "Role" badge becomes three-state via `tierLabel`
     (Superuser / Admin / Staff) instead of Superuser/User.

5. **`frontend/src/lib/route-guards.ts`**
   - Add `requireSuperuser()` (mirrors `requireAdmin` but checks `isSuperuser`).
   - Apply `requireSuperuser()` to **`admin.tsx`** (the Users page); all other admin
     pages keep `requireAdmin()`.

6. **Sidebar / nav** (verify exact file during build)
   - Hide the Users/Admin nav entry for non-superusers (only superusers see it).

## Approach note — editing the superuser

Chosen: **front-end protection, backend already safe.** The seed superuser's role
is shown read-only and never submitted; because `update_user` is `exclude_unset`,
even a stray request cannot silently demote it.

Rejected (for now): adding a backend "cannot demote the last superuser" check —
more robust but adds risk to the role-tiering backend for a UI-tier feature.
Tracked as backlog.

## Testing

- **Unit (`useRole`):** `tierLabel` and `isSuperuser` across all three tiers plus a
  null/undefined user (least-privilege fail-safe preserved).
- **E2E (Playwright):**
  - Superuser creates an Admin and a Staff via the role select; the Users table
    badge shows the correct tier for each.
  - An Admin login is redirected away from `/admin` and does not see the Users nav
    entry.
  - The superuser's Edit dialog shows the role locked (disabled "Superuser").

## Out of scope (backlog)

- Renaming the `UserRole` enum to `ADMIN` / `STAFF`.
- Backend "cannot demote last superuser" demotion guard.
- Any change to the AddUser `is_active` default.
