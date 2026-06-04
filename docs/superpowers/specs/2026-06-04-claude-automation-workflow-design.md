# CastraNova POS — Claude Automation Workflow (Design)

**Date:** 2026-06-04
**Status:** Approved (design)
**Author:** brainstorming session

## Goal

Turn CastraNova-POS's documented-but-unenforced guidelines into a layered safety +
velocity system that composes with the existing superpowers loop and ECC specialist
reviewers. Four automations, three layers — not four loose pieces.

## Non-goals (YAGNI)

- No mypy on the per-edit hook (too slow; stays at pre-commit / commit time).
- No Postgres MCP (deferred — optional follow-up).
- No new ECC-equivalent review subagents (ECC already ships fastapi/database/security/python reviewers).
- No `/fewer-permission-prompts` cleanup (separate user-run command).

## Architecture (3 layers)

```
Layer 1 — GUARDRAILS (hooks, deterministic, always on)
   PreToolUse  -> block edits to generated files
   PostToolUse -> auto-ruff on backend Python edits
        v
Layer 2 — KNOWLEDGE (skill, auto-pulled by Claude)
   ledger-invariants -> append-only / FIFO / txn rules in context
        v
Layer 3 — RITUAL (skill, user-invoked)
   new-migration -> wraps alembic -> test -> SDK dance; hands off to ECC database-reviewer
```

## Components

### 1. `block-generated-files.sh` — PreToolUse hook

- **Location:** `.claude/hooks/block-generated-files.sh`
- **Wired in:** `.claude/settings.json` under `hooks.PreToolUse`, matcher `Edit|Write|MultiEdit`.
- **Behavior:** reads JSON from stdin, extracts `.tool_input.file_path`. If the path
  contains `frontend/src/client/` or ends with `routeTree.gen.ts`, emit deny JSON:
  ```json
  {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny",
   "permissionDecisionReason":"<file> is auto-generated. Run `bun run generate-client` instead of hand-editing."}}
  ```
  Otherwise `exit 0` (normal flow).
- **Depends on:** `jq`.
- **Enforces:** CLAUDE.md "What NOT to Do" — never hand-edit `frontend/src/client/` or `routeTree.gen.ts`.

### 2. `ruff-on-edit.sh` — PostToolUse hook

- **Location:** `.claude/hooks/ruff-on-edit.sh`
- **Wired in:** `.claude/settings.json` under `hooks.PostToolUse`, matcher `Edit|Write|MultiEdit`.
- **Behavior:** reads `.tool_input.file_path`. If it matches `backend/**/*.py` and is NOT
  under `backend/app/alembic/` (matching ruff `exclude`), run
  `uv run ruff check --fix --force-exclude <file>` from `backend/`. Always `exit 0`
  (non-blocking — surfaces remaining issues as informational stderr/feedback).
- **mypy:** intentionally excluded (latency). Stays at pre-commit.
- **Mirrors:** existing `.pre-commit-config.yaml` ruff hooks.

### 3. `ledger-invariants` — Claude-only knowledge skill

- **Location:** `.claude/skills/ledger-invariants/SKILL.md`
- **Frontmatter:** `user-invocable: false` (background knowledge, auto-pulled).
- **Triggers:** when Claude touches `crud.py`, stock-movement, unit-movement, or sale code.
- **Encodes:**
  - Stock is append-only — insert a movement row; never mutate `quantity_on_hand` in place.
  - FIFO consumption ordering for stock decrements.
  - Multi-row writes wrapped in a DB transaction (sale -> multiple decrements).
  - Auditable fields on every mutation: `created_at`, `updated_at`, acting `user_id`.
  - All DB access through `crud.py`; routes never run raw SQL / `session.exec`.
- **Composes:** deepens ECC `database-reviewer` / `security-reviewer` (the domain layer they assume but can't see).

### 4. `new-migration` — user-invoked ritual skill

- **Location:** `.claude/skills/new-migration/SKILL.md`
- **Frontmatter:** `disable-model-invocation: true` (mutates the DB — user-only).
- **Steps:**
  1. `POSTGRES_PORT=55432 uv run alembic revision --autogenerate -m "<msg>"`
  2. Pause — show the generated migration diff for human review.
  3. `POSTGRES_PORT=55432 uv run alembic upgrade head`
  4. Run affected tests (`POSTGRES_PORT=55432 uv run pytest <targets> -q`).
  5. Round-trip check: `alembic downgrade -1` then `alembic upgrade head`.
  6. If `models.py` changed, remind: `bun run generate-client`.
  7. Hand off to ECC `database-reviewer` for high-risk (ledger/money/append-only) changes.
- **Composes:** slots into the superpowers Build stage; ECC `database-reviewer` is the Review handoff.

## Composition with existing workflow

- Hooks run under *every* superpowers stage automatically (guardrails during
  `subagent-driven-development`, `test-driven-development`, etc.).
- `ledger-invariants` supplies the missing domain layer to ECC reviewers.
- `new-migration` is a Build-stage tool whose Review handoff is ECC `database-reviewer`.

## Error handling

- Hooks fail-safe: any script error -> `exit 0` (never block legitimate work on a buggy hook).
- The block hook is the one intentional exception: it denies on path match.

## Testing

- **Hooks:** simulate stdin JSON and assert exit code / output.
  - `echo '{"tool_input":{"file_path":"frontend/src/client/sdk.gen.ts"}}' | .claude/hooks/block-generated-files.sh` -> deny JSON.
  - `echo '{"tool_input":{"file_path":"backend/app/models.py"}}' | .claude/hooks/block-generated-files.sh` -> exit 0.
  - ruff hook: edit a deliberately unformatted temp `.py` under `backend/`, assert it gets fixed; assert a non-`backend` path is ignored.
- **Skills:** dry-run the documented commands; confirm frontmatter invocation flags behave (user-only / Claude-only).

## Config schema reference (verified via context7, /websites/code_claude)

PreToolUse/PostToolUse entries take a `matcher` (tool-name regex) and a `hooks` array of
`{type:"command", command:"<path>"}`. Scripts read tool JSON from stdin (`.tool_input.*`).
Block via `exit 2` or `permissionDecision:"deny"` JSON; `exit 0` = no decision.
