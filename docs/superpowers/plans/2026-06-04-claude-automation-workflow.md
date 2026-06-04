# Claude Automation Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two guardrail hooks and two workflow skills that enforce CastraNova-POS's CLAUDE.md rules mechanically and compose with the superpowers loop + ECC reviewers.

**Architecture:** Layer 1 = deterministic hooks (block generated-file edits; auto-ruff backend Python). Layer 2 = a Claude-only `ledger-invariants` knowledge skill. Layer 3 = a user-only `new-migration` ritual skill. Hooks are wired into the checked-in `.claude/settings.json` so the whole team gets them.

**Tech Stack:** Bash + `jq` (hooks), Claude Code hook schema (`PreToolUse`/`PostToolUse`), Markdown SKILL.md files, `uv`/`ruff`/`alembic`/`bun` (referenced by skills).

---

## File Structure

- Create: `.claude/hooks/block-generated-files.sh` — PreToolUse guard, blocks edits to generated files.
- Create: `.claude/hooks/ruff-on-edit.sh` — PostToolUse, auto-fixes backend Python with ruff.
- Modify: `.claude/settings.json` — add `hooks` block wiring both scripts (checked-in / shared).
- Create: `.claude/skills/ledger-invariants/SKILL.md` — Claude-only domain knowledge.
- Create: `.claude/skills/new-migration/SKILL.md` — user-only migration ritual.

Hooks live together under `.claude/hooks/`; each script has one responsibility. Settings wiring is the single integration point.

---

### Task 1: Block-generated-files PreToolUse hook

**Files:**
- Create: `.claude/hooks/block-generated-files.sh`
- Modify: `.claude/settings.json`

- [ ] **Step 1: Write the hook script**

Create `.claude/hooks/block-generated-files.sh`:

```bash
#!/usr/bin/env bash
# PreToolUse hook (matcher: Edit|Write|MultiEdit).
# Blocks edits to auto-generated files per CLAUDE.md "What NOT to Do".
# Fail-safe: any unexpected condition -> exit 0 (no decision).

input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[ -z "$file_path" ] && exit 0

case "$file_path" in
  *frontend/src/client/*|*routeTree.gen.ts)
    reason="$file_path is auto-generated. Run 'bun run generate-client' (or ./scripts/generate-client.sh) instead of hand-editing it."
    jq -n --arg r "$reason" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}' 2>/dev/null
    exit 0
    ;;
esac
exit 0
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x .claude/hooks/block-generated-files.sh`

- [ ] **Step 3: Write the failing test (run before wiring)**

Run:
```bash
echo '{"tool_input":{"file_path":"/x/frontend/src/client/sdk.gen.ts"}}' | .claude/hooks/block-generated-files.sh
```
Expected: JSON containing `"permissionDecision":"deny"`.

Run:
```bash
echo '{"tool_input":{"file_path":"/x/frontend/src/routeTree.gen.ts"}}' | .claude/hooks/block-generated-files.sh
```
Expected: JSON containing `"permissionDecision":"deny"`.

Run:
```bash
echo '{"tool_input":{"file_path":"/x/backend/app/models.py"}}' | .claude/hooks/block-generated-files.sh
```
Expected: empty output, exit 0.

Run:
```bash
echo '{}' | .claude/hooks/block-generated-files.sh; echo "exit=$?"
```
Expected: `exit=0` (fail-safe on missing field).

- [ ] **Step 4: Wire into `.claude/settings.json`**

Add a top-level `"hooks"` key (sibling of `env`, `enabledPlugins`). The full merged file:

```json
{
  "env": {
    "ECC_DISABLED_HOOKS": "pre:edit-write:gateguard-fact-force,pre:bash:gateguard-fact-force",
    "ECC_CONTEXT_MONITOR_COST_WARNINGS": "off"
  },
  "extraKnownMarketplaces": {
    "ecc": {
      "source": {
        "source": "git",
        "url": "https://github.com/affaan-m/ECC.git"
      },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "ecc@ecc": true,
    "superpowers@claude-plugins-official": true
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/block-generated-files.sh"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/block-generated-files.sh .claude/settings.json
git commit -m "feat(hooks): block edits to generated client + routeTree (PreToolUse)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Ruff-on-edit PostToolUse hook

**Files:**
- Create: `.claude/hooks/ruff-on-edit.sh`
- Modify: `.claude/settings.json`

- [ ] **Step 1: Write the hook script**

Create `.claude/hooks/ruff-on-edit.sh`:

```bash
#!/usr/bin/env bash
# PostToolUse hook (matcher: Edit|Write|MultiEdit).
# Auto-fixes backend Python with ruff, mirroring .pre-commit-config.yaml.
# Non-blocking: always exit 0. mypy intentionally excluded (latency).

input=$(cat)
file_path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[ -z "$file_path" ] && exit 0

case "$file_path" in
  *backend/app/alembic/*) exit 0 ;;        # matches ruff [tool.ruff] exclude
  *backend/*.py)
    cd "${CLAUDE_PROJECT_DIR:-.}/backend" 2>/dev/null || exit 0
    uv run ruff check --fix --force-exclude "$file_path" 2>&1 || true
    ;;
esac
exit 0
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x .claude/hooks/ruff-on-edit.sh`

- [ ] **Step 3: Test path matching (no ruff side effects on non-backend)**

Run:
```bash
echo '{"tool_input":{"file_path":"/x/backend/app/alembic/versions/abc.py"}}' | .claude/hooks/ruff-on-edit.sh; echo "exit=$?"
```
Expected: `exit=0`, no ruff output (alembic excluded).

Run:
```bash
echo '{"tool_input":{"file_path":"/x/frontend/src/foo.ts"}}' | .claude/hooks/ruff-on-edit.sh; echo "exit=$?"
```
Expected: `exit=0`, no ruff output (not backend python).

- [ ] **Step 4: Test ruff actually fixes a backend file**

Run:
```bash
printf 'import os\nx=1\n' > backend/app/_hooktmp.py
echo "{\"tool_input\":{\"file_path\":\"$(pwd)/backend/app/_hooktmp.py\"}}" | .claude/hooks/ruff-on-edit.sh
cat backend/app/_hooktmp.py
rm -f backend/app/_hooktmp.py
```
Expected: ruff reports/removes the unused `import os` (file changed or violation reported); exit 0. Then temp file removed.

- [ ] **Step 5: Add to `hooks` in `.claude/settings.json`**

Add a `"PostToolUse"` array alongside the existing `"PreToolUse"`. The `hooks` block becomes:

```json
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/block-generated-files.sh"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/ruff-on-edit.sh"
          }
        ]
      }
    ]
  }
```

- [ ] **Step 6: Commit**

```bash
git add .claude/hooks/ruff-on-edit.sh .claude/settings.json
git commit -m "feat(hooks): auto-ruff backend python on edit (PostToolUse)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: ledger-invariants knowledge skill

**Files:**
- Create: `.claude/skills/ledger-invariants/SKILL.md`

- [ ] **Step 1: Write the skill file**

Create `.claude/skills/ledger-invariants/SKILL.md`:

```markdown
---
name: ledger-invariants
description: Stock/ledger correctness invariants for CastraNova-POS. Use whenever editing crud.py, stock-movement, unit-movement, sale, or any code that changes inventory quantities or money.
user-invocable: false
---

# Ledger Invariants (CastraNova-POS)

Apply these to ALL inventory/financial changes. They are "high-risk" per CLAUDE.md —
run superpowers stages 3-5 and ECC database-reviewer + security-reviewer.

## Non-negotiable rules

1. **Append-only stock.** Never mutate `quantity_on_hand` (or any running total) in
   place. Insert a movement row (stock movement / unit movement / SOLD ledger entry)
   and derive totals by aggregation.
2. **FIFO consumption.** Stock decrements consume oldest-received units first. Order
   the consumed rows deterministically (e.g. by `received_at`, then id).
3. **Transactions for multi-row writes.** A sale that decrements multiple units must
   commit as one DB transaction — all-or-nothing.
4. **Auditable mutations.** Every mutation row carries `created_at`, `updated_at`, and
   the acting `user_id`.
5. **All DB access through `crud.py`.** Routes never run raw SQL or call
   `session.exec` directly. Schema changes require an Alembic migration.
6. **Idempotency.** Receive/sale endpoints replay safely (see `get_or_replay` helper).

## When reviewing or writing this code

- Trace the existing FIFO/ledger path first (ecc:code-explorer) before adding to it.
- The FIFO concurrency test (plan Task 2.3) is mandatory before any PR touching consumption.
- Hand serialized/ledger/money changes to ecc:database-reviewer and ecc:security-reviewer.
```

- [ ] **Step 2: Verify it loads**

Run: `ls .claude/skills/ledger-invariants/SKILL.md`
Expected: path printed (file exists). The `user-invocable: false` flag means Claude
auto-pulls it but it is not user-typed via `/`.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/ledger-invariants/SKILL.md
git commit -m "feat(skill): ledger-invariants domain knowledge (Claude-only)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: new-migration ritual skill

**Files:**
- Create: `.claude/skills/new-migration/SKILL.md`

- [ ] **Step 1: Write the skill file**

Create `.claude/skills/new-migration/SKILL.md`:

```markdown
---
name: new-migration
description: Generate and verify an Alembic migration for CastraNova-POS, then hand off to review. User-invoked only (mutates the DB).
disable-model-invocation: true
---

# New Migration (CastraNova-POS)

Wraps the standard Alembic ritual. Test DB runs on port 55432. Run from `backend/`.
Ask the user for a short migration message if not provided.

## Steps

1. **Generate** the revision:
   ```bash
   POSTGRES_PORT=55432 uv run alembic revision --autogenerate -m "<message>"
   ```
2. **Review the diff.** Open the new file under `backend/app/alembic/versions/` and
   show it to the user. Confirm it only contains intended changes (no spurious drops).
3. **Apply:**
   ```bash
   POSTGRES_PORT=55432 uv run alembic upgrade head
   ```
4. **Run affected tests:**
   ```bash
   POSTGRES_PORT=55432 uv run pytest <relevant test targets> -q
   ```
5. **Round-trip check** (catches non-reversible migrations):
   ```bash
   POSTGRES_PORT=55432 uv run alembic downgrade -1
   POSTGRES_PORT=55432 uv run alembic upgrade head
   ```
6. **Regenerate the SDK** if `models.py` changed:
   ```bash
   cd ../frontend && bun run generate-client
   ```
7. **Hand off to review.** For ledger / money / append-only changes (high-risk),
   dispatch ecc:database-reviewer and ecc:security-reviewer per CLAUDE.md.

## Notes

- Reference [[ledger-invariants]] when the migration touches stock/sale tables.
- Never edit a migration that has already shipped; add a new one.
```

- [ ] **Step 2: Verify it loads**

Run: `ls .claude/skills/new-migration/SKILL.md`
Expected: path printed. `disable-model-invocation: true` means it runs only when the
user invokes `/new-migration` (it mutates the DB).

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/new-migration/SKILL.md
git commit -m "feat(skill): new-migration ritual (user-only)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Validate settings.json is valid JSON**

Run: `jq . .claude/settings.json > /dev/null && echo OK`
Expected: `OK`.

- [ ] **Step 2: Confirm both hook scripts are executable**

Run: `ls -l .claude/hooks/*.sh`
Expected: both files have `x` permission bits.

- [ ] **Step 3: Re-run the four hook behavior checks from Tasks 1-2**

Confirm: deny on generated paths, exit 0 on backend models, alembic skipped, ruff fixes a backend temp file. (Commands as in Tasks 1 & 2.)

- [ ] **Step 4: Confirm skills are discoverable**

Run: `ls .claude/skills/*/SKILL.md`
Expected: both `ledger-invariants` and `new-migration` listed.

- [ ] **Step 5: Reload plugins/skills**

Tell the user to run `/reload-plugins` (or restart the session) so the new hooks and
skills are picked up by the running Claude Code instance.

---

## Self-Review

- **Spec coverage:** block hook (Task 1), ruff hook (Task 2), ledger-invariants (Task 3),
  new-migration (Task 4), settings wiring (Tasks 1-2), testing approach (Tasks 1,2,5).
  mypy-excluded and Postgres-MCP-skipped honored. All spec sections covered.
- **Placeholders:** `<message>` and `<relevant test targets>` in the new-migration SKILL
  are intentional runtime arguments (the skill is a template the user/Claude fills at
  invocation), not plan placeholders. No "TBD"/"TODO" in build steps.
- **Type/name consistency:** hook filenames, settings `command` paths, and skill `name`
  frontmatter match across tasks. `[[ledger-invariants]]` link in Task 4 matches the
  skill name in Task 3.
