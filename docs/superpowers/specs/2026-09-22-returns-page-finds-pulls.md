# Returns page finds project pulls — design addendum (2026-09-22)

Extends `2026-09-21-pull-return-design.md`. Manual testing showed staff go to
Sell → Return to bring back stock that left on a project pull, and that page
only knows sales. Decision: the Returns page lists project requests too, mixed
into the same picker, newest first. The Pulls-page Return stays.

## Backend
- `GET /project-pulls/returnable?castranova_barcode=|sku=` — any logged-in
  user (same gate as `/sales/returnable`). Declared **before** `/{pull_id}`.
  Exactly one selector, else 422; unknown SKU → 404 "Product not found".
- Response `ReturnablePullsPublic { pulls: [ReturnablePullPublic] }`:
  `pull_id, project_code, project_name, customer_name, created_at,
  lines: [ReturnablePullLinePublic { line_id, line_kind, product_id, label
  ("SKU — Model"), quantity_out (line cap: 1 UNIT / requested_qty PART),
  quantity_returnable }]`. No cost fields.
- crud `list_returnable_pulls(*, session, castranova_barcode, sku, limit=20)`:
  pull lines matching the product (PART: `product_id`; UNIT: `unit_serial ==
  barcode`), joined to non-PENDING pulls, newest `created_at` first,
  over-fetch ×4, per pull compute `pull_line_returnable`, drop lines at 0,
  cap at `limit` pulls. Mirrors `list_returnable_sales`.

## Frontend (Sell → Return)
- Second lookup `ProjectPullsService.readReturnablePulls` runs alongside the
  sales lookup for the same scan.
- One picker, options merged newest first. Option value is prefixed
  (`sale:<sale_line_id>` / `pull:<line_id>`) so the two id spaces can't
  collide. Labels: sale → `dd/mm/yyyy · Customer · N of M returnable`
  (unchanged); pull → `dd/mm/yyyy · Project name (CODE) · Customer · N of M
  returnable`.
- A pull return needs no reason and has no refund: when a pull option is
  picked, hide the reason field and the refund line. Submit via
  `ProjectPullsService.returnProjectPull` with `{idempotency_key, lines:
  [{line_id, quantity}]}`; key minted per attempt as today.
- Unit tab: if the barcode has no returnable sale but has a returnable pull
  line, offer "Return to stock" for that pull (no reason field).
- Empty state copy: "Nothing from this SKU can be returned — no recent sale
  or project request still has returnable stock."
- Page description and help box mention project requests.

## Tests
- Backend: barcode→pull, sku→pulls newest first, fully-returned line
  disappears, PENDING pull excluded, exactly-one-selector 422, staff allowed,
  no cost keys in the payload.
- Vitest: picker merge order + labels + value prefixes; submit rules (reason
  not required for pull).
- E2E: SKU scan on Returns page picks a project option, returns 2, on hand +2;
  unit from a pull returned via the Unit tab.
