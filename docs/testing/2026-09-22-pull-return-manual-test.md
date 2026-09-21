# Manual test — project pull returns (branch `feat/pull-return`)

App: http://localhost:5173 · API: http://localhost:8000

| Login | Password | Role |
|---|---|---|
| `admin@example.com` | `FIRST_SUPERUSER_PASSWORD` from `.env` (not `changethis`) | superuser (admin) |
| `bkk.admin@example.com` | `changethis` | BKK admin — can stand in for admin in every step |
| `ygn.staff@example.com` | `changethis` | YGN staff |

> **Don't run backend tests while testing.** They truncate the dev DB, including your test data.

Customers per project (shown in the New request picker as "Project (CODE) — Customer"):
PRJ-2026-01 and PRJ-2026-03 → **Thiri Trading**; PRJ-2026-02 → **Ko Min Electronics**.
To create a request for another customer, create a project for that customer first (Catalog → Projects).

**Where to look:**
- **Search** (Sell → Search, type the SKU): "On hand" plus a table of batches.
- **Stock requests** (Service → Pulls): the queue. It shows only waiting requests by default; click **Show all (incl. completed)** to see finished ones.
- **Audit** (Admin → Audit): the movement ledger.
- **Project dashboard** (Admin → Catalog → Projects → open a project): the Consumed cost card and the Consumed items list.

## Starting state (fresh seed)

| Project | Request | Item | State |
|---|---|---|---|
| PRJ-2026-01 Thiri Store Refit | 5 × USB-C Cable 2m (`CBL-USBC-2M`) | PART | **Done** (FULFILLED) |
| PRJ-2026-02 Ko Min Bulk Order | 1 × Galaxy S23 Ultra, unit `CN-EC214E0656AA4673` | UNIT | **Waiting** (PENDING) |
| PRJ-2026-03 Internal Spares Pool | 4 × Galaxy S23 Battery (`BAT-SG23-STD`) | PART | **Waiting** (PENDING) |

| SKU | Batch | Remaining |
|---|---|---|
| CBL-USBC-2M | …-001 @ 60.00 | **29** |
| CBL-USBC-2M | …-002 @ 72.00 | 30 |
| CBL-USBC-2M | …-ADJ-001 @ 58.00 | 12 → On hand **71** |
| BAT-SG23-STD | …-001 @ 60.00 | **33** |
| BAT-SG23-STD | …-002 @ 72.00 | 30 → On hand **63** |

Unit `CN-EC214E0656AA4673` is in state **PROJECT_OUT**, with a cost of 29,800.00.

> To start over at any time:
> `docker compose exec -T backend bash -c "cd /app/backend && python app/initial_data.py && python -m app.seed_demo"`

---

## A. Return part of a finished request (staff)

1. Log in as **ygn.staff@example.com** and open **Stock requests**.
2. Click **Show all (incl. completed)**.
   - [ ] The Thiri Store Refit row shows **Done**, and its button reads **Open** (not "Give out parts").
   - [ ] There is **no Cancel** button (staff can never cancel).
3. Click **Open**.
   - [ ] The page shows "This request is done", with a **Return items to stock** button.
4. Click **Return items to stock**.
   - [ ] The dialog lists `USB-C Cable 2m (CBL-USBC-2M)` at **0 / 5**.
   - [ ] **Return 0 items** is disabled.
5. Press **+** three times.
   - [ ] The line reads 3 / 5 and the button reads **Return 3 items**.
   - [ ] You cannot go past 5, and **−** at 0 is disabled.
6. Click **Return 3 items**.
   - [ ] A toast says "Items returned to stock." and the dialog closes.
7. Go to Search → `CBL-USBC-2M`.
   - [ ] On hand is **74** (71 + 3).
   - [ ] Batch **-001** is **32** (the return went back to the batch the pull took from, at 60.00). The other batches are unchanged.
8. Go back to the request and open **Return items to stock** again.
   - [ ] The line now shows **0 / 2**.

## B. Return the rest, then nothing is left (admin)

1. Log in as **admin@example.com**, open the Thiri request and return **2**.
   - [ ] On hand is **76** and batch -001 is **34**.
2. Look at the request page again.
   - [ ] The **Return items to stock** button is **gone**, because nothing is still out.
   - [ ] The request still says **Done** with "Given out 1 of 1". Returns don't rewrite the hand-out record.

## C. Project COGS nets the return (admin)

1. Open project **PRJ-2026-01**.
   - [ ] **Consumed cost** is **0.00**: out 5 × 60 = 300, back 5 × 60 = 300.
   - [ ] **Consumed items** has the original row (5, 300.00) plus returned rows shown as **−3 / −180.00** and **−2 / −120.00**, each marked "Returned · <time>".
   - [ ] Expanding a returned row shows its batch with the same **−** sign.
2. Open Reports → **Channel margin** for September 2026.
   - [ ] The PROJECT channel's COGS went down by 300 compared with before the returns. If you checked it before step A, it was 300 lower after returning all 5.
3. Open Admin → **Audit**, filtered to SKU `CBL-USBC-2M`.
   - [ ] Two **RETURNED** rows, each with Source **Project pull**, the right user and the right quantity.

## D. Cancel a waiting request puts stock back (admin)

1. As admin, on **Stock requests** (default "waiting" view):
   - [ ] **Internal Spares Pool** has a **Cancel** button. Before this change it had none.
2. Click **Cancel** on Internal Spares Pool.
   - [ ] A toast says "Request cancelled — stock put back."
3. Search → `BAT-SG23-STD`.
   - [ ] On hand is **67** (63 + 4) and batch -001 is **37**.
4. Click **Cancel** on **Ko Min Bulk Order** (the unit).
   - [ ] Search → `SG23U-512-GRN`: unit `CN-EC214E0656AA4673` is **IN_STOCK** again.
   - [ ] Open project PRJ-2026-02: **Consumed cost** is **0.00**.
5. Click **Show all**.
   - [ ] Both requests show **Cancelled**, and neither has a Return button (nothing left out).

## E. Short hand-out, then cancel, then return the surplus (admin + staff)

1. As **admin**, click **New request**: project **PRJ-2026-03**, add **Galaxy S23 Battery × 3**, and submit.
   - [ ] A toast says "Request created — stock deducted." On hand is **64** (67 − 3).
2. As **ygn.staff**, click **Give out parts** on it. Set the battery line to **1 / 3** with the steppers, then click **Done — give out parts**.
   - [ ] A toast says "some items still short", and the request is **Short**.
3. As **admin**, click **Cancel** on the Short request.
   - [ ] The toast says **"Request closed. Items already given out stay out — use Return to bring them back."** It must **not** say "stock put back".
   - [ ] On hand is **still 64**. Cancelling a Short request moves no stock.
4. Open the (now Cancelled) request and click **Return items to stock**.
   - [ ] The line shows **0 / 3**: all 3 are still deducted, the 2 never handed out plus the 1 given out.
5. Return **2** (the ones never handed out).
   - [ ] On hand is **66**, and the line now shows **0 / 1**.

## F. Guard rails

1. **Double submit.** In a Return dialog, set 1 and double-click **Return 1 item** quickly.
   - [ ] Only **one** return happens: on hand goes up by 1, and Audit shows one RETURNED row.
2. **Stale cap.** Open the same finished request in two browser tabs, both with the Return dialog open. Return everything in tab 1, then try to return 1 in tab 2.
   - [ ] Tab 2 shows an error toast ("Over-return: 0 returnable…").
   - [ ] Reopening the dialog shows fresh caps, and no extra stock appears.
3. **Waiting requests have no Return.** Open any **Waiting** request.
   - [ ] There is no **Return items to stock** button, only the give-out screen.
4. **Unit re-pulled elsewhere.** After D.4, as admin, create a new request for PRJ-2026-01 with **Galaxy S23 Ultra × 2**. It auto-claims the in-stock units, including `CN-EC214E0656AA4673`, the one Ko Min gave back.
   - [ ] The old cancelled Ko Min request still offers **no** Return for that unit.
   - [ ] The new request, once handed out, offers its own Return.
5. **Old sale returns unaffected.** Sell → **Return**: return one item from a seeded sale as usual.
   - [ ] It works exactly as before (regression check for the shared return code).

## G. (Optional) API-only checks

These live in the automated tests too. Try them if you're curious, with the admin token in Swagger at http://localhost:8000/docs:
- [ ] `POST /project-pulls/{id}/returns` on a **Waiting** request → **409** "…an admin can cancel it…".
- [ ] Repeating the same body and the same `idempotency_key` → **200**, and no second RETURNED row.
- [ ] The same key sent while logged in as a different user → **409** "…used by a different user."
- [ ] `quantity: 0`, an unknown `line_id`, or a duplicated `line_id` → **422**.
- [ ] Creating a request with **two PART lines for the same product** → **422** "One PART line per product". The UI cart merges these, so you can't reach this from the screen.

## H. Returns page

1. Log in as **ygn.staff@example.com** (or admin) and open **Sell → Return**.
2. Stay on the **Quantity SKU** tab and scan `BAT-SG23-STD`.
   - [ ] The picker lists the Test/seed project requests for this SKU alongside any sale, not just sales.
3. Pick the project-request option and return **2**.
   - [ ] There is **no** reason field for a project-request return (only sale returns ask for one).
   - [ ] On success, on hand goes up by **2**, and the toast says "Return recorded. The stock is back on hand."
4. Switch to the **Serialized unit** tab and scan a barcode that was pulled by a project request but never sold.
   - [ ] The card reads "This unit went out on a project request…" with a **Return to stock** button and no reason field.
   - [ ] Clicking it returns the unit; a re-scan no longer offers it back.
