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
- Use [[new-migration]] for any schema change these rules touch.
