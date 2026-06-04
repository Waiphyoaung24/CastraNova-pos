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
