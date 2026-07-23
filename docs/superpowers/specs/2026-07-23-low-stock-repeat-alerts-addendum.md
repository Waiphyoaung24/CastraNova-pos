# Addendum: low-stock alert fires on every decrease below threshold, not just the first crossing

**Date:** 2026-07-23
**Type:** Small addendum (bug fix), not a full spec/plan cycle
**Related:** FR-016 (Low-Stock Alerts, Per SKU) — `docs/client/2026-06-02-castranova-pos-v3.0-prd.md:254-257`

## Problem

`crud.py`'s `consume_quantity_fifo` flags a product for a low-stock push only on
a *fresh* downward crossing:

```python
if threshold is not None and total_available >= threshold and after < threshold:
```

With min stock level 3: consuming 3→2 fires (was ≥3, now <3). A later
consumption 2→1 does **not** fire, because `total_available` (2) is already
below the threshold — the `total_available >= threshold` clause is always
false from that point on, so every further drop is silently skipped until
the SKU is restocked back above the threshold.

## PRD check

FR-016 says only: "When Yangon stock drops below the threshold, an alert
fires via LINE and Viber." This is phrased as a state check, not "the first
time." Nothing elsewhere in the PRD (FR-018 notification infra, the v1.1
deferred-items table, §10 Tricky Scenarios) specifies or implies a
fire-once-until-restocked cooldown. The deferred stock-out-dashboard note
("the data is already captured by FR-016 alerts") reads as expecting FR-016
to capture the full trajectory down to zero, not just the first crossing.
The current "fresh crossing only" behavior was an implementation choice, not
a documented requirement — this fix does not conflict with the PRD.

## Fix

`consume_quantity_fifo` already rejects `quantity_needed <= 0` with a 400 at
the top of the function, so every call represents a real decrease. Drop the
"was at/above before" clause:

```python
if threshold is not None and after < threshold:
    session.info.setdefault("low_stock_crossed", set()).add(product_id)
```

Now any consumption that leaves a product below its threshold flags it:
3→2 pushes, 2→1 pushes, 1→0 pushes.

## Scope

- Applies to the three callers of `consume_quantity_fifo` that read
  `pop_low_stock_crossed()`: sales, service tickets, project pulls.
- Stock adjustments stay silent — unchanged, separate deliberate exclusion
  (`crud.py`, "Flow E.5: adjustments never notify").
- No change to notification dispatch, opt-in preferences, or the
  `set()`-based one-push-per-request dedup.

## Testing

- `backend/tests/api/routes/test_low_stock.py::test_already_below_threshold_no_new_alert`
  currently asserts the *old* (buggy) behavior — a sale from 4→3 (already
  below threshold 5) must NOT alert. This assertion is wrong under the fix
  and must be inverted: it SHOULD alert. Rename/rewrite it accordingly.
- Add a test for the reported scenario directly: two sequential sales
  against the same SKU, min level 3, first 3→2 (alert), second 2→1 (alert)
  — asserting two separate SENT logs, not just one.
- `test_stays_above_threshold_no_alert` and `test_null_threshold_never_alerts`
  are unaffected and stay as-is.
- Per CLAUDE.md's high-risk rule (this touches code inside
  `consume_quantity_fifo`), run the FIFO concurrency test
  (`backend/tests/crud/test_fifo_concurrency.py`) before merging, even
  though this change doesn't touch locking or quantity math.
