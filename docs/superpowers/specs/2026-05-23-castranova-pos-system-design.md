# CastraNova-POS — System Design Spec

**Date:** 2026-05-23
**Status:** Approved (brainstorm phase complete, pending implementation plan)
**Scope:** v1 MVP — cross-border serialized inventory tracking between Bangkok HQ and Yangon branch.

---

## 1. Context & Problem

CastraNova is an international trading enterprise headquartered in **Thailand (Bangkok)** with a satellite office in **Myanmar (Yangon)**, trading **refrigeration machinery** (B2B / industrial).

**Pain point:** inventory tracking between the Bangkok HQ warehouse and the Yangon office is not streamlined. Units move BKK → YGN but staff have no reliable way to know *what's in transit, what arrived, what was sold, and what's in service*. Yangon's internet is unreliable, so any solution must work offline.

**v1 goal:** every refrigeration unit is barcoded once, then scanned at every state change. HQ sees one consolidated, audited view of every machine's lifecycle.

## 2. Constraints

| Constraint | Value |
|---|---|
| Inventory flow | Bangkok = procurement hub; Yangon = receive + sell + service. Returns flow back to YGN service, then back to YGN stock. |
| Tracking granularity | Serialized units only (one barcode per machine). Parts/accessories deferred. |
| Volume | 500–700 units/month |
| Users | ~5 staff per office (10 concurrent max) |
| Connectivity | Yangon wifi unreliable; mobile-data fallback acceptable; offline scanning must work |
| Stack | Existing: FastAPI, SQLModel, Postgres, React+Vite+TanStack, shadcn/ui, JWT |
| Languages | English UI (v1) |
| Currency | THB only (v1) |

## 3. Architecture

```
┌─────────────────────────┐       ┌─────────────────────────┐
│  Bangkok HQ (online)    │       │  Yangon Office          │
│  ─ admin staff          │       │  ─ warehouse + sales    │
│  ─ laptops/phones       │       │  ─ scan via PWA         │
└───────────┬─────────────┘       └────────────┬────────────┘
            │ HTTPS                            │ HTTPS (wifi or 4G)
            ▼                                  ▼
        ┌─────────────────────────────────────────┐
        │   FastAPI + Postgres (Bangkok cloud)    │
        │   ─ JWT auth                            │
        │   ─ append-only movement ledger         │
        │   ─ server-side unit state machine      │
        └─────────────────────────────────────────┘
                          ▲
                          │ generates
                  ┌───────┴────────┐
                  │ Barcode/QR PDF │  (Code128 encoding serial)
                  └────────────────┘
```

**Approach:** centralised Postgres in Bangkok; React PWA with service worker + IndexedDB write queue for offline scanning in Yangon. Queue replays to FastAPI when network returns (mobile data fallback acceptable).

**Rejected alternatives:**
- *Local Yangon Postgres replica.* Adds hardware and bidirectional sync complexity not justified at this scale.
- *Native mobile app.* Doubles maintenance vs. PWA; PWA on phone is sufficient for barcode scanning.

### Components

1. **PWA frontend** — existing React app + service worker + IndexedDB queue. Installable to home screen.
2. **FastAPI backend** — existing app, with new routers: `units`, `shipments`, `movements`, `service_tickets`, `locations`, `suppliers`, `customers`, `products`.
3. **Postgres** — existing. Append-only `unit_movement` table is the source of truth.
4. **Barcode service** — backend module rendering Code128 PDF sheets (one label per unit) using `reportlab` or `python-barcode`.
5. **Auth** — existing JWT. Roles: `admin`, `staff`, `technician`.
6. **Offline queue** — frontend IndexedDB; idempotent replay on reconnect.

## 4. Data Model

Seven new tables. Existing `user` table unchanged.

| Table | Key fields | Purpose |
|---|---|---|
| `location` | id, code, name, country | BKK_WH, YGN_WH, IN_TRANSIT, CUSTOMER, SERVICE, SCRAPPED. Extensible to new branches. |
| `supplier` | id, name, country, contact | Procurement source. |
| `product` | id, sku, model_name, brand, specs (jsonb), unit_price_thb | Machine model (e.g., "Daikin RXM-50N"). |
| `customer` | id, name, country, contact, type (dealer/end-customer) | Sales target. |
| `unit` ⭐ | id (uuid), serial_no (unique), barcode, product_id, supplier_id, current_state, current_location_id, created_at, created_by | One physical machine. `current_state`/`current_location_id` are denormalised caches of latest movement (for fast queries). |
| `unit_movement` ⭐ | id, unit_id, event_type, from_location_id, to_location_id, shipment_id?, customer_id?, service_ticket_id?, actor_user_id, occurred_at, idempotency_key (unique), notes | **Append-only ledger.** Source of truth. |
| `shipment` | id, code, origin_location_id, dest_location_id, dispatched_at, received_at?, status, created_by | Groups units in transit. |
| `service_ticket` | id, unit_id, opened_at, closed_at?, issue, resolution, technician_user_id | Warranty/service history. |

All tables: UUID primary keys, `created_at`/`updated_at`, `actor_user_id` on mutations (per project conventions in CLAUDE.md).

### Unit state machine

```
CREATED ─► IN_BKK ─► IN_TRANSIT ─► IN_YGN ─┬─► SOLD
                                           │
                                           ├─► RETURNED ─► IN_SERVICE ─► IN_YGN (loop)
                                           │
                                           └─► SCRAPPED
```

Transitions are enforced by the backend on every `unit_movement` insert. Illegal transitions return **409 Conflict** with the reason. Compensating movements (not edits) correct mistakes.

### Append-only ledger enforcement

- Postgres `REVOKE UPDATE, DELETE ON unit_movement` from app role.
- SQLModel/crud layer offers no update or delete method for movements.
- All corrections happen by inserting a new compensating movement row.

## 5. Key User Flows

### Flow A: Procurement (Bangkok admin, online)
1. Admin selects product + supplier + quantity → backend creates N `unit` rows with auto-generated serials and barcodes.
2. Backend writes N `unit_movement` rows: `RECEIVED_FROM_SUPPLIER`, location = BKK_WH.
3. Admin prints PDF sheet of Code128 labels and applies to each machine.

### Flow B: Transfer BKK → YGN
1. **Bangkok:** admin creates a `shipment` (dest = YGN_WH), assigns units → each unit gets `DISPATCHED` movement (location = IN_TRANSIT). Manifest PDF accompanies the shipment.
2. **Yangon (PWA, possibly offline):** staff opens "Receive Shipment", enters shipment code → app uses cached manifest (loaded last time online).
3. Staff scans each barcode; app validates serial against manifest, writes `RECEIVED` movement (location = YGN_WH). Missing scans flagged.
4. Offline writes queue in IndexedDB and replay on reconnect (wifi or 4G).

### Flow C: Sale at Yangon
1. Staff opens "New Sale", picks/creates customer, scans unit barcode.
2. App verifies unit state = `IN_YGN`; otherwise error ("in transit / sold / in service").
3. Confirm → `SOLD` movement (to_location = CUSTOMER). Sale receipt PDF generated.
4. Offline-safe via queue.

### Flow D: Service return & redeploy
1. Customer returns unit → staff scans → creates `service_ticket` + `RETURNED` movement (location = SERVICE).
2. Technician closes ticket → `SERVICED` movement (location = YGN_WH). Unit is saleable again.
3. Service history queryable by serial.

### Flow E: HQ dashboard (Bangkok)
- Stock-on-hand per location (derived from latest movement per unit).
- In-transit shipments + ageing flags (e.g., >14 days = red).
- Sales this month, by branch / by product.
- Search by serial → full lifecycle ledger.

### Conflict & error handling
- **Duplicate scan offline:** PWA de-dupes by `(unit_id, event_type, timestamp)`; backend enforces a unique `idempotency_key` per movement.
- **Stale local state:** if PWA thinks unit is `IN_YGN` but server says `SOLD`, server returns 409 → PWA refreshes that unit and shows "already sold by [user] at [time]."
- **Lost label:** admin reprints by serial; barcode unchanged.

## 6. Security & Non-Functional

### Auth
- JWT (existing). Access 30 min; refresh 7 days. Refresh token stored in `httpOnly` cookie (not localStorage) for XSS safety.
- Roles: `admin`, `staff`, `technician` (technician = staff + close-ticket permission).
- Route guards via existing `deps.py`. All business logic in `crud.py` (per CLAUDE.md).

### Data integrity
- Append-only `unit_movement` (DB-level revoke).
- Server-side state machine enforced on every insert.
- Idempotency keys on every offline-sourced write.
- Multi-row writes wrapped in DB transactions.

### Offline-mode safety
- IndexedDB queue encrypted at rest with Web Crypto API using a key derived from the session.
- Queue capped at 7 days; older items flagged for admin review on replay.
- Auto-logout after 12 h inactivity even offline.

### Transport & deployment
- HTTPS only (Traefik + Let's Encrypt — already in template).
- CORS locked to production frontend domain.
- Rate limit auth endpoints: 5 attempts / 15 min / IP.
- Secrets via env vars; `SECRET_KEY` rotated annually.
- Daily `pg_dump` to S3-compatible storage, 30-day retention; monthly restore test.

### Audit
- Every movement has `actor_user_id`, `occurred_at`, optional `notes`.
- Admin audit-log view filters by user / date / event type.

## 7. Testing Strategy

| Layer | Tool | Coverage focus |
|---|---|---|
| Backend unit | pytest | State-machine transitions (every legal + illegal pair); idempotency; role guards |
| Backend integration | pytest + test DB | crud.py + Alembic migrations apply cleanly |
| Frontend E2E | Playwright | Three critical paths: receive shipment, sell unit, sync after offline |
| Offline test | Playwright with network blocked | Queue + replay correctness |

Target: 80%+ coverage on `crud.py` and route handlers.

## 8. Out of Scope (v1)

Explicit YAGNI per CLAUDE.md §2:

- Multi-currency / FX rates (THB only).
- Spare parts / accessories inventory.
- Customer self-service portal.
- Native mobile app (PWA suffices).
- Real-time multi-user live updates (sync-on-reconnect is enough).
- Accounting / tax integration.
- Multi-language UI.

## 9. Rollout & Training

- Pilot with one full BKK→YGN shipment cycle before full cutover.
- User training (1 day per office) covering: scanning, offline indicator, what to do when a scan is rejected, reprinting labels.
- Parallel run with existing tracking (spreadsheet or whatever's current) for 1 month before retiring it.

## 10. Open Questions (defer to implementation plan)

- Where exactly is "Bangkok cloud" hosted? (AWS Singapore? DigitalOcean? Neon managed Postgres?) — affects latency from Yangon.
- Are sale receipts a legal/tax document in either jurisdiction? If so, additional fields may be required.
- Who currently issues serial numbers — supplier or CastraNova? If supplier, do we capture *both* their serial and our internal serial?
