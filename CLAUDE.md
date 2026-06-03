# CLAUDE.md

Behavioral guidelines for working on **CastraNova-POS**, an inventory tracking & management system built on the full-stack-fastapi-template.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

---

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken. Match existing style.
- Remove imports/vars that YOUR changes orphaned; leave pre-existing dead code alone (mention it).
- Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

- "Add validation" → write tests for invalid inputs, then make them pass.
- "Fix the bug" → write a failing test that reproduces it, then make it pass.
- "Refactor X" → tests pass before and after.

For multi-step tasks, state a brief plan with verification per step.

## 5. Feature Development Workflow (Skills)

**Every non-trivial feature follows this skill-driven loop.** Skills are invoked via the Skill tool (or `/<skill-name>`). This loop operationalizes §1–§4 above; don't skip stages on inventory/financial code.

| Stage | Skill | When | Why it's critical here |
|---|---|---|---|
| 1. Plan | `writing-plans` | Before touching code, once per feature/group | Produces bite-sized, DRY tasks → enforces §2 Simplicity & §3 Surgical Changes (no speculative code). Plans live in `docs/plans/`. |
| 2. Build | `subagent-driven-development` | Executing a plan with independent tasks | Dispatches a fresh subagent per task across the stack (model → crud → route → SDK → UI); review between tasks. |
| 3. Test-first | `test-driven-development` | Inside every build task | Red → green → commit. Prevents regressions in FIFO/ledger/margin logic. pytest (backend) + Playwright (E2E) already integrated. |
| 4. Debug | `systematic-debugging` | Any failing/flaky test or wrong stock total | Root-cause **before** fixing. POS cannot afford "ghost inventory" patches — no symptom-chasing on stock movements, FIFO, or money. |
| 5. Review | `requesting-code-review` | Before opening a PR | Independent check that the change obeys §2 Simplicity First & §3 Surgical Changes and the conventions below. |
| 6. Ship | `create-pr` (+ `git-pushing`) | After review passes | Clean, scoped PRs — one feature/task group per PR; never push to `master` directly. |

**The loop:** `writing-plans` (once) → for each task: `subagent-driven-development` → `test-driven-development` → `systematic-debugging` (only if a test resists) → `requesting-code-review` → `create-pr`.

- **Active plan:** `docs/plans/2026-06-04-castranova-pos-implementation.md` (Parts 0–2 are fully bite-sized; Parts 3–5 are a roadmap to expand on demand).
- **Append-only / FIFO / role-tiering changes are "high-risk"** — always run stages 3–5; the FIFO concurrency test (plan Task 2.3) is mandatory before any PR that touches consumption.
- **Skill availability:** stages 1–5 use installed superpowers skills. `github-pr-workflow` is **not installed** — use the installed `create-pr` / `git-pr-workflows-git-workflow` / `git-pushing` instead. (A Hermes `github-pr-workflow` skill is referenced at https://hermes-agent.nousresearch.com/docs/skills; install it explicitly before swapping it into stage 6.)

---

## Project Overview

CastraNova-POS is an **inventory tracking & management system**. Forked from `fastapi/full-stack-fastapi-template`. Core domain (forward-looking): products, stock movements, suppliers, sales, audit trails.

## Stack

| Layer    | Tech                                                                 |
| -------- | -------------------------------------------------------------------- |
| Backend  | FastAPI ≥0.114, SQLModel ≥0.0.21, Pydantic v2, Alembic, psycopg3     |
| Auth     | PyJWT, pwdlib (argon2 + bcrypt)                                      |
| DB       | PostgreSQL                                                           |
| Frontend | React + TypeScript, Vite, TanStack Router + Query, shadcn/ui, Tailwind v4 |
| SDK      | `@hey-api/openapi-ts` — auto-generated from FastAPI OpenAPI          |
| Testing  | pytest (backend), Playwright (E2E)                                   |
| Infra    | Docker Compose, Traefik, Mailcatcher (dev SMTP), Sentry              |
| Tooling  | uv, ruff, mypy (strict), biome, prek (pre-commit)                    |

## Directory Map

```
backend/
  app/
    api/
      deps.py           # FastAPI dependencies (auth, db session)
      main.py           # APIRouter aggregator
      routes/           # HTTP endpoints — one file per resource
    core/               # config, security (JWT, hashing), db engine
    alembic/            # migrations (one per schema change)
    models.py           # SQLModel ORM + Pydantic schemas (single source of truth)
    crud.py             # all DB read/write operations
    main.py             # FastAPI app factory
    initial_data.py     # seed superuser
  tests/                # pytest suites mirroring app/ structure
frontend/
  src/
    routes/             # TanStack file-based routes
    components/         # UI (shadcn/ui primitives + app components)
    client/             # AUTO-GENERATED SDK — never hand-edit
    hooks/  lib/  utils.ts
    routeTree.gen.ts    # AUTO-GENERATED — never hand-edit
compose.yml             # dev orchestration
scripts/                # generate-client.sh, test.sh, etc.
```

## Backend Conventions

- **Models live in `models.py`** — define SQLModel table + the `*Create`/`*Update`/`*Public` schema variants together.
- **All DB access goes through `crud.py`.** Routes never run raw SQL or call `session.exec` directly.
- **Dependencies via `deps.py`** — `SessionDep`, `CurrentUser`, `get_current_active_superuser`.
- **Every schema change requires an Alembic migration.** Generate with `alembic revision --autogenerate -m "..."` then review.
- **Strict typing** — mypy strict mode is on. Annotate everything.
- **Auth** — JWT bearer tokens, password hashing via pwdlib (argon2 preferred).

## Frontend Conventions

- **Regenerate the SDK after any backend schema change:** `bun run generate-client` (or `./scripts/generate-client.sh`). Auto-runs on pre-commit.
- **Routing** — TanStack Router file-based; routes auto-discovered into `routeTree.gen.ts`.
- **Data fetching** — TanStack Query + generated SDK. No bare `axios` calls in components.
- **UI** — shadcn/ui primitives in `components/ui/`. Tailwind v4 utility classes. Dark mode via `next-themes`.
- **Forms** — react-hook-form + `@hookform/resolvers` for validation.
- **Lint/format** — biome (not ESLint/Prettier).

## Database & Domain Conventions

- **Primary keys: UUIDs** (per existing `models.py` pattern).
- **Inventory mutations must be auditable** — include `created_at`, `updated_at`, and the acting `user_id`.
- **Stock movements are append-only.** Don't mutate `quantity_on_hand` directly; insert a movement row and derive totals.
- **Use DB transactions** for any multi-row write (e.g., sale → multiple stock decrements).
- **Soft delete** only when the domain requires audit retention; otherwise hard delete is fine.

## Development Workflow

- Start dev stack: `docker compose watch`
- Backend tests: `bash scripts/test.sh` (or `pytest` inside `backend/`)
- E2E tests: `bun run test` (Playwright) in `frontend/`
- Pre-commit (`prek` / biome / ruff / mypy) must pass before commit.
- Required env vars before any deploy: `SECRET_KEY`, `POSTGRES_PASSWORD`, `FIRST_SUPERUSER_PASSWORD`. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

## What NOT to Do

- ❌ Hand-edit `frontend/src/client/` or `routeTree.gen.ts` (regenerate instead).
- ❌ Skip Alembic migrations when changing `models.py`.
- ❌ Bypass `crud.py` with inline SQL or session queries in routes.
- ❌ Commit `.env` overrides or rotate `SECRET_KEY` without coordination.
- ❌ Mutate stock quantities in place — always go through a movement record.
- ❌ Add features, abstractions, or "flexibility" beyond what was asked (see §2).
