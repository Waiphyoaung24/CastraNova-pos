# Full Code Review — CastraNova-POS

**Date:** 2026-07-18
**Updated:** 2026-07-19 (morning) — all findings re-verified against `dev_wth` HEAD `3364fb6`.
**Updated again:** 2026-07-19 (evening) — re-verified against two new commits (`be4b3f2`, `8bde703`) plus the uncommitted working tree.
**Updated again:** 2026-07-23 — H-8 implemented on branch `feat/telegram-connect-hardening` (not yet merged to `dev_wth`); see §0 and the H-8 entry in §2 for status.
**Scope:** Entire project, working tree on `dev_wth`. The Telegram work that was uncommitted at review time is now committed (`a8d564c`…`225c57c`), plus the product active-filter and mobile bottom-sheet UI work.
**Method:** Seven parallel specialist review passes — FastAPI, Python, PostgreSQL/schema, security, React, TypeScript, and a PRD v3.0 gap analysis (`docs/client/2026-06-02-castranova-pos-v3.0-prd.md`). Static review only; no tests were run and no DB was touched. Findings below are deduplicated and ranked.

---

## 0. Status update — 2026-07-19 (evening)

Since the morning pass, two migrations landed on `dev_wth` and a logging/comment cleanup is sitting uncommitted in the working tree. Summary of what moved today:

| Change | Items |
|---|---|
| ✅ **Resolved — committed** | **C-3** (`be4b3f2`, m032 — ledger FK indexes), **H-2 + H-3** (`8bde703`, m033 — report-range + remaining FK indexes), **H-4** (`73a4181` + `5287d3a` — server-filtered/paginated stock dashboard) |
| ✅ **Resolved — uncommitted working tree** | **C-2 + M-7** (`backend/app/core/logging.py` — centralized `configure_logging()`, httpx logger silenced, Sentry `before_send`/`before_breadcrumb` scrub hooks; regression test added) |
| 🟢 **Comment cleanup — uncommitted, no behavior change** | H-7's 6 duplicated 5-line comments (`customers.tsx`, `SupplierCreateDialog.tsx`, `SupplierEditDialog.tsx`, `ProjectCreateDialog.tsx`, `ProjectEditDialog.tsx`) replaced with one-line pointers to a single canonical explanation now in `EntityCombobox.tsx`, which itself grew a corrected, more precise version of the comment (attributes the cause to `react-remove-scroll`'s shard-based containment, not a "focus trap fighting" the popover) |
| 🟡 **Implemented on a branch, not yet merged (2026-07-23)** | **H-8** (`feat/telegram-connect-hardening`, commits `03c017a`..`25b34d6`) — negative-offset `getUpdates` fix, TTL cache, per-user rate limits, connect-code reaping, frontend 429 handling. All 5 tasks passed individual + whole-branch review (general + `ecc:database-reviewer` + `ecc:security-reviewer`, all clean). Three items outstanding before this is fully production-ready: a manual Telegram-side pre-flight (does a negative offset confirm updates?), a manual browser check of the new 429 message, and applying the branch's new migration (m034, DELETE grant) to the real dev DB. See the H-8 entry below. |
| ⚪ **Still open, unchanged since morning** | H-1, H-5, H-6, M-1…M-6, M-8, M-9, M-11…M-15, L-1…L-13 |

**Also:** Alembic head is now **`e5f6a7b8c9d0` (m033)** — m032 added `(actor_user_id, occurred_at DESC)` + partial `sale_id`/`stock_adjustment_id` indexes on both `unitmovement` and `partmovement` (closing C-3); m033 added `sale.sold_at`, partial `serviceticket.closed_at`, partial `projectpull.fulfilled_at` (closing H-2), plus `saleline.unit_id`/`product_id` and `serviceticketpart.product_id` FK-hygiene indexes (closing H-3 — the migration's own message is explicit that these are FK hygiene, not report-query wins, since `saleline.product_id` is only ever grouped via `COALESCE(saleline.product_id, unit.product_id)`, which a plain index can't serve). Both migrations declare the indexes in `models.py.__table_args__` too, since the test suite builds its schema from SQLModel metadata rather than Alembic — the drift risk called out in m033's message. `CLAUDE.md` still claims head is `m027`; that line is now off by three migrations (m031→m033) and should be corrected.

**Telegram enrollment** (shipped 2026-07-19 morning, unchanged today) — this partially closes the FR-004/FR-018 enrollment gap (see §6). It is **Telegram-only**; LINE and Viber IDs are still written by nothing.

**Working tree note:** the C-2/M-7 fix and the H-7 comment cleanup are real, verified code (test added for C-2; H-7 is comment-only) but are **not yet committed**. Get them into a commit before they're at risk of being lost or excluded from the next PR.

---

## 1. Critical

### C-1 · Live Telegram bot token in a git-tracked `.env` — ✅ RESOLVED 2026-07-19
`.env:50` — `TELEGRAM_BOT_TOKEN=8942...` was added to `.env`, which **was still tracked by git**. The `.gitignore` edit alone would not have untracked an already-indexed file.

- **Fixed by `3254002` ("chore(security): stop tracking .env, add .env.example templates").** `git ls-files .env` now returns nothing and `.gitignore:19` carries `.env`. `.env.example` templates were added in its place.
- **Still outstanding:** rotate the bot token via @BotFather anyway — it existed in a working tree and in this review document. Rotation is not verifiable from the repo, so confirm it was done.

### C-2 · httpx INFO logging leaks the Telegram token into logs/Sentry — ✅ RESOLVED 2026-07-19 (uncommitted)
*Re-verified 2026-07-19 evening.* Fixed by a new `backend/app/core/logging.py`: `configure_logging()` calls `logging.getLogger("httpx").setLevel(logging.WARNING)` and is now invoked from `main.py`, `backend_pre_start.py`, `initial_data.py`, and `tests_pre_start.py` (replacing the four scattered `logging.basicConfig(level=INFO)` import-side-effects — see M-7, closed by the same change). Sentry's `sentry_sdk.init` (`main.py`) now also passes `before_send=scrub_telegram_token_from_event` and `before_breadcrumb=scrub_telegram_token_from_breadcrumb`, a shape-based regex redaction (`_TELEGRAM_TOKEN_RE`) that scrubs any `api.telegram.org/bot<token>` URL found anywhere in an event or breadcrumb — belt-and-suspenders in case some other path ever logs the URL. A regression test (`backend/tests/services/test_notify.py::test_configure_logging_suppresses_telegram_token_in_httpx_log`) drives a real `httpx.Client.send` through a `MockTransport` so httpx's actual log line fires, then asserts via `caplog` (root level, all records) that the token never appears — exactly the test shape this doc originally recommended.

- **Not yet committed** — verified correct in the working tree, but get it into a commit; it's real security-fix code sitting unprotected.

### C-3 · No indexes on `sale_id` / `actor_user_id` on either append-only ledger — ✅ RESOLVED 2026-07-19 (`be4b3f2`, m032)
*Re-verified 2026-07-19 evening.* Migration `d4e5f6a7b8c9_m032_ledger_fk_indexes.py` adds `(actor_user_id, occurred_at DESC)` composite indexes and partial `sale_id`/`stock_adjustment_id` indexes (mirroring the existing `project_pull_id`/`service_ticket_id` partial-index pattern) to both `UnitMovement.__table_args__` and `PartMovement.__table_args__` in `models.py`, plus the Alembic migration itself — declared in both places since the test suite builds its schema from SQLModel metadata rather than Alembic.

- **Impact addressed:** `list_audit`/`count_audit`'s `WHERE actor_user_id = :x ORDER BY occurred_at DESC LIMIT n` and `margin_report`'s `*.sale_id → sale.id` joins are now index-served instead of sequential-scanning tables that grow on every sale/receive/adjustment.

---

## 2. High

### H-1 · `FIRST_SUPERUSER_PASSWORD` default exempt from the production guard — ⚪ unchanged (now annotated)
*Re-verified 2026-07-19: behavior unchanged; `config.py:154-157` now carries an explicit comment documenting the exemption as an owner-approved trade-off. The guard covers `SECRET_KEY`, `POSTGRES_PASSWORD`, `POSTGRES_APP_PASSWORD` only.*

`backend/app/core/config.py:150-163` — `_enforce_non_default_secrets` hard-fails non-local deploys on default `SECRET_KEY`/`POSTGRES_PASSWORD` but deliberately exempts `FIRST_SUPERUSER_PASSWORD` (documented owner decision). A deploy that forgets to override it ships `admin@example.com` / `changethis` as a live superuser with **no warning at all**. Flagged independently by both the security and FastAPI reviews.

- **Fix (minimum, preserving the owner's trade-off):** loud startup warning when default in non-local env; better: force password change on first login, or gate the exemption behind a second explicit env flag.

### H-2 · Missing date indexes on the exact columns the margin report range-filters — ✅ RESOLVED 2026-07-19 (`8bde703`, m033)
*Re-verified 2026-07-19 evening.* Migration `e5f6a7b8c9d0_m033_report_range_and_fk_indexes.py` adds a plain `ix_sale_sold_at` (NOT NULL column — every row qualifies), a partial `ix_serviceticket_closed_at WHERE closed_at IS NOT NULL` (open tickets have `closed_at IS NULL` and can never satisfy a `>= start` range filter, so excluding them keeps the index small), and a partial `ix_projectpull_fulfilled_at WHERE fulfilled_at IS NOT NULL` (same reasoning — the existing `ix_project_pull_state_created` doesn't serve these queries, which filter on neither `state` nor `created_at`). All three land in both `models.py.__table_args__` and the migration, verified via an autogenerate run that produced an empty migration (i.e. the two surfaces now agree).

### H-3 · More missing FK indexes: `serviceticketpart.product_id`, `saleline.unit_id`/`product_id` — ✅ RESOLVED 2026-07-19 (`8bde703`, m033, same migration as H-2)
*Re-verified 2026-07-19 evening.* The same m033 migration adds `serviceticketpart.product_id`, `saleline.unit_id`, and `saleline.product_id` indexes. The commit message is explicit that these are **FK/parent-delete hygiene, not the report-query win** the original finding assumed: `saleline.product_id` is only ever grouped via `COALESCE(saleline.product_id, unit.product_id)`, which a plain column index can't serve, and `saleline.unit_id` joins to `unit.id` (the primary-key side, already indexed by the PK). They're added anyway because Postgres scans child tables on parent-row delete, and for consistency with m032's FK-indexing pass.

### H-4 · Stock-on-hand is unbounded end-to-end — ✅ RESOLVED 2026-07-20 (`73a4181` + `5287d3a`)
- Backend now accepts bounded `skip`/`limit` plus `q`, `brand`, `category`, and admin-only `supplier`; the response carries a filtered `count`. The same clauses drive count and rows, and the correlated quantity projections run only for the returned page.
- Supplier filtering now uses a tracking-aware `EXISTS` row predicate while retaining supplier-scoped quantities, so unrelated products no longer form a wall of zero rows. The API rejects supplier filters from staff.
- Frontend filtering is fully server-side and debounced, uses the shared 25-row pagination controls, resets to page one on filter changes, and drops the superseded customer filter. The client-only stock filter module and its unit test were removed. Focused Playwright coverage pins supplier narrowing/scoped labeling and the 25→page-2 boundary.
- Batch/unit drills remain lazy. Administrators now see supplier provenance in the drill; staff receive `supplier: null`. Costs remain absent from the shared drill contract.

### H-5 · CRUD getters typed `Any` instead of `uuid.UUID` — ⚪ unchanged (11 sites, re-counted)
*Re-verified 2026-07-19.* `backend/app/crud.py` — `get_supplier` (:307), `get_customer` (:387), `get_project` (:482), `get_product` (:582), `list_price_history` (:755), `get_unit` (:768), `get_pricing_override` (:1291), `get_sale` (:2264), plus `sale_id: Any` (:2304), `ticket_id: Any` (:2640), `pull_id: Any` (:2839). Each takes `<entity>_id: Any`, silently disabling mypy-strict checking on these entry points, inconsistent with the rest of the module. (`get_setting`/`set_setting`'s `value: Any` at :241/:252 are legitimate JSONB payloads — leave them.)

- **Fix:** change to `uuid.UUID`.

### H-6 · `as any` cast in the shared frontend error extractor — ⚪ unchanged
`frontend/src/utils.ts:9-13` — `(err.body as any)?.detail`, then `:11 return errDetail[0].msg` with no check that element 0 is an object carrying `msg`. A non-JSON error body (e.g. proxy HTML page) throws **inside** `extractErrorMessage`, crashing the "always show a toast, never crash" path. *Additionally noted 2026-07-19:* `:13` returns `errDetail` unnarrowed (inferred `string` off the `any`), so an object-shaped `detail` renders as `[object Object]`. The `sale.tsx:165` code casts more safely — consolidate on that style.

- **Fix:** treat body as `unknown`; narrow with `typeof === "string"` / `Array.isArray` before indexing.

### H-7 · `modal={false}` strips the focus trap from entire dialogs — 🟢 investigated 2026-07-19; kept as a verified, documented trade-off
Radix `modal={false}` disables focus trapping, `aria-modal`, and background inertness for the **whole** dialog. Keyboard and screen-reader users can Tab out of an open modal into background controls. Occurrences (unchanged, 6 sites):

- `frontend/src/routes/_layout/customers.tsx:197`, `:274`
- `frontend/src/components/suppliers/SupplierCreateDialog.tsx:63`, `SupplierEditDialog.tsx:69`
- `frontend/src/components/projects/ProjectCreateDialog.tsx:74`, `ProjectEditDialog.tsx:91` (added 2026-07-19 by `00c1101`)

**Investigated end-to-end this session** — the original comment's claim ("a modal Dialog's focus trap fights the popover for focus") was verified empirically to be *functionally true*, though the precise Radix mechanism is more subtle than the comment stated:

- Live DevTools test on `ProjectCreateDialog`: with `modal={false}` removed (dialog modal, the default), clicking the combobox trigger opens the popover but **focus never reaches the search input** — it stays on the trigger button. With `modal={false}` restored, focus correctly lands in the search box. Reproduced twice, not flaky.
- Reading `@radix-ui/react-focus-scope`'s source shows the `FocusScope` stack-pausing mechanism (which I initially thought disproved the comment) is *not* the actual blocker — it behaves correctly in isolation, same as it does for `Select` inside a modal Dialog. The real blocker is almost certainly `react-remove-scroll`'s shard-based containment (`react-dialog` wraps the modal in `RemoveScroll` with `shards: [context.contentRef]` — only the dialog's own content node is exempt from the scroll/focus lock; a Popover portalled to `document.body` is neither inside the lock nor a shard).
- **Attempted fix:** portal the Popover *inside* the Dialog's content node instead of `document.body` (new `PortalContainerProvider` context, `DialogContent` provides its content ref, `PopoverContent` consumes it). Typechecked clean, verified live: focus now reaches the search input correctly. **But it broke positioning outright** — `DialogContent`'s centering (`translate-x-[-50%] translate-y-[-50%]`) makes it a CSS containing block for `position: fixed` descendants, and Radix Popper's positioning strategy is hardcoded to `"fixed"` (not configurable via props). The popover rendered with `position: static` and a phantom width (462px, matching the dialog's width, not the 224px trigger) — not just misplaced, position failed to compute at all.
- **Reverted.** No fix exists without either rewriting `DialogContent`'s centering (removes the transform, touches every dialog in the app) or Radix Popper exposing a positioning-strategy override (it doesn't). Both are out of scope for this finding.

**Disposition:** `modal={false}` is kept as a necessary, now-precisely-documented trade-off, not an oversight. The 6 duplicated 5-line comments (each blaming "the dialog's focus trap" without detail) were replaced with a one-line pointer to a single, verified explanation added in `EntityCombobox.tsx` near the `Popover` return, so the real cause and the two things already tried live in one place. No behavior change — comment consolidation only, confirmed via `tsc --noEmit` and a full manual + Playwright pass (`project-customer-combobox`, `combobox-scroll`, `supplier-edit-flow` all green; `project-edit-flow` fails identically on unmodified `HEAD`, a pre-existing test bug — it never clicks "New customer" before filling the Name field — unrelated to this change).

**Update 2026-07-19 evening:** this consolidation is now sitting in the working tree (`customers.tsx`, `SupplierCreateDialog.tsx`, `SupplierEditDialog.tsx`, `ProjectCreateDialog.tsx`, `ProjectEditDialog.tsx`, `EntityCombobox.tsx`) but is **not yet committed**. The canonical comment in `EntityCombobox.tsx` was also sharpened over the version described above — it now names `react-remove-scroll`'s shard-based containment as the specific mechanism (matching §H-7's own root-cause finding) rather than the vaguer "focus trap fighting the popover" framing the six duplicated comments used.

- **Remaining option, not taken:** build a small custom Tab-key focus-containment hook for these 6 dialogs specifically (manual `aria-modal` + keydown trap) instead of relying on Radix's built-in one, to close the actual keyboard/AT gap without touching shared Dialog/Popover styling. Deferred — larger surface, needs its own verification that it doesn't refight the popover the way Radix's own trap does.

### H-8 · Telegram `connect`/`confirm` are unrate-limited outbound-API amplifiers — 🟡 IMPLEMENTED 2026-07-23 on branch `feat/telegram-connect-hardening`, not yet merged
`backend/app/api/routes/notifications.py:49` (`POST /telegram/connect`) and `:66` (`POST /telegram/confirm`) originally carried **no rate limit**. Only `POST /telegram/test` did (`backend/app/core/limiter.py:22`, `TELEGRAM_TEST_RATE_LIMIT = "10/hour"`).

**Status 2026-07-20 → 2026-07-23:** brainstormed → spec → implementation plan → all 5 tasks implemented via `subagent-driven-development` on an isolated worktree/branch. Every task passed an individual spec+quality review; the whole branch then passed three parallel final reviews (general code review, `ecc:database-reviewer`, `ecc:security-reviewer`), all clean, no Critical/Important findings. Commits `03c017a`..`25b34d6` on `feat/telegram-connect-hardening` (branched from `dev_wth`).
- **Spec:** `docs/superpowers/specs/2026-07-20-telegram-connect-hardening-design.md` (`95b29cf`)
- **Plan:** `docs/superpowers/plans/2026-07-20-telegram-connect-hardening.md` (`b644e38`) — 5 TDD tasks, 42 steps, all executed

**What shipped, part by part:**
- **Part 0 (negative `getUpdates` offset):** `get_telegram_updates` now sends `{"offset": -100}` instead of `{}`, reading the newest 100 updates instead of the oldest. Fixes the separate, arguably-worse defect found during the original investigation: since this module never confirms updates, a backlog of >100 unconfirmed updates previously pushed a fresh `/start` outside the returned window, silently failing connect until the backlog aged out at 24h.
- **Part 1 (TTL cache):** `get_telegram_updates_cached()` collapses concurrent `/confirm` pollers into one outbound call per 3s (one client poll interval), since `getUpdates` returns the bot's whole shared queue — byte-identical for every caller. This, not the rate limit, is what actually bounds outbound Telegram traffic (worst case ~80 outbound calls/min shop-wide across 4 workers, independent of request volume).
- **Part 2 (per-user rate limits):** `20/hour` on `connect`, `60/minute` on `confirm`, keyed on the authenticated user (not IP) via a custom slowapi `key_func` reading a value a new FastAPI dependency stashes on `request.state`. This closes the IP-collapsing weakness noted below (co-located staff no longer share one bucket).
- **Part 3 (delete-on-mint reaping):** minting a new connect code now deletes the caller's prior codes first, bounding `telegramconnectcode` at ~1 row/user without a scheduler.
- **Part 4 (client poll-stop):** `TelegramConnectCard.tsx` now stops polling and shows a clear message on a 429, instead of spinning silently to its existing 2-minute timeout — closes the failure mode Part 2 introduced.

**The two assumptions the plan flagged as unresolved — now settled:**
1. *"A negative offset does not confirm updates."* **Still unresolved** — the Task 1 Step 8 manual `curl` pre-flight against a real bot token was not run (no bot token access in the implementation environment). This must be run before Part 0 is fully trusted; if it turns out negative offsets DO confirm updates, Part 0 should be reverted per the plan's documented fallback (keep `json={}}`, document the 100-update ceiling as a known limitation).
2. *slowapi resolves route dependencies before `key_func` runs.* **Resolved, verified true.** `test_one_users_limit_does_not_block_another_user` passed on the first run — both the implementer and the whole-branch reviewer independently confirmed the test genuinely forces two users through the same simulated client IP, ruling out a false pass. The JWT-decode fallback was not needed.

**An unplanned addition, found necessary during implementation:** Part 3's `session.delete()` call, run against the real least-privilege `castranova_app` DB role (established in m026), fails `InsufficientPrivilege` — `telegramconnectcode` was created (m030) after m026's `DEFAULT PRIVILEGES` were set, and never received a `DELETE` grant the way `"user"` did. A new migration, `f1a2b3c4d5e6` ("m034"), grants `DELETE ON telegramconnectcode TO castranova_app`, mirroring m026's existing pattern exactly. Independently verified by both the per-task reviewer and the dedicated `ecc:database-reviewer` pass as necessary, minimal, and correctly written (injection-safe role interpolation, symmetric downgrade, correct revision chain onto m033). **Not yet applied to the real dev database** — `alembic upgrade head` must be run there (and staging/prod) before Part 3 works outside the isolated test DB it was built against.

**Owner decisions recorded during design, still honored:** kept the `/confirm` limit and the custom `key_func` (defense-in-depth + reusable infra) despite a marginal cost/benefit read; reaping is delete-on-mint, not a scheduled sweep.

**Still true, not changed by this work:** slowapi's buckets are **per-process** and `backend/Dockerfile:45` runs `--workers 4`, so the stated rate limits are ceilings up to 4× looser in practice. The security review confirmed this doesn't undermine the fix's actual goal (bounding outbound Telegram traffic), since the TTL cache — not the rate limit — is what does that job, and the cache is equally per-process (same 4× ceiling, but a hard one). Making the limits exact needs Redis, which the stack doesn't run — still out of scope, still worth its own decision if it ever matters.

- **Remaining before this is fully production-ready:**
  1. Run the Task 1 Step 8 manual Telegram curl pre-flight (assumption #1 above).
  2. Run the Task 5 Step 5 manual browser verification of the new 429 message (not performed — no interactive browser access during implementation).
  3. Merge the branch, then run `alembic upgrade head` against dev/staging/prod to apply m034.
  4. One Low/informational item from the security review, optional: `TelegramConfirmRequest.code` (`models.py:1783-1784`) has no `max_length`, unlike its DB column (32). Not exploitable (exact-match lookup, already rate-limited) — fix opportunistically if touching that model again.

---

## 3. Medium

### Security / deployment

- **M-1 · Spoofable `X-Forwarded-For` defeats login rate limiting.** `compose.yml:115-122` sets `FORWARDED_ALLOW_IPS=*` (known residual risk per inline comment) and `compose.dokploy.yml:55-56` publishes backend port `8099` directly to the host, bypassing Traefik. An attacker hitting `:8099` with a rotating `X-Forwarded-For` gets an unlimited effective login rate limit (`backend/app/core/limiter.py` keys on `get_remote_address`). **Fix:** restrict `FORWARDED_ALLOW_IPS` to the proxy subnet and/or drop the direct host port publish.

### Backend

- **M-2 · Routes bypass `crud.py`.** ⚪ unchanged. `backend/app/api/routes/sales.py:25` (`_to_public` runs `session.exec(select(SaleLine)...)` inline; `select` imported at `:4` — the only such call in that file) and six spots in `users.py` (:116-118, :138-139, :160-161, :172, :200, :240, :247-248 — inherited from the upstream template). Violates the project's own "all DB access through crud.py" convention; risks drift. **Fix:** thin `crud.*` wrappers.
- **M-3 · Customer dashboard transaction history unbounded.** ⚪ unchanged, now `backend/app/crud.py:4081-4109` (`_customer_transactions`) — three unbounded `select(...).all()` over Sale/ServiceTicket/ProjectPull, then an in-Python sort with no limit. High-volume dealer customers degrade `GET /customers/{id}/dashboard` over time. **Fix:** cap to most recent N (mirror `_CONSUMPTION_LIMIT = 200`) or paginate.
- **M-4 · `list_low_stock` N+1.** ⚪ unchanged, now `backend/app/crud.py:1144-1166` — loads all thresholded products, then calls `_on_hand()` (`:1125-1141`, one or two queries each) per product inside the loop. **Fix:** single set-based query copying `stock_on_hand`'s correlated-subquery shape.
- **M-5 · Audit deep pagination is OFFSET-shaped.** ⚪ unchanged. `backend/app/crud.py:3983-4080` fetches and merge-sorts `skip + limit` rows from both ledgers per page — page 500 at limit 100 pulls ~50k rows per ledger. **Fix (only if deep paging matters):** keyset pagination on `(occurred_at, id)`.
- **M-6 · Leading-wildcard `ILIKE '%term%'` catalog search with no trigram index.** `crud.py:277-284` + `_supplier_where`/`_product_filter_clauses` — every catalog search is a seq scan. **Fix if catalog grows past a few thousand rows:** `pg_trgm` + GIN indexes on `product.sku/model_name/brand/category`, `supplier.name`, `customer.name`; otherwise accept.
- **M-7 · ~~`logging.basicConfig(level=INFO)` as import side effect.~~** ✅ **RESOLVED 2026-07-19 (uncommitted, same change as C-2).** The four scattered `logging.basicConfig(level=INFO)` calls (`utils.py`, `main.py`, `backend_pre_start.py`, `initial_data.py`, `tests_pre_start.py`) are replaced by a single `configure_logging()` in `backend/app/core/logging.py`, called once from each entrypoint.
- **M-8 · `assert` guard stripped under `-O`.** `backend/app/utils.py:39` — `assert settings.emails_enabled` disappears with `PYTHONOPTIMIZE`, letting `send_email` proceed unconfigured. **Fix:** explicit `if not ...: raise RuntimeError(...)`.
- **M-9 · `GET /sync-review` returns a bare list with no `count`.** 🟡 half fixed. `backend/app/api/routes/sync_review.py:40-56` now has validated `skip` (ge=0, le=10_000) and `limit` (ge=1, le=500) — the unbounded-pagination half is resolved. Still `response_model=list[SyncReviewItemPublic]` with no `{data, count}` envelope, inconsistent with every other paginated admin list. **Fix:** wrap in `{data, count}` schema + `crud.count_sync_review_items`.

### Frontend

- **M-10 · ~~Notifications page: one shared mutation disables every checkbox; no optimistic update.~~** 🟢 **CLOSED 2026-07-19 — no longer applies.** The page was rebuilt (`c1c59e9`, `de71192`, `025143f`, `33cef51`) into an event-rows × channel-columns grid with **batched save**. Checkbox clicks now mutate local state only (`notifications.tsx:81` `pending: Map`, `:103-116` `toggle`), so there is no per-click round-trip and nothing to optimistically update. The shared `saveMutation` (`:83`) still disables all checkboxes while saving (`:130`, `:141`), but that is now *correct* — one batch PATCH genuinely covers all of them. Save is gated on `isDirty` (`:245`).
- **M-11 · `useIsMobile` starts `undefined`, causing a Popover→Sheet remount on first mobile paint.** 🔴 unchanged in the hook, **higher impact now**. `frontend/src/hooks/useMobile.ts:6` is still `useState<boolean | undefined>(undefined)` with `:18 return !!isMobile`, so first paint is always "desktop" and flips after the effect. After `83859fb`, consumers swap entire component *trees* rather than classes: `EntityCombobox.tsx:64` (Popover `:206-223` vs Sheet `:225-241`), `ListFilters.tsx:36` (inline row `:39-45` vs Sheet `:47-78`), plus `stock.tsx:57`, `products.tsx:77`, `notifications.tsx:71` (card vs table). That is a real mount/unmount flash on mobile, not a cosmetic reflow. No SSR concern in this SPA. **Fix:** seed state synchronously from `window.matchMedia(...).matches`.
- **M-12 · `humanize()` duplicated three times.** ⚪ unchanged. `frontend/src/lib/labels.ts:11` (module-private — which is *why* the others exist), `notifications.tsx:34`, `components/audit/AuditDetailSheet.tsx:70` (`humanizeEvent`). All three byte-equivalent. **Fix:** export from `labels.ts`, import at both call sites.
- **M-13 · Two divergent error-detail parsers.** 🔴 worsened by `b368121`. `frontend/src/routes/_layout/sale.tsx:161-172` replaced `handleError.bind(...)` with a hand-rolled parser casting `(err.body as { detail?: unknown })`, alongside `utils.ts:4-14` casting `as any` — **two shapes, two different casts** (the local one is safer). It also widened `useCustomToast.showErrorToast` to accept an optional title (`hooks/useCustomToast.ts:10-17`, default unchanged). Worse, the special case matches on `detail.startsWith("Insufficient stock")` — any backend rewording silently reverts the toast to generic, with no test catching it. `receive.tsx:172,490` still use the shared path. **Fix:** one shared typed helper (combine with H-6); key the special case on status + a stable error code, not prose.
- **M-14 · ➕ NEW · `ListFilters` mobile trigger is not a `SheetTrigger`.** `frontend/src/components/Common/ListFilters.tsx:49-59` renders a plain `Button` with `onClick={() => setOpen(true)}` as a direct child of `<Sheet>` instead of wrapping it in `SheetTrigger asChild`. Radix therefore holds no trigger reference and **cannot restore focus to the Filters button when the sheet closes** — keyboard users land back at the top of the document. `EntityCombobox.tsx:209` does it correctly, so the fix is a one-line copy of the sibling pattern. Genuine a11y regression introduced by `83859fb`.
- **M-15 · ➕ NEW · `TelegramConnectCard` fails silently when the confirm poll errors.** `frontend/src/components/notifications/TelegramConnectCard.tsx:45-53` — `confirmQuery` refetches every 3s while `activeCode !== null`, but both stop conditions (`:58-71` on `data.connected`, `:77-83` on `data.error`) key off **successful** responses. On a 5xx or dropped network the user sees a spinner with no error until the 2-minute give-up timer (`:87-101`) fires. The timer does hold (it depends only on `pollStartedAt`), so this is bounded, not a runaway — but it is two minutes of unexplained waiting on a flaky warehouse connection. **Fix:** surface `confirmQuery.isError` in the card, or stop polling after N consecutive failures.

---

## 4. Low / Advisory

- **L-1 · Password-reset JWT lacks a `type` claim.** `backend/app/utils.py:103-123` — any leaked access/refresh token doubles as a reset token, widening a 15-min token leak into persistent takeover. **Fix:** add/require `"type": "reset"`, mirroring the access/refresh discipline in `security.py`/`deps.py`.
- **L-2 · Access token in `localStorage`.** `frontend/src/lib/auth-session.ts:4,44` etc. — XSS-exposed by design (no active XSS sink found; refresh token is correctly httpOnly). Defense-in-depth note only, but compounds L-1.
- **L-3 · `TOKEN_KEY` literal duplicated.** ⚪ unchanged — and it is **5 raw copies**, not 2. `frontend/src/lib/auth-session.ts:4` defines it module-privately; the literal `"access_token"` is re-typed at `lib/print-pdf.ts:25`, `lib/report-download.ts:12`, `main.tsx:30`, `hooks/useAuth.ts:16` and `:33`. Renaming the key silently breaks PDF/report downloads. **Fix:** export and import `TOKEN_KEY`.
- **L-4 · Unchecked `Map.get` casts.** 🟡 partially fixed. `frontend/src/routes/_layout/products.tsx:291-293` and `:361-363` now read `costByProductId.has(p.id) ? formatThb(costByProductId.get(p.id) as string) : "—"` — the `as string` can no longer be `undefined` at runtime, so this is now a TS-ergonomics wart rather than a "฿NaN" bug. **Still open:** `costByProductId` is rebuilt on every render (`:141-146`, no `useMemo`). Client-side filtering is gone entirely — the page paginates server-side now (`:111-121`).
- **L-5 · Float summation of THB cart subtotal (display-only).** `frontend/src/lib/sale-cart.ts:132-134` — backend is authoritative (documented); just ensure every render site formats through a 2-decimal formatter (currently true).
- **L-6 · `DEFAULT_OVERRIDE_THRESHOLD_PCT = 5.0` as float.** `backend/app/crud.py:227` — safe via `Decimal(str(...))` at the read site, but inconsistent with the module's `Decimal("...")` literals. **Fix:** declare as `Decimal("5.0")`.
- **L-7 · Engine has no pool/timeout config.** `backend/app/core/db.py:7` — SQLAlchemy defaults (pool 5 + overflow 10, no `statement_timeout`); a stuck `FOR UPDATE` wait can hang a connection indefinitely under burst load. **Fix when load-testing:** explicit pool sizing + `statement_timeout`.
- **L-8 · Random UUIDv4 PKs on insert-heavy ledgers.** B-tree bloat/page-split cost vs UUIDv7 — advisory only; the domain genuinely needs offline-mintable non-guessable IDs. Conscious trade-off, now documented.
- **L-9 · Missing `DialogDescription`/`aria-describedby`.** ⚪ unchanged, and the pattern is now clear: **edit/delete dialogs have one, create dialogs don't.** Missing at `products.tsx:430` (PriceHistoryDialog), `customers.tsx:209`, `:279`, `products/ProductCreateDialog.tsx:108`, `pos/CustomerCreateDialog.tsx:93`, `suppliers/SupplierCreateDialog.tsx:75`, `projects/ProjectCreateDialog.tsx:86`. Present at `Admin/AddUser.tsx:110`, `Admin/EditUser.tsx:126`, `Admin/DeleteUser.tsx:68`, `UserSettings/DeleteConfirmation.tsx:54`, `products/EditProductDialog.tsx:142`, `suppliers/SupplierEditDialog.tsx:77`, `projects/ProjectEditDialog.tsx:99`. Radix dev warning; screen-reader context follow-up. Compounds H-7 — those dialogs still lack both the trap (a verified, necessary trade-off — see §H-7) and the description (no such constraint; worth adding).
- **L-10 · `handleError.call(showErrorToast, err)` binding style.** ⚪ unchanged; **both** styles are live. `frontend/src/utils.ts:16-22` still uses `this`-binding: `.bind(showErrorToast)` at 11 sites (`useAuth.ts:44`, `Admin/AddUser.tsx:89`, `Admin/EditUser.tsx:93`, `Admin/DeleteUser.tsx:44`, `UserSettings/ChangePassword.tsx:61`, `UserSettings/DeleteConfirmation.tsx:33`, `UserSettings/UserInformation.tsx:58`, `reset-password.tsx:92`, `recover-password.tsx:72`, `EditProductDialog.tsx:125`, `tickets.tsx:168`), `.call(showErrorToast, err)` at 3 (`receive.tsx:172`, `:490`, `sale.tsx:172`). Functionally correct but fragile; prefer a plain higher-order function.
- **L-11 · ➕ NEW · `EntityCombobox`'s `useMemo`s never hit.** `frontend/src/components/Common/EntityCombobox.tsx:73-80` memoizes on `[items, debouncedQuery, getLabel]` and `:83-87` on `[items, value, getKey, getLabel]`, but every call site passes inline arrow functions (e.g. `stock.tsx:137-138`, `:156-157`), so `getLabel`/`getKey` get fresh identities each render and both memos recompute unconditionally. The debounce at `:70-71` still works; the memoization is decorative. **Fix:** `useCallback` at call sites, or drop the unstable deps.
- **L-12 · ➕ NEW · `useCustomToast` returns fresh closures every render, and a comment claims otherwise.** `frontend/src/hooks/useCustomToast.ts:3-19` has no `useCallback`, so `showSuccessToast`/`showErrorToast` are new identities each render. `TelegramConnectCard.tsx:69-70` carries a comment asserting `showSuccessToast` is "a stable helper" — that is **false**. It doesn't misfire today only because the effect early-returns on `!confirmQuery.data?.connected`, i.e. the guard is load-bearing and the stated reason for safety is wrong. Latent anywhere a toast helper lands in a dependency array. **Fix:** wrap the helpers in `useCallback`; correct the comment.
- **L-13 · ➕ NEW · Unsaved notification edits survive a background refetch.** `frontend/src/routes/_layout/notifications.tsx:81` — `pending` is cleared only in `onSuccess` (`:89`). If the underlying query refetches, stale dirty entries whose `rowKey` still resolves keep overriding server data in `effectiveEnabled` (`:99-101`), and `handleSave` (`:118-127`) would then PATCH a value derived from a view the user never saw. Low likelihood today (no `refetchInterval` on that query). Related: no unsaved-changes guard on navigation away. **Fix:** reconcile or drop `pending` on query-data change.

---

## 5. Performance improvements (consolidated)

*2026-07-20: items 1–3 are done (`be4b3f2`, `8bde703`, `73a4181`, `5287d3a`). Item 7's `products.tsx` half improved — see L-4. Everything else below is still open.*

1. ~~**Ledger indexes** — `(actor_user_id, occurred_at DESC)` + `sale_id` on `unitmovement`/`partmovement`.~~ ✅ done (C-3, `be4b3f2` m032).
2. ~~**Report date indexes** — `sale.sold_at`, `serviceticket.closed_at`, `projectpull.fulfilled_at`; `serviceticketpart.product_id`, `saleline.unit_id/product_id`.~~ ✅ done (H-2/H-3, `8bde703` m033).
3. ~~**Stock-on-hand pagination**, backend and frontend.~~ ✅ done (H-4, `73a4181` + `5287d3a`; pagination chosen over virtualization).
4. **Cap customer-dashboard transactions** (M-3); **set-based `list_low_stock`** (M-4).
5. **Keyset pagination for the audit ledger** if deep paging is real usage (M-5).
6. **`pg_trgm` GIN indexes** for catalog search at scale (M-6).
7. Frontend micro-items: memoize `costByProductId`, fix `useIsMobile` first-paint remount (M-11, L-4).
8. Engine pool sizing + `statement_timeout` (L-7).

Everything else measured as disciplined: all other list endpoints bounded (≤500) and batched (no N+1), FIFO locking is deadlock-ordered, frontend uses `staleTime`/debounce/`keepPreviousData`/server pagination correctly.

---

## 6. PRD v3.0 gap analysis

Status per feature (verified against code, not docs):

| FR | Feature | Status | Key gaps / deviations |
|---|---|---|---|
| FR-001 | Product catalog | ✅ Implemented | Catalog page admin-only in UI; staff reach products via option pickers only. |
| FR-002 | Pricing + FIFO cost | ✅ Implemented | Cross-batch cost split exact (`consume_quantity_fifo`). "Price on date D" needs walking history — no as-of endpoint; price-change `reason` optional. |
| FR-003 | Suppliers/customers/projects | ✅ (deviations) | Inline customer-create in sale works. But PRD says staff can *read* lists: `GET /projects/*` is admin-only, and the supplier/customer/project list pages are `requireAdmin`. |
| FR-004 | Roles & user mgmt | ⚠️ Partial (improved) | User add/edit/deactivate is **superuser-only**, not BKK admin (de-facto 3 tiers). **Telegram self-enrollment now ships** (see below) and populates `telegram_chat_id`/`telegram_username`. **LINE and Viber still have no enrollment flow** — `line_user_id`/`viber_user_id` are declared (`models.py:202-203`), mapped (`:218-219`) and dispatched (`services/notify.py:227-228`) but **written by no code path**. Telegram remains scope beyond PRD. |
| FR-005 | Serialized receiving | ✅ (deviation) | **Receiving is admin-only** (documented 2026-06-17 decision) — PRD says Yangon staff receive. Labels are QR, not 1D barcodes; no label-printer config setting. |
| FR-006 | Commodity receiving | ✅ (deviation) | Batch IDs exactly `YYYYMMDD-SKU-###`. Same admin-only deviation; manifest mismatch is a recorded note, not a blocking confirmation workflow. |
| FR-007 | Sale | ✅ Implemented | Customer required, oversell 409s, FIFO split, receipt PDF, offline queue + idempotency. Offline is deliberately **single-queued-sale** — thinner than the PRD's 8-hour outage narrative; confirm multi-sale-in-sequence works. |
| FR-008 | Service tickets | ⚠️ Partial | **No open/close lifecycle** — ticket is created already-closed in one atomic call; an in-progress ticket cannot exist. **Machine-swap Maintenance exit impossible** — tickets accept QUANTITY products only; nothing ever writes `UnitMovement(MAINTENANCE_OUT)` (state machine supports it, no code path uses it). |
| FR-009 | Project pulls | ✅ Implemented | Full lifecycle, short→notify, revenue=0, dual audit (creator + fulfiller). Also notifies on FULFILLED (matches FR-018's event list). |
| FR-010 | Pricing overrides | ✅ (nuance) | Override request waits for approval rather than a half-created sale — functionally equivalent. **Threshold configurable only via direct DB write** — no settings API/UI. |
| FR-011 | Stock adjustment | ✅ (gap) | Admin-only, mandatory reason, `-ADJ-` batches. **No adjustments-history list endpoint or screen** (PRD §8.7 promises one); visible only inside the audit ledger. |
| FR-012 | Stock-on-hand dashboard | ✅ (deviation) | Batch drill **omits `purchase_cost_thb` even for admins** (deliberate: shared both-roles endpoint) — PRD promises "at what cost". Admin can get cost via SKU search. Customer-history filtering was removed; supplier remains filterable for admins, and its selected quantity is explicitly supplier-scoped. |
| FR-013 | Channel margin report | ✅ Implemented | Screen + PDF + XLSX, drill by product/customer/project. No material gaps. |
| FR-014 | Holding period | ✅ Implemented | 90-day threshold configurable only via DB (same settings-UI gap). |
| FR-015 | Search & lookup | ✅ Implemented | Serial lifecycle + SKU batch/consumption with per-batch attribution; role-split schemas. No export (see FR-017). |
| FR-016 | Low-stock alerts | ✅ Implemented | Single + bulk (≤500) edit, crossing detection in FIFO consume, dashboard list. Alerts only fire on a fresh downward crossing during consumption; reach depends on the unbuilt enrollment flow. |
| FR-017 | Export everywhere | ❌ **Largest gap** — unchanged | Re-verified 2026-07-19: still exactly **3 of ~10 promised surfaces**. `backend/app/api/routes/reports.py` has three surfaces × {pdf, xlsx} — channel-margin (:97, :117), override-exceptions (:174, :186), holding-period (:234, :247). The only other PDF routes are single-document, not exports (`products.py:107` label.pdf, `sales.py:71` receipt.pdf). **No CSV routes anywhere.** Missing: stock-on-hand, search results, customer detail, project detail, audit log, low-stock list, adjustments history. `services/export.py` is generic — extension is cheap. |
| FR-018 | LINE + Viber notifications | ⚠️ Partial (improved) | Senders + retry + all 4 events + append-only `NotificationLog`. **Preference UI is now genuinely self-service and role-aware** — full event×channel grid with synthetic defaults so a fresh user sees every switch, `eligible_events()` (`models.py:231`) omits admin-only events for non-admins, per-cell `channel_connected` disables with a "Connect X to enable" tooltip, single batched PATCH (≤100 prefs, duplicate pairs rejected server-side). **Still missing: no admin review surface for permanent failures** — `grep NotificationLog backend/app/api/` and `frontend/src/` both return **zero hits**; the `ix_notification_log_status_created` index (`models.py:1610`) is even commented "drives the weekly FAILED-row admin review", but that review does not exist. Retry still in-process only. Reach now real for Telegram, still nil for LINE/Viber. |
| FR-019 | Audit trail | ✅ (one filter missing) | Append-only enforced by DB triggers + role REVOKEs. **No batch filter** (PRD lists it; the 2026-07-11 plan shipped SKU only). Price changes not surfaced in the audit screen. |
| FR-020 | Customer/project dashboards | ✅ Implemented | Financial redaction genuinely server-side (staff schemas structurally lack the fields). Any authenticated user can open any customer/project dashboard — documented decision, broader than PRD framing. |

### Telegram enrollment — what actually shipped (2026-07-19)

The one substantive PRD movement since 2026-07-18. End to end:

- **Schema (m031, `c3d4e5f6a7b8`):** `User.telegram_username` (`models.py:208`, display-only), `UNIQUE` on `User.telegram_chat_id` (`uq_user_telegram_chat_id`, `:194`), and a new `TelegramConnectCode` table (`:1636`) — `user_id`, unguessable `code`, `expires_at`, `consumed_at`; its docstring correctly frames it as an authentication boundary.
- **CRUD:** `create_telegram_connect_code` (`crud.py:3253`, `token_urlsafe`, ~10 min TTL, Telegram-deep-link-safe charset per `bc66e57`), `confirm_telegram_connect_code` (`:3281` — validates code/user/expiry/`consumed_at`, and at `:3318` rejects a chat already bound to another user with `CHAT_ALREADY_LINKED` rather than hanging until timeout, per `9d5e37e`).
- **Routes:** `POST /telegram/connect` (`:49`, mints code + `t.me/<bot>?start=<code>` + QR data-URI), `/confirm` (`:66`), `/test` (`:112`, rate-limited, deliberately bypasses prefs), `GET /status` (`:131`).
- **Frontend:** `TelegramConnectCard.tsx` — connect → QR/deep link → 3s poll with a 2-minute give-up → Test button; mounted at `notifications.tsx:170`.

Assessment: the design is sound — the one-time-code + chat-uniqueness model is the right shape for binding an external chat ID to an account, and the `CHAT_ALREADY_LINKED` outcome closes a real hole. The gaps are operational, not architectural: **H-8** (unrate-limited connect/confirm) and **M-15** (silent poll failure).

### NFR gaps (§7–8)

- **Offline conflict message deviation:** PRD promises staff see *"already sold by [name] at [time]"*; actual 409 is `"Unit already SOLD"` — no actor/timestamp, and offline conflicts divert silently to the admin sync-review queue rather than a staff-facing fix-it flow. (Queue cap 7 days ✅, pending-sync counter ✅, idempotent replay ✅.)
- **Frontend Sentry missing** — backend-only (`BE/main.py:23-24`); PRD §8.8 says front-end and back-end.
- **Notification-failure weekly review page missing** (pairs with FR-018) — re-confirmed 2026-07-19, zero references to `NotificationLog` in any route or frontend file.
- **No admin UI/API for any "configurable" setting** — override threshold, slow-mover days, label-printer config (PRD §7.1 lists a System Settings screen). Re-confirmed: `SystemSetting` (`models.py:291`) is read/written **only** through the `crud.py:243-282` helpers; **no route file references it**. `frontend/src/routes/_layout/settings.tsx` is the upstream template's *user* settings page (profile / password / danger zone), not system config — easy to mistake for coverage.
- 12h auto-logout ✅ (sliding refresh window), login rate limiting ✅ (but see M-1), camera-scan fallback ✅, loading/empty states ✅, plain-language errors mostly ✅ (a few enum-caps messages like "Unit already SOLD" remain).
- THB-only / English-only hold cleanly; the exchange-rate setting exists only as docs — nothing half-shipped. Telegram is a scope **addition** beyond the PRD's "LINE and Viber".

### Ranked PRD deltas to reconcile with the client

*Re-ranked 2026-07-19 — #2 shrank but did not close.*

1. FR-017 exports on 3 of ~10 surfaces. **(unchanged — now the clear #1)**
2. FR-018/§8.8 notification-failure review page — still entirely absent. **LINE/Viber enrollment still absent**; Telegram enrollment now ships, so notifications can reach Telegram users without hand-inserted IDs. Worth asking the client whether Telegram *replaces* LINE/Viber or must sit alongside them — building two more enrollment flows is materially more work than the one just shipped.
3. FR-005/006 receiving moved staff → admin-only (documented, but contradicts PRD as written).
4. FR-008 no open-ticket state; no serialized machine-swap exit.
5. FR-004 user management restricted to superuser tier.
6. No settings UI for "configurable" thresholds / printer config.
7. FR-019 batch filter and FR-012 admin batch-cost drill absent.
8. Frontend Sentry absent.

---

## 7. Verified sound (checked, no action needed)

- **Role/financial separation is real server-side enforcement:** role-dispatched response models (`SalePublic`/`SaleStaffPublic`, `CustomerDashboardAdminPublic`/`StaffPublic`, `BatchDrillRow` omitting cost, etc.) — staff cannot reach COGS/margin/purchase cost through any endpoint found.
- **FIFO is race-safe:** `consume_quantity_fifo` orders by `(received_at, id)` under `FOR UPDATE`; sales/tickets/pulls/adjustments lock overrides → units → batches in a fixed documented global order (deadlock-free by design).
- **Money is `Numeric` throughout** — no float money anywhere in the schema; per-line rounded snapshot correctly separated from unrounded authoritative COGS totals.
- **Idempotency:** unique-key + catch-IntegrityError-return-winner on every mutating write path; replay-actor binding (`_assert_replay_actor`) consistent across sales, receipts, tickets, adjustments, sync-review.
- **JWT:** algorithm pinned (HS256, no alg-confusion), exp validated, access/refresh types distinguished; CORS explicit allowlist; no mass-assignment (`UserUpdateMe` exposes only name/email); dev-only `/private` router local-env-only.
- **No injectable SQL** — all user-reachable queries via SQLModel/SQLAlchemy expression builders; no SSRF (notification hosts hardcoded first-party).
- **Append-only genuinely enforced at the DB** — `BEFORE UPDATE OR DELETE` triggers (m021) + `REVOKE UPDATE, DELETE` for `castranova_app` (m026), belt and suspenders.
- **m030 + m031 Telegram migrations correct** — clean revision chain (`586bc2d1d79d` → m028 → m029 → m030 → m031 `c3d4e5f6a7b8`), `ADD VALUE IF NOT EXISTS` idempotent enum upgrade, documented asymmetric downgrade (the only safe option in PG). m031 adds the `UNIQUE` on `telegram_chat_id` that makes the enrollment binding sound. m029 cleanly reverses the two m028 indexes whose audit filter was dropped — no orphan indexes left behind.
- **Telegram enrollment security model** — one-time `token_urlsafe` code with a ~10 min TTL and `consumed_at`, chat-uniqueness enforced at the DB, and `CHAT_ALREADY_LINKED` returned rather than silently rebinding another user's chat. This is the right shape (see §6). `send_telegram` also defends against the token reaching exception messages (`notify.py:138-139`, `:195-196`) — C-2 is purely a transitive httpx-logging gap, not a logic bug.
- **Notification preference grid** — synthetic `enabled=False` defaults mean a fresh user sees the full grid (fixes "no way to create the first row"); role-awareness keys on `role` via `eligible_events()` rather than `deps.is_admin`, and omits ineligible events entirely instead of showing dead switches; backend validates ≤100 prefs and rejects duplicate `(channel, event)` pairs (`models.py:1674-1694`).
- **Working-tree changes clean:** `NotificationChannel.TELEGRAM` handled by all SDK consumers; `useCustomToast` title param backward-compatible across ~30 call sites; new Playwright specs have no hard waits, self-seeded fixtures, auto-retrying assertions.
- **`ListTable` `ResizeObserver`** (`ListTable.tsx:79-89`) has an empty dep array but the `<table>` element identity is stable across renders here — correct as written. Noted only because it is the kind of thing a future reviewer will re-flag.
- Datetimes tz-aware throughout (`get_datetime_utc`); no mutable default args; m027's `NOT VALID → VALIDATE` two-step is the right lock-friendly pattern.

## 8. Known backlog (pre-existing, restated for completeness)

- `ServiceTicketPart` has no `idempotency_key` — a multi-part ticket retry can duplicate part lines (tracked in CLAUDE.md).
- `FORWARDED_ALLOW_IPS=*` residual risk was already known from the 2026-07-16 review (M-1 above) — restated so it isn't lost before the next deploy. Now compounded by H-8's note that all rate limits are shop-global behind Traefik.
- **`CLAUDE.md` is stale on two points** (found 2026-07-19, still true as of the evening pass): it states "Alembic head: `m027` (`586bc2d1d79d`)" — the head is now **`e5f6a7b8c9d0` (m033)**, three migrations further than even the morning pass found; and its Project Status section predates both the Telegram enrollment work and today's two index migrations. Worth a one-line correction so the next `alembic upgrade head` instruction isn't misleading.
- **C-2/M-7 and the H-7 comment cleanup are real but uncommitted** — verified correct in the working tree as of 2026-07-19 evening (see §0), but with nothing protecting them from being lost, reverted, or left out of the next PR. Commit them.

---

## 9. Suggested next actions (2026-07-19, evening)

Nothing here is blocking a merge of the current branch; these are the items where the cost/benefit is clearest.

**✅ Cleared 2026-07-20 — the whole "do first" + "cheap" bucket is now committed:**
1. ~~**Commit the working tree**~~ — `fc8d065` (C-2/M-7 logging + Sentry scrub) and `2dd0636` (H-7 comment consolidation).
2. ~~**M-14**~~ — `6f5c8ea`, `ListFilters` trigger wrapped in `SheetTrigger asChild`.
3. ~~**L-12**~~ — `c03a1d7`, toast helpers `useCallback`-wrapped, false "stable helper" comment corrected.
4. ~~**H-5, M-8**~~ — `b9246d4` (12 crud id params → `uuid.UUID`; the doc undercounted at 11) and `777d5ac` (`assert` → `ValueError` in `send_email`).
5. ~~**CLAUDE.md**~~ — `8d721ac`, head corrected to `e5f6a7b8c9d0` (m033), Project Status refreshed with Telegram enrollment + the index migrations.

**⚠️ L-6 was REJECTED as written — the doc's suggested fix is a latent regression.** `DEFAULT_OVERRIDE_THRESHOLD_PCT` is seeded into `SystemSetting.value`, a **JSONB** column (`models.py:297`), via `seed_system_settings` (`crud.py:274-282`) which runs on every init from `core/db.py:37`. A `Decimal` there raises `TypeError: Object of type Decimal is not JSON serializable` at startup. The read site already converts correctly with `Decimal(str(...))` (`crud.py:1260-1268`) — that *is* the right float→Decimal boundary. `DEFAULT_HOLDING_THRESHOLD_DAYS = 90` (int) sits under the identical contract on the adjacent line. Resolved instead by annotating `: float` with an inline comment recording why (`b9246d4`), so the finding isn't re-filed.

**Needs a decision, not just code:**
- **H-8** — 🟡 **implemented 2026-07-23 on branch `feat/telegram-connect-hardening`; needs merge + the manual pre-flight/browser checks + `alembic upgrade head` for m034.** See the H-8 entry in §2 for full status.
- ~~**H-7**~~ — done. Investigated live; portalling the popover inside the dialog breaks Radix Popper's positioning outright (no fix without touching shared Dialog centering or Popper internals). Kept `modal={false}`, consolidated the 6 duplicated comments into one verified explanation in `EntityCombobox.tsx` (uncommitted — see above). The custom-focus-trap alternative (closing the actual a11y gap rather than documenting around it) remains undone if the trade-off stops being acceptable.

**Done since the morning pass:**
- ~~**C-3 / H-2 / H-3**~~ — shipped as two migrations, `be4b3f2` (m032, ledger FK indexes) and `8bde703` (m033, report-range + remaining FK indexes). Both committed, both declare indexes in `models.py` and Alembic together.
- ~~**C-2**~~ — see "Do first" above; code is done, commit is outstanding.
- ~~**H-4**~~ — `73a4181` + `5287d3a`: server-side stock filters/count/pagination, supplier row narrowing and API guard, role-shaped drill supplier names, matching frontend filters/columns, and replacement Playwright coverage.

**Deliberate deferrals** (documented so they aren't re-litigated): H-1 (owner-approved), L-5, L-8, M-6, L-7 — revisit L-7 and M-6 when load-testing or when the catalog passes a few thousand rows.
