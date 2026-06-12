# CastraNova-POS — Pre-Deployment Hardening Design

**Date:** 2026-06-11
**Status:** Approved (brainstormed + user-validated)
**Precedes:** Part 5.4 Deploy
**Sources:** deferred-hardening ledger (memory), system design spec `2026-05-23-castranova-pos-system-design.md`, client PRD `2026-06-02-castranova-pos-v3.0-prd.md`

## 1. Context & Goal

Parts 0–5.3 plus the 5.2 E2E pass are complete. Before 5.4 (deploy), this pass
closes the security and correctness debts accumulated in the deferred-hardening
ledger, fixes the unordered-LIMIT-100 catalog bug, hardens the E2E test
infrastructure, and certifies the Definition of Done. Cross-checked against the
system design spec and the client PRD — most items *close gaps against language
already committed* (spec §4.6 app-role REVOKE, §10 M015/M016 service-ticket
FKs, §6.5/Flow F staff cost redaction, §6.2 auth-endpoint rate limits, PRD §8.2
"strict server-side enforcement").

**Out of scope:** 4.4 AI integration (deferred until signing); perf/tech-debt
extras (channel-margin indexes, low-stock N+1, Alembic enum-drop sweep,
notification-prefs ON CONFLICT); deploy-coupled items staying in 5.4
(proxy-aware rate-limit key, refresh-token denylist, migration-lock runbook,
CORS lock to prod domain); frontend combobox server-side search/pagination
(needed eventually at FR-012's "hundreds of SKUs", a product feature for later).

## 2. Decisions (user-confirmed)

| # | Decision | Choice |
|---|---|---|
| D1 | Scope buckets | Security hardening + catalog/test-infra + DoD sweep; perf extras parked |
| D2 | New-user role default | `YGN_STAFF` (least privilege); first superuser stays `BKK_ADMIN` via explicit seed |
| D3 | Object-level access (receipt.pdf, ticket parts/close, pull fulfill, unit label) | **Shared-team access** — any authenticated staff/admin may act; documented as policy in code comments + this spec. Matches PRD §5 (capability-based exclusions, ~5-person unified team) and spec §8 (role-level table). No ownership scoping. |
| D4 | Least-privilege runtime DB role | **Included now**, not deferred to 5.4 — it is the keystone that makes spec §4.6's REVOKE real |
| D5 | Structure | Three sequential PRs + DoD verification finale (A over single-PR / parallel-worktrees) |

## 3. PR 1 — Catalog correctness (the LIMIT-100 bug)

The shared catalogs (`list_products`, `list_customers`, `list_projects`,
`list_suppliers` in `crud.py`) are unordered `LIMIT 100` heap scans: past 100
rows, newly created rows silently vanish from every screen catalog (observed
live during the 5.2 pass at 107 products).

- **Ordering:** `ORDER BY created_at DESC` on the four list functions
  (newest-first is what counter screens need). *Verify-first:* confirm each
  table has `created_at`; any that lacks it gets a small backfilled-column
  migration per the audit conventions.
- **Bounds:** every list route's pagination params become validated
  `skip: int = Query(0, ge=0)`, `limit: int = Query(100, ge=1, le=500)` —
  closing the Part 2.6 "unbounded skip/limit" review item API-wide.
- **Tests:** newest-first ordering per endpoint; 422 on out-of-range params.
- **Frontend:** no change required — screens read the first page; newest-first
  restores visibility of recent rows.

Spec accordance: spec is silent on ordering; supports §6.1 perf targets. No
index needed at 500-SKU scale.

## 4. PR 2 — Security hardening

Ordering inside the PR: code items → FK migration → DB role **last** (it can
surface grant gaps across the whole suite; everything else must already be
green).

### 4.1 Code items

1. **Global `IntegrityError` handler** (`main.py`):
   `@app.exception_handler(IntegrityError)` → session-safe rollback → `409
   {"detail": "Conflicting or invalid data."}`; full exception logged
   server-side (Sentry). **Boundary (PRD §10):** domain conflicts — "already
   sold by [name] at [time]", "N actually available" — are raised explicitly by
   `crud.py` with informative payloads and MUST keep them; this handler only
   catches programming-bug escapes that would otherwise 500 with leaked
   constraint/table names. Do not "harmonize" domain 409s into the sanitized
   one.
2. **Replay user-binding:** the idempotency replay paths (`create_sale`,
   `receive_serialized`, `receive_quantity`, `open_service_ticket`) compare the
   stored acting user with the caller; mismatch → 409. **Spec §6.6 addendum:**
   §6.6's "replay returns the existing row (200 OK)" remains true for the case
   it describes (the same offline client retrying); the 409 fires only on a
   same-key/different-user collision, which legitimate flows never produce
   (client-generated 122-bit UUIDs). This does not touch PRD §10's
   "two staff sell the same machine" scenario — that is two *different* keys
   hitting the unit state machine, and its informative 409 is preserved.
3. **Sync-review audit + ownership:** new nullable `submitted_by_user_id` FK on
   `syncreviewitem` (migration; legacy rows stay NULL), set at ingest;
   ingest replay enforces `submitted_by_user_id == current_user.id` (same 409
   rule as item 2). Extends spec §6.9's actor-on-every-write principle; gives
   the admin reviewing a CONFLICT the originating user.
4. **Rate limits** (same `RATE_LIMIT_ENABLED`-gated slowapi pattern and
   route-decorator mechanics as 5.1's login limit — decorator above
   `@limiter.limit`, route takes `request: Request`):
   `POST /login/refresh-token` "5 per 15 minutes" (spec §6.2 covers auth
   endpoints plural), `POST /login/logout` "20 per 15 minutes",
   `POST /pricing-overrides` "30 per hour" (threshold-probe + queue-flood),
   `POST /sync-review` "120 per hour" (JSONB queue flood; must stay above any
   legitimate offline-replay burst from a full 7-day queue).
   Key function stays remote-address until 5.4's proxy-aware key (documented
   limitation; the limiter is env-disabled in local/E2E anyway).
5. **Role defaults:** `UserBase.role` default → `YGN_STAFF`;
   `PrivateUserCreate` gains `role: UserRole = YGN_STAFF`. First-superuser
   seeding stays explicitly `BKK_ADMIN` (spec §10 M001's note is about that
   seed, not a general default). Fixtures/tests relying on the implicit admin
   default get explicit roles.
6. **Refresh-token expiry spec alignment:** `REFRESH_TOKEN_EXPIRE_MINUTES`
   30d → **7 days** per spec §6.2 (the 5.1 "policy question" was already
   answered by the spec).
7. **FR-015 cost-history redaction (audit-then-fix):** enumerate every
   staff-reachable surface returning derived cost (SKU-search cost_line
   history, search/low-stock exports), then apply the established Staff-schema
   + `deps.is_admin` dispatch pattern (§6.5; financial fields *absent*, not
   blanked). **PRD FR-015 nuance:** staff keep "batch-by-batch attribution"
   (which batch, what quantity, when) — only THB cost fields
   (`unit_cost_thb`, `total_cost_thb`, batch `purchase_cost_thb`) are omitted.
   A staff variant that drops the history entirely would break a promised
   feature.
8. **Shared-team policy documentation (D3):** code comments at the four IDOR
   sites (`GET /sales/{id}/receipt.pdf`, service-ticket `parts`/`close`,
   pull `fulfill`, unit `label.pdf`) stating shared-team access is a recorded
   product decision, with a pointer to this spec.

### 4.2 Migrations

1. **Movement→service-ticket FKs** (spec §10 M015/M016 gap): wire
   `partmovement.service_ticket_id` and `unitmovement.service_ticket_id` FKs
   to `serviceticket.id`, plus the missing partial index on
   `unitmovement.service_ticket_id`. Orphan-row pre-check aborts the migration
   with a clear message if any exist.
2. **`syncreviewitem.submitted_by_user_id`** (per 4.1.3).
3. **Least-privilege DB role** (closes spec §4.6 / §6.9 "REVOKE … from the app
   role" — currently a no-op because the app connects as the `postgres`
   superuser, leaving the M021 triggers as the only line of defense):
   - **Role creation:** prestart idempotently ensures role `castranova_app`
     (LOGIN, password from new `POSTGRES_APP_PASSWORD` env var) — secrets never
     live in migrations.
   - **Grant matrix (Alembic migration):** ledgers (`unit_movement`,
     `part_movement`, `cost_line`, `price_change`, `notification_log`):
     `SELECT, INSERT` only — UPDATE/DELETE/TRUNCATE denied, so REVOKE finally
     bites alongside the triggers. Mutable tables: `SELECT, INSERT, UPDATE`
     (+ `DELETE` only where the domain hard-deletes, e.g. `user`). Sequences:
     `USAGE`. No DDL, no table ownership, no `CREATE` on schema.
   - **Connection split:** the app engine connects as `castranova_app`
     (new env-driven URI); Alembic + prestart keep the `postgres` connection
     (DDL + role management). Compose dev env switches the backend to the app
     role so the entire test suite proves least-privilege *before* prod; 5.4
     reuses the role as-is.
   - **pytest teardown:** conftest gains an explicit admin engine for its
     `TRUNCATE CASCADE` teardown (the app role rightly cannot TRUNCATE).

## 5. PR 3 — Test-infra hardening

- **Per-run E2E DB reset** via Playwright **project dependencies** (the
  documented-recommended pattern over `globalSetup`): new `setup db` project
  (`global.setup.ts`) truncates app tables and re-runs prestart seeding
  (shelling out to the compose stack; host-coupled is acceptable and documented
  for this local-only suite). The existing auth `setup` project gains
  `dependencies: ['setup db']` so login always sees a fresh superuser. Retires
  three memory-note pitfalls at once: pytest-wiped superusers, test-user
  accumulation, LIMIT-100 overflow (also fixed at the root by PR 1).
- **Escape hatch:** `E2E_SKIP_DB_RESET=1` skips the reset for quick iteration.
- **admin.spec fix:** "Edit user" scopes its assertion to the searched/filtered
  row instead of page-wide visibility (the documented pollution flake).

## 6. DoD verification sweep (after PR 3)

| DoD item | Verification |
|---|---|
| Coverage ≥ 80% on `crud.py` + route handlers | `pytest --cov`; gaps get targeted tests |
| Append-only at DB level | New pytest: UPDATE/DELETE/TRUNCATE on the 5 ledgers **as `castranova_app`** → denied |
| Staff cannot see financial fields | Raw-HTTP redaction tests swept across every staff-reachable endpoint incl. the new FR-015 staff schema |
| FIFO concurrency suite | Re-run green |
| Tooling | `uv run ruff check .` + `uv run mypy app` + biome clean; `alembic autogenerate` empty-diff probe (drift guard after the new migrations) |
| E2E | Full suite green on the new reset infra |

Findings loop back as fixes; the sweep certifies the final stack, not
intermediate snapshots.

## 7. Execution model (ECC subagents, per CLAUDE.md)

Each PR: `superpowers:writing-plans` → `superpowers:subagent-driven-development`
with TDD per task. Build tasks consult `ecc:fastapi-patterns`,
`ecc:postgres-patterns`, `ecc:database-migrations`. PRs 2–3 touch ledgers and
role-tiering → **high-risk**: review stage dispatches `ecc:database-reviewer` +
`ecc:security-reviewer` on top of `superpowers:requesting-code-review`. Ship via
`create-pr`, one PR per workstream, sequenced PR 1 → PR 2 → PR 3 → DoD sweep.

## 8. Spec/PRD accordance summary

- **Closes spec gaps:** §4.6/§6.9 app-role REVOKE (D4); §10 M015/M016
  service-ticket FKs; §6.5 + Flow F FR-015 staff cost redaction; §6.2
  auth-endpoint rate limits; §6.2 refresh expiry 7d.
- **Consistent/additive:** ORDER BY + bounded pagination; sanitized
  IntegrityError 409 (domain 409s preserved per PRD §10); `submitted_by_user_id`
  (§6.9 principle); pricing/sync rate limits; YGN_STAFF default (M001 concerns
  the first-superuser seed only); shared-team access (= spec §8's role-level
  model, PRD §5's unified team).
- **Recorded refinement:** §6.6 replay returns 200 for same-user replays;
  409 only on same-key/different-user collisions (this section is the
  addendum of record).
