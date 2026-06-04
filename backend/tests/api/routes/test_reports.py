import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.models import (
    Channel,
    CustomerCreate,
    Location,
    ProductCreate,
    ProjectCreate,
    ProjectPull,
    ProjectPullCreate,
    ProjectPullFulfillLine,
    ProjectPullLine,
    ProjectPullLineCreate,
    ReceivePiece,
    Sale,
    SaleLineInput,
    SaleLineKind,
    ServiceTicket,
    SupplierCreate,
    TrackingMode,
)

PREFIX = settings.API_V1_STR

# The month every "in-window" record is pinned into for the hand-calc tests.
TARGET = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)


def _channel(report: dict[str, Any], name: str) -> dict[str, Any]:
    return next(c for c in report["channels"] if c["channel"] == name)


def _pull_lines(db: Session, pull_id: uuid.UUID) -> list[ProjectPullLine]:
    return list(
        db.exec(
            select(ProjectPullLine).where(ProjectPullLine.project_pull_id == pull_id)
        ).all()
    )


@pytest.fixture
def seed(db: Session) -> Iterator[dict[str, Any]]:
    """Customer + supplier + one SERIALIZED product (units received on demand) and
    a fresh QUANTITY product per channel so each channel's FIFO cost is isolated
    and hand-calculable. Yields the ids/helpers the tests need."""
    if not db.exec(select(Location).where(Location.code == "YGN_WH")).first():
        crud.seed_locations(session=db)
    admin = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert admin is not None
    customer = crud.create_customer(
        session=db, customer_in=CustomerCreate(name="Report Cust")
    )
    supplier = crud.create_supplier(
        session=db, supplier_in=SupplierCreate(name="Acme")
    )
    serialized = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"SER-{uuid.uuid4().hex[:8]}",
            model_name="Machine",
            tracking_mode=TrackingMode.SERIALIZED,
            retail_price_thb="500.00",
            repair_price_thb="50.00",
        ),
    )

    def make_part(retail: str, repair: str, batches: list[tuple[int, str]]) -> Any:
        product = crud.create_product(
            session=db,
            product_in=ProductCreate(
                sku=f"QTY-{uuid.uuid4().hex[:8]}",
                model_name="Part",
                tracking_mode=TrackingMode.QUANTITY,
                retail_price_thb=retail,
                repair_price_thb=repair,
            ),
        )
        for qty, cost in batches:
            crud.receive_quantity(
                session=db,
                product_id=product.id,
                supplier_id=supplier.id,
                received_qty=qty,
                purchase_cost_thb=Decimal(cost),
                idempotency_key=uuid.uuid4(),
                received_by_user_id=admin.id,
            )
        return product

    def make_unit(cost: str) -> str:
        units = crud.receive_serialized(
            session=db,
            product_id=serialized.id,
            supplier_id=supplier.id,
            pieces=[
                ReceivePiece(
                    supplier_serial=f"S-{uuid.uuid4().hex[:8]}",
                    purchase_cost_thb=Decimal(cost),
                )
            ],
            idempotency_key=uuid.uuid4(),
            received_by_user_id=admin.id,
        )
        return units[0].castranova_barcode

    yield {
        "admin": admin,
        "customer": customer,
        "supplier": supplier,
        "serialized": serialized,
        "make_part": make_part,
        "make_unit": make_unit,
    }


def _pin_sale(db: Session, sale_id: uuid.UUID, when: datetime) -> None:
    row = db.get(Sale, sale_id)
    assert row is not None
    row.sold_at = when
    db.add(row)
    db.commit()


def _pin_ticket(db: Session, ticket_id: uuid.UUID, when: datetime) -> None:
    row = db.get(ServiceTicket, ticket_id)
    assert row is not None
    row.closed_at = when
    db.add(row)
    db.commit()


def _pin_pull(db: Session, pull_id: uuid.UUID, when: datetime) -> None:
    row = db.get(ProjectPull, pull_id)
    assert row is not None
    row.fulfilled_at = when
    db.add(row)
    db.commit()


def test_mixed_channel_hand_calc(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed: dict[str, Any],
) -> None:
    admin = seed["admin"]
    customer = seed["customer"]

    # --- SALE: one UNIT (cost 100, retail 500) + one PART (qty 5 over 3@10+4@12).
    sale_part = seed["make_part"]("100.00", "20.00", [(3, "10.00"), (4, "12.00")])
    sale_barcode = seed["make_unit"]("100.00")
    sale = crud.create_sale(
        session=db,
        customer_id=customer.id,
        lines=[
            SaleLineInput(line_kind=SaleLineKind.UNIT, castranova_barcode=sale_barcode),
            SaleLineInput(line_kind=SaleLineKind.PART, sku=sale_part.sku, quantity=5),
        ],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=admin.id,
    )
    _pin_sale(db, sale.id, TARGET)
    # revenue = 500 (unit retail) + 5*100 (part retail) = 1000
    # cogs    = 100 (unit) + (3*10 + 2*12 = 54) = 154
    sale_rev = Decimal("1000.00")
    sale_cogs = Decimal("154.00")

    # --- MAINTENANCE: ticket, one part qty 2 @ repair 20, FIFO over 3@10+4@12.
    maint_part = seed["make_part"]("100.00", "20.00", [(3, "10.00"), (4, "12.00")])
    ticket = crud.open_service_ticket(
        session=db,
        customer_id=customer.id,
        issue="noisy",
        idempotency_key=uuid.uuid4(),
        created_by_user_id=admin.id,
    )
    crud.add_service_ticket_part(
        session=db, ticket_id=ticket.id, sku=maint_part.sku, quantity=2
    )
    crud.close_service_ticket(session=db, ticket_id=ticket.id, actor_user_id=admin.id)
    _pin_ticket(db, ticket.id, TARGET)
    # revenue = 2 * 20 = 40 ; cogs = 2 @ 10 (oldest batch) = 20
    maint_rev = Decimal("40.00")
    maint_cogs = Decimal("20.00")

    # --- PROJECT: pull one UNIT (cost 100) + one PART (qty 3 over 3@10+4@12).
    proj_part = seed["make_part"]("100.00", "20.00", [(3, "10.00"), (4, "12.00")])
    proj_barcode = seed["make_unit"]("100.00")
    project = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"PRJ-{uuid.uuid4().hex[:8]}",
            name="Site",
            customer_id=customer.id,
        ),
    )
    pull = crud.create_project_pull(
        session=db,
        pull_in=ProjectPullCreate(
            project_id=project.id,
            lines=[
                ProjectPullLineCreate(
                    line_kind=SaleLineKind.UNIT,
                    product_id=seed["serialized"].id,
                    unit_serial=proj_barcode,
                ),
                ProjectPullLineCreate(
                    line_kind=SaleLineKind.PART,
                    product_id=proj_part.id,
                    requested_qty=3,
                ),
            ],
        ),
        created_by_user_id=admin.id,
    )
    line_ids = {ln.line_kind: ln.id for ln in _pull_lines(db, pull.id)}
    crud.fulfill_project_pull(
        session=db,
        pull_id=pull.id,
        fulfill_lines=[
            ProjectPullFulfillLine(line_id=line_ids[SaleLineKind.UNIT], fulfilled_qty=1),
            ProjectPullFulfillLine(line_id=line_ids[SaleLineKind.PART], fulfilled_qty=3),
        ],
        actor_user_id=admin.id,
    )
    _pin_pull(db, pull.id, TARGET)
    # revenue = 0 ; cogs = 100 (unit) + 3 @ 10 = 30 => 130
    proj_rev = Decimal("0.00")
    proj_cogs = Decimal("130.00")

    r = client.get(
        f"{PREFIX}/reports/channel-margin?month=2026-03",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["month"] == "2026-03"

    sale_row = _channel(report, "SALE")
    assert Decimal(sale_row["revenue_thb"]) == sale_rev
    assert Decimal(sale_row["cogs_thb"]) == sale_cogs
    assert Decimal(sale_row["margin_thb"]) == sale_rev - sale_cogs

    maint_row = _channel(report, "MAINTENANCE")
    assert Decimal(maint_row["revenue_thb"]) == maint_rev
    assert Decimal(maint_row["cogs_thb"]) == maint_cogs
    assert Decimal(maint_row["margin_thb"]) == maint_rev - maint_cogs

    proj_row = _channel(report, "PROJECT")
    assert Decimal(proj_row["revenue_thb"]) == proj_rev
    assert Decimal(proj_row["cogs_thb"]) == proj_cogs
    assert Decimal(proj_row["margin_thb"]) == proj_rev - proj_cogs

    assert Decimal(report["total_revenue_thb"]) == sale_rev + maint_rev + proj_rev
    assert Decimal(report["total_cogs_thb"]) == sale_cogs + maint_cogs + proj_cogs
    assert Decimal(report["total_margin_thb"]) == (
        (sale_rev + maint_rev + proj_rev) - (sale_cogs + maint_cogs + proj_cogs)
    )


def test_channels_always_three_rows_in_order(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    r = client.get(
        f"{PREFIX}/reports/channel-margin?month=2026-01",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    channels = [c["channel"] for c in r.json()["channels"]]
    assert channels == [Channel.SALE, Channel.MAINTENANCE, Channel.PROJECT]


def test_empty_month_all_zero(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    r = client.get(
        f"{PREFIX}/reports/channel-margin?month=2026-02",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    report = r.json()
    for row in report["channels"]:
        assert Decimal(row["revenue_thb"]) == Decimal("0.00")
        assert Decimal(row["cogs_thb"]) == Decimal("0.00")
        assert Decimal(row["margin_thb"]) == Decimal("0.00")
    assert Decimal(report["total_revenue_thb"]) == Decimal("0.00")
    assert Decimal(report["total_cogs_thb"]) == Decimal("0.00")
    assert Decimal(report["total_margin_thb"]) == Decimal("0.00")


def test_adjacent_month_not_counted(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed: dict[str, Any],
) -> None:
    admin = seed["admin"]
    customer = seed["customer"]
    part = seed["make_part"]("100.00", "20.00", [(5, "10.00")])
    sale = crud.create_sale(
        session=db,
        customer_id=customer.id,
        lines=[SaleLineInput(line_kind=SaleLineKind.PART, sku=part.sku, quantity=2)],
        idempotency_key=uuid.uuid4(),
        created_by_user_id=admin.id,
    )
    # Pin into August; query July (a month nothing else in this session writes
    # to) -> the August sale must not be counted.
    _pin_sale(db, sale.id, datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc))
    r = client.get(
        f"{PREFIX}/reports/channel-margin?month=2026-07",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    assert Decimal(_channel(r.json(), "SALE")["revenue_thb"]) == Decimal("0.00")


def test_staff_forbidden(
    client: TestClient,
    staff_token_headers: dict[str, str],
) -> None:
    r = client.get(
        f"{PREFIX}/reports/channel-margin?month=2026-03",
        headers=staff_token_headers,
    )
    assert r.status_code == 403


def test_admin_allowed(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    r = client.get(
        f"{PREFIX}/reports/channel-margin?month=2026-03",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200


@pytest.mark.parametrize("month", ["2026-13", "2026/03", "nonsense", "2026-00", "26-03"])
def test_bad_month_param_422(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    month: str,
) -> None:
    r = client.get(
        f"{PREFIX}/reports/channel-margin?month={month}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 422


def test_short_pull_counted(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    seed: dict[str, Any],
) -> None:
    admin = seed["admin"]
    customer = seed["customer"]
    # Request 5 but only 3 in stock -> SHORT, consumes 3 @ 10 = 30 COGS.
    part = seed["make_part"]("100.00", "20.00", [(3, "10.00")])
    project = crud.create_project(
        session=db,
        project_in=ProjectCreate(
            code=f"PRJ-{uuid.uuid4().hex[:8]}",
            name="Short Site",
            customer_id=customer.id,
        ),
    )
    pull = crud.create_project_pull(
        session=db,
        pull_in=ProjectPullCreate(
            project_id=project.id,
            lines=[
                ProjectPullLineCreate(
                    line_kind=SaleLineKind.PART,
                    product_id=part.id,
                    requested_qty=5,
                ),
            ],
        ),
        created_by_user_id=admin.id,
    )
    line_id = _pull_lines(db, pull.id)[0].id
    # Fulfill 3 of the 5 requested -> partial consumption -> line+pull SHORT.
    settled = crud.fulfill_project_pull(
        session=db,
        pull_id=pull.id,
        fulfill_lines=[ProjectPullFulfillLine(line_id=line_id, fulfilled_qty=3)],
        actor_user_id=admin.id,
    )
    assert settled.state.value == "SHORT"
    # Dedicated month so the session-scoped DB's other PROJECT activity (the
    # hand-calc test pins to March) doesn't float this assertion.
    _pin_pull(db, pull.id, datetime(2026, 9, 10, tzinfo=timezone.utc))

    r = client.get(
        f"{PREFIX}/reports/channel-margin?month=2026-09",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.text
    proj_row = _channel(r.json(), "PROJECT")
    # 3 @ 10 consumed = 30 COGS, revenue 0.
    assert Decimal(proj_row["cogs_thb"]) == Decimal("30.00")
    assert Decimal(proj_row["revenue_thb"]) == Decimal("0.00")
