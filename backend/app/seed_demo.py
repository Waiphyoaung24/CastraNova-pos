"""Seed a coherent demo dataset for manual testing.

Wipes domain data (keeping users + locations), then drives the real crud
operations so every derived ledger — part_batch, unit, *_movement, cost_line,
price_change — is produced the same way production produces it. Nothing is
INSERTed straight into an append-only table, so stock totals reconcile against
their own movements and FIFO costing is real.

Run:  docker compose exec -T backend python app/seed_demo.py
"""

import uuid
from decimal import Decimal

from sqlalchemy import create_engine, text
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.db import engine
from app.models import (
    AdjustmentTarget,
    CustomerCreate,
    CustomerType,
    NotificationChannel,
    NotificationEvent,
    NotificationLog,
    NotificationPreference,
    NotificationStatus,
    OverrideTargetKind,
    PricingOverrideCreate,
    Product,
    ProductCreate,
    ProductUpdate,
    ProjectCreate,
    ProjectPullCreate,
    ProjectPullFulfillLine,
    ProjectPullLine,
    ProjectPullLineCreate,
    ReceivePiece,
    SaleLineInput,
    SaleLineKind,
    ServiceTicketPartCreate,
    StockAdjustmentCreate,
    SupplierCreate,
    SyncReviewItemCreate,
    SyncReviewReason,
    TrackingMode,
    Unit,
    User,
    UserCreate,
    UserRole,
)

# Keep these: users hold the login you are testing with, locations are
# infrastructure that init_db seeds, alembic_version is schema state.
KEEP = {"user", "location", "alembic_version"}


def key() -> uuid.UUID:
    return uuid.uuid4()


def require_local() -> None:
    """Refuse to run anywhere but local.

    This file ships inside the backend image (Dockerfile COPYs ./backend/app),
    and wipe() truncates every domain table on the *admin* connection —
    deliberately bypassing the app role's inability to TRUNCATE the append-only
    ledgers (hardening spec 4.2.3). Without this gate the production container
    would carry a one-command wipe of production.
    """
    if settings.ENVIRONMENT != "local":
        raise SystemExit(
            f"seed_demo refuses to run with ENVIRONMENT={settings.ENVIRONMENT!r}. "
            "It wipes every domain table; it is a local-only tool."
        )


def wipe() -> None:
    # Admin engine: the app role deliberately cannot TRUNCATE the append-only
    # ledgers (hardening spec 4.2.3).
    admin_engine = create_engine(str(settings.SQLALCHEMY_ADMIN_DATABASE_URI))
    with Session(admin_engine) as s:
        rows = s.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).all()
        names = [r[0] for r in rows if r[0] not in KEEP]
        quoted = ", ".join(f'"{n}"' for n in names)
        s.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
        s.commit()
    print(f"wiped {len(names)} domain tables (kept {', '.join(sorted(KEEP))})")


def seed(s: Session) -> None:
    admin = s.exec(select(User).where(User.is_superuser)).first()
    if not admin:
        raise SystemExit("no superuser — run `python app/initial_data.py` first")
    aid = admin.id

    # The wipe drops the rows init_db seeds; restore the configurable thresholds
    # (override deviation %, holding-period days) before anything reads them.
    crud.seed_system_settings(session=s)
    print("system settings: restored defaults")

    # --- users -------------------------------------------------------------
    users = []
    for email, name, role in [
        ("bkk.admin@example.com", "Somchai (BKK Admin)", UserRole.BKK_ADMIN),
        ("ygn.staff@example.com", "Aung (YGN Staff)", UserRole.YGN_STAFF),
        ("ygn.staff2@example.com", "Hla (YGN Staff)", UserRole.YGN_STAFF),
    ]:
        existing = s.exec(select(User).where(User.email == email)).first()
        if existing:
            users.append(existing)
            continue
        users.append(
            crud.create_user(
                session=s,
                user_create=UserCreate(
                    email=email, password="changethis", full_name=name, role=role
                ),
            )
        )
    print(f"users: {len(users)} staff/admin (+ {admin.email})")

    # --- suppliers ---------------------------------------------------------
    suppliers = [
        crud.create_supplier(
            session=s, supplier_in=SupplierCreate(name=n, country=c, contact=ct)
        )
        for n, c, ct in [
            ("Shenzhen Parts Co", "CN", "sales@szparts.example"),
            ("Bangkok Distribution", "TH", "+66 2 555 0100"),
            ("Yangon Supply House", "MM", "contact@ygnsupply.example"),
        ]
    ]
    print(f"suppliers: {len(suppliers)}")

    # --- customers ---------------------------------------------------------
    customers = [
        crud.create_customer(
            session=s,
            customer_in=CustomerCreate(name=n, country=c, contact=ct, type=t),
        )
        for n, c, ct, t in [
            ("Thiri Trading", "MM", "+95 9 555 0101", CustomerType.DEALER),
            ("Ko Min Electronics", "MM", "komin@example.com", CustomerType.DEALER),
            ("Walk-in Customer", "MM", None, CustomerType.END_CUSTOMER),
        ]
    ]
    print(f"customers: {len(customers)}")

    # --- products ----------------------------------------------------------
    # 3 QUANTITY (parts, FIFO-consumed) + 3 SERIALIZED (units, barcode-tracked)
    # + 1 retired, so the inactive-product guard is testable out of the box.
    qty_specs = [
        ("CBL-USBC-2M", "USB-C Cable 2m", "Anker", "Cable", "180.00", "0.00"),
        ("SCR-IP15-GLS", "iPhone 15 Screen", "Apple", "Screen", "4500.00", "3800.00"),
        ("BAT-SG23-STD", "Galaxy S23 Battery", "Samsung", "Battery", "1900.00", "1500.00"),
    ]
    ser_specs = [
        ("IP15P-256-BLK", "iPhone 15 Pro 256GB", "Apple", "Smartphone", "42000.00", "0.00"),
        ("SG23U-512-GRN", "Galaxy S23 Ultra 512GB", "Samsung", "Smartphone", "38000.00", "0.00"),
        ("PIX8-128-OBS", "Pixel 8 128GB", "Google", "Smartphone", "24000.00", "0.00"),
    ]
    qty_products = [
        crud.create_product(
            session=s,
            product_in=ProductCreate(
                sku=sku,
                model_name=m,
                brand=b,
                category=c,
                tracking_mode=TrackingMode.QUANTITY,
                retail_price_thb=Decimal(r),
                repair_price_thb=Decimal(rp),
                default_min_stock_level=5,
            ),
        )
        for sku, m, b, c, r, rp in qty_specs
    ]
    ser_products = [
        crud.create_product(
            session=s,
            product_in=ProductCreate(
                sku=sku,
                model_name=m,
                brand=b,
                category=c,
                tracking_mode=TrackingMode.SERIALIZED,
                retail_price_thb=Decimal(r),
                repair_price_thb=Decimal(rp),
                default_min_stock_level=2,
            ),
        )
        for sku, m, b, c, r, rp in ser_specs
    ]
    # Created active on purpose: the guard blocks receiving into an inactive
    # product, so stock must land while it is still live. It is retired below,
    # after its batch exists — which is also the real-world ordering.
    retired = crud.create_product(
        session=s,
        product_in=ProductCreate(
            sku="OLD-CBL-MICRO",
            model_name="Micro-USB Cable (discontinued)",
            brand="Generic",
            category="Cable",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb=Decimal("90.00"),
            repair_price_thb=Decimal("0.00"),
        ),
    )
    print(f"products: {len(qty_products)} QUANTITY, {len(ser_products)} SERIALIZED, 1 retired")

    # --- projects ----------------------------------------------------------
    projects = [
        crud.create_project(
            session=s,
            project_in=ProjectCreate(
                code=code, name=name, customer_id=cust.id, budget_thb=Decimal(b)
            ),
        )
        for code, name, cust, b in [
            ("PRJ-2026-01", "Thiri Store Refit", customers[0], "150000.00"),
            ("PRJ-2026-02", "Ko Min Bulk Order", customers[1], "80000.00"),
            ("PRJ-2026-03", "Internal Spares Pool", customers[0], "25000.00"),
        ]
    ]
    print(f"projects: {len(projects)}")

    # --- receive QUANTITY: two batches each, so FIFO has something to order --
    batches = 0
    for i, p in enumerate(qty_products):
        for j, (q, cost) in enumerate([(40, "60.00"), (30, "72.00")]):
            crud.receive_quantity(
                session=s,
                product_id=p.id,
                supplier_id=suppliers[i % len(suppliers)].id,
                received_qty=q,
                purchase_cost_thb=Decimal(cost),
                idempotency_key=key(),
                received_by_user_id=aid,
                supplier_batch_ref=f"PO-{2026}{i}{j}",
            )
            batches += 1
    # Retired product gets stock too — it is the documented "drain via Adjust" case.
    crud.receive_quantity(
        session=s,
        product_id=retired.id,
        supplier_id=suppliers[0].id,
        received_qty=10,
        purchase_cost_thb=Decimal("30.00"),
        idempotency_key=key(),
        received_by_user_id=aid,
    )
    # ...received while active, then retired — the real-world ordering.
    crud.update_product(
        session=s,
        db_product=retired,
        product_in=ProductUpdate(is_active=False),
        changed_by_user_id=aid,
    )
    print(f"part batches: {batches + 1} (2 per QUANTITY product, for FIFO + 1 retired)")

    # --- receive SERIALIZED: 3 units each ----------------------------------
    units = 0
    for i, p in enumerate(ser_products):
        pieces = [
            ReceivePiece(
                supplier_serial=f"{p.sku}-SN{n:03d}",
                purchase_cost_thb=Decimal("30000.00") - Decimal(n * 100),
            )
            for n in range(1, 4)
        ]
        crud.receive_serialized(
            session=s,
            product_id=p.id,
            supplier_id=suppliers[i % len(suppliers)].id,
            pieces=pieces,
            idempotency_key=key(),
            received_by_user_id=aid,
        )
        units += len(pieces)
    print(f"units: {units} (3 per SERIALIZED product)")

    barcodes = [u.castranova_barcode for u in s.exec(select(Unit)).all()]

    # --- price change (populates price_change) ------------------------------
    crud.update_product(
        session=s,
        db_product=qty_products[0],
        product_in=ProductUpdate(retail_price_thb=Decimal("195.00")),
        changed_by_user_id=aid,
    )
    crud.update_product(
        session=s,
        db_product=qty_products[1],
        product_in=ProductUpdate(retail_price_thb=Decimal("4700.00")),
        changed_by_user_id=aid,
    )
    print("price changes: 2")

    # --- pricing overrides: auto-approved + pending -------------------------
    overrides = [
        crud.create_pricing_override(
            session=s,
            override_in=PricingOverrideCreate(
                target_kind=OverrideTargetKind.SALE_LINE,
                product_id=qty_products[0].id,
                requested_price_thb=Decimal("190.00"),
                reason="Loyal dealer, small discount",
            ),
            created_by_user_id=aid,
        ),
        crud.create_pricing_override(
            session=s,
            override_in=PricingOverrideCreate(
                target_kind=OverrideTargetKind.SALE_LINE,
                product_id=ser_products[0].id,
                requested_price_thb=Decimal("30000.00"),
                reason="Bulk deal — needs admin sign-off",
            ),
            created_by_user_id=aid,
        ),
        crud.create_pricing_override(
            session=s,
            override_in=PricingOverrideCreate(
                target_kind=OverrideTargetKind.SERVICE_TICKET_PART,
                product_id=qty_products[1].id,
                requested_price_thb=Decimal("3000.00"),
                reason="Warranty goodwill repair",
            ),
            created_by_user_id=aid,
        ),
    ]
    print(f"pricing overrides: {len(overrides)} ({', '.join(o.state.value for o in overrides)})")

    # --- sales: PART lines, UNIT lines, and a mixed one ---------------------
    sales = [
        crud.create_sale(
            session=s,
            customer_id=customers[0].id,
            lines=[
                SaleLineInput(line_kind=SaleLineKind.PART, sku=qty_products[0].sku, quantity=3),
                SaleLineInput(line_kind=SaleLineKind.PART, sku=qty_products[2].sku, quantity=2),
            ],
            idempotency_key=key(),
            created_by_user_id=aid,
        ),
        crud.create_sale(
            session=s,
            customer_id=customers[1].id,
            lines=[
                SaleLineInput(line_kind=SaleLineKind.UNIT, castranova_barcode=barcodes[0])
            ],
            idempotency_key=key(),
            created_by_user_id=aid,
        ),
        crud.create_sale(
            session=s,
            customer_id=customers[2].id,
            lines=[
                SaleLineInput(line_kind=SaleLineKind.UNIT, castranova_barcode=barcodes[3]),
                SaleLineInput(line_kind=SaleLineKind.PART, sku=qty_products[0].sku, quantity=1),
            ],
            idempotency_key=key(),
            created_by_user_id=aid,
        ),
    ]
    print(f"sales: {len(sales)} (PART-only, UNIT-only, mixed)")

    # --- service tickets ----------------------------------------------------
    tickets = [
        crud.record_service_ticket(
            session=s,
            customer_id=c.id,
            issue=issue,
            parts=[ServiceTicketPartCreate(sku=sku, quantity=q)],
            idempotency_key=key(),
            actor_user_id=aid,
            resolution=res,
        )
        for c, issue, sku, q, res in [
            (customers[0], "Cracked screen after drop", qty_products[1].sku, 1, "Screen replaced"),
            (customers[1], "Battery drains in 2 hours", qty_products[2].sku, 1, "Battery swapped"),
            (customers[2], "Charging port loose", qty_products[0].sku, 2, "Cable + port cleaned"),
        ]
    ]
    print(f"service tickets: {len(tickets)}")

    # --- project pulls: one fulfilled, two pending --------------------------
    pulls = [
        crud.create_project_pull(
            session=s,
            pull_in=ProjectPullCreate(
                project_id=projects[0].id,
                admin_notes="Initial refit kit",
                lines=[
                    ProjectPullLineCreate(
                        line_kind=SaleLineKind.PART,
                        product_id=qty_products[0].id,
                        requested_qty=5,
                    ),
                ],
            ),
            created_by_user_id=aid,
        ),
        crud.create_project_pull(
            session=s,
            pull_in=ProjectPullCreate(
                project_id=projects[1].id,
                admin_notes="Bulk handset allocation",
                lines=[
                    ProjectPullLineCreate(
                        line_kind=SaleLineKind.UNIT,
                        product_id=ser_products[1].id,
                        unit_serial=f"{ser_products[1].sku}-SN002",
                    ),
                ],
            ),
            created_by_user_id=aid,
        ),
        crud.create_project_pull(
            session=s,
            pull_in=ProjectPullCreate(
                project_id=projects[2].id,
                admin_notes="Spares top-up",
                lines=[
                    ProjectPullLineCreate(
                        line_kind=SaleLineKind.PART,
                        product_id=qty_products[2].id,
                        requested_qty=4,
                    ),
                ],
            ),
            created_by_user_id=aid,
        ),
    ]
    pull0_lines = s.exec(
        select(ProjectPullLine).where(ProjectPullLine.project_pull_id == pulls[0].id)
    ).all()
    crud.fulfill_project_pull(
        session=s,
        pull_id=pulls[0].id,
        fulfill_lines=[
            ProjectPullFulfillLine(line_id=ln.id, fulfilled_qty=ln.requested_qty or 1)
            for ln in pull0_lines
        ],
        actor_user_id=aid,
    )
    print(f"project pulls: {len(pulls)} (1 fulfilled, 2 pending)")

    # --- stock adjustments: +qty, -qty, and a unit write-off ----------------
    adjustments = [
        crud.create_stock_adjustment(
            session=s,
            adj_in=StockAdjustmentCreate(
                target_kind=AdjustmentTarget.QUANTITY,
                sku=qty_products[0].sku,
                quantity_delta=12,
                purchase_cost_thb=Decimal("58.00"),
                reason="Recount — found extra box in back room",
                idempotency_key=key(),
            ),
            created_by_user_id=aid,
        ),
        crud.create_stock_adjustment(
            session=s,
            adj_in=StockAdjustmentCreate(
                target_kind=AdjustmentTarget.QUANTITY,
                sku=qty_products[1].sku,
                quantity_delta=-2,
                reason="Damaged in handling — written off",
                idempotency_key=key(),
            ),
            created_by_user_id=aid,
        ),
        crud.create_stock_adjustment(
            session=s,
            adj_in=StockAdjustmentCreate(
                target_kind=AdjustmentTarget.UNIT,
                castranova_barcode=barcodes[6],
                reason="DOA from supplier — RMA'd",
                idempotency_key=key(),
            ),
            created_by_user_id=aid,
        ),
        # Drain the retired product's residual stock — the documented path that
        # is deliberately NOT blocked by the inactive-product guard.
        crud.create_stock_adjustment(
            session=s,
            adj_in=StockAdjustmentCreate(
                target_kind=AdjustmentTarget.QUANTITY,
                sku=retired.sku,
                quantity_delta=-4,
                reason="Draining discontinued stock",
                idempotency_key=key(),
            ),
            created_by_user_id=aid,
        ),
    ]
    print(f"stock adjustments: {len(adjustments)} (+qty, -qty, unit write-off, retired drain)")

    # --- sync review queue --------------------------------------------------
    items = [
        crud.create_sync_review_item(
            session=s,
            data=SyncReviewItemCreate(
                idempotency_key=key(),
                mutation_kind=kind,
                payload=payload,
                reason=reason,
            ),
            submitted_by_user_id=uid,
        )
        for kind, payload, reason, uid in [
            ("sale", {"sku": "CBL-USBC-2M", "qty": 2}, SyncReviewReason.STALE, users[1].id),
            ("sale", {"barcode": "unknown-123"}, SyncReviewReason.CONFLICT, users[2].id),
            ("service_ticket", {"sku": "SCR-IP15-GLS", "qty": 1}, SyncReviewReason.STALE, aid),
        ]
    ]
    print(f"sync review items: {len(items)}")

    # --- notifications: prefs + log ----------------------------------------
    prefs = 0
    for u in [admin, users[0]]:
        for ev in [NotificationEvent.LOW_STOCK, NotificationEvent.OVERRIDE_PENDING]:
            s.add(
                NotificationPreference(
                    user_id=u.id, channel=NotificationChannel.LINE, event_type=ev
                )
            )
            prefs += 1
    logs = [
        NotificationLog(
            channel=NotificationChannel.LINE,
            event_type=NotificationEvent.LOW_STOCK,
            target_user_id=aid,
            payload={"sku": "BAT-SG23-STD", "remaining": 3},
            status=NotificationStatus.SENT,
            attempts=1,
        ),
        NotificationLog(
            channel=NotificationChannel.LINE,
            event_type=NotificationEvent.OVERRIDE_PENDING,
            target_user_id=aid,
            payload={"override": "bulk deal"},
            status=NotificationStatus.FAILED,
            attempts=3,
            last_error="LINE API timeout",
        ),
        NotificationLog(
            channel=NotificationChannel.VIBER,
            event_type=NotificationEvent.PULL_FULFILLED,
            target_user_id=users[0].id,
            payload={"pull": "PRJ-2026-01"},
            status=NotificationStatus.SENT,
            attempts=1,
        ),
    ]
    for lg in logs:
        s.add(lg)
    s.commit()
    print(f"notifications: {prefs} preferences, {len(logs)} log rows")


def report(s: Session) -> None:
    rows = s.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    ).all()
    print("\n--- row counts ---")
    empty = []
    for (t,) in rows:
        if t == "alembic_version":
            continue
        n = s.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one()
        print(f"  {t:24} {n}")
        if n == 0:
            empty.append(t)
    if empty:
        print(f"\nSTILL EMPTY: {', '.join(empty)}")
    else:
        print("\nevery domain table has rows.")


if __name__ == "__main__":
    require_local()
    wipe()
    with Session(engine) as s:
        seed(s)
        report(s)
    print("\ndone. log in as admin@example.com / changethis")
