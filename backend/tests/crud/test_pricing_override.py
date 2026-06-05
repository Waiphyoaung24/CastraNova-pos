import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app import crud
from app.models import (
    OverrideState,
    OverrideTargetKind,
    PricingOverrideCreate,
    PricingOverrideRequest,
    ProductCreate,
    TrackingMode,
    UserCreate,
    UserRole,
)


def _set_threshold(db: Session, pct: float) -> None:
    crud.set_setting(
        session=db, key=crud.OVERRIDE_THRESHOLD_KEY, value=pct
    )


def _admin(db: Session) -> uuid.UUID:
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=f"ovr-{uuid.uuid4()}@example.com",
            password="changethis123",
            role=UserRole.BKK_ADMIN,
        ),
    )
    return user.id


def _product(db: Session, *, retail: str = "1000.00", repair: str = "300.00") -> uuid.UUID:
    product = crud.create_product(
        session=db,
        product_in=ProductCreate(
            sku=f"OVR-{uuid.uuid4().hex[:8]}",
            model_name="Override Test",
            brand="Acme",
            category="compressor",
            tracking_mode=TrackingMode.QUANTITY,
            retail_price_thb=Decimal(retail),
            repair_price_thb=Decimal(repair),
        ),
    )
    return product.id


def test_pricing_override_request_persists(db: Session) -> None:
    actor = _admin(db)
    row = PricingOverrideRequest(
        target_kind=OverrideTargetKind.SALE_LINE,
        product_id=_product(db),
        default_price_thb=Decimal("1000.00"),
        requested_price_thb=Decimal("900.00"),
        deviation_pct=Decimal("10.0000"),
        reason="loyal customer",
        state=OverrideState.PENDING,
        created_by_user_id=actor,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    fetched = db.exec(
        select(PricingOverrideRequest).where(
            PricingOverrideRequest.id == row.id
        )
    ).first()
    assert fetched is not None
    assert fetched.target_kind == OverrideTargetKind.SALE_LINE
    assert fetched.requested_price_thb == Decimal("900.00")
    assert fetched.state == OverrideState.PENDING
    assert fetched.created_at is not None
    assert fetched.decided_at is None


def test_create_override_auto_approves_within_threshold(db: Session) -> None:
    _set_threshold(db, 5.0)
    actor = _admin(db)
    pid = _product(db, retail="1000.00")
    ovr = crud.create_pricing_override(
        session=db,
        override_in=PricingOverrideCreate(
            target_kind=OverrideTargetKind.SALE_LINE,
            product_id=pid,
            requested_price_thb=Decimal("970.00"),  # 3% deviation
            reason="repeat customer",
        ),
        created_by_user_id=actor,
    )
    assert ovr.state == OverrideState.AUTO_APPROVED
    assert ovr.default_price_thb == Decimal("1000.00")
    assert ovr.deviation_pct == Decimal("3.0000")


def test_create_override_pending_above_threshold(db: Session) -> None:
    _set_threshold(db, 5.0)
    actor = _admin(db)
    pid = _product(db, retail="1000.00")
    ovr = crud.create_pricing_override(
        session=db,
        override_in=PricingOverrideCreate(
            target_kind=OverrideTargetKind.SALE_LINE,
            product_id=pid,
            requested_price_thb=Decimal("900.00"),  # 10% deviation
            reason="big discount",
        ),
        created_by_user_id=actor,
    )
    assert ovr.state == OverrideState.PENDING
    assert ovr.deviation_pct == Decimal("10.0000")


def test_create_override_uses_repair_price_for_ticket_target(db: Session) -> None:
    _set_threshold(db, 5.0)
    actor = _admin(db)
    pid = _product(db, retail="1000.00", repair="300.00")
    ovr = crud.create_pricing_override(
        session=db,
        override_in=PricingOverrideCreate(
            target_kind=OverrideTargetKind.SERVICE_TICKET_PART,
            product_id=pid,
            requested_price_thb=Decimal("330.00"),  # 10% off repair price
            reason="warranty goodwill",
        ),
        created_by_user_id=actor,
    )
    assert ovr.default_price_thb == Decimal("300.00")
    assert ovr.state == OverrideState.PENDING


def test_decide_approve_sets_decided_fields(db: Session) -> None:
    _set_threshold(db, 5.0)
    creator = _admin(db)
    decider = _admin(db)
    pid = _product(db)
    ovr = crud.create_pricing_override(
        session=db,
        override_in=PricingOverrideCreate(
            target_kind=OverrideTargetKind.SALE_LINE,
            product_id=pid,
            requested_price_thb=Decimal("800.00"),
            reason="x",
        ),
        created_by_user_id=creator,
    )
    decided = crud.decide_pricing_override(
        session=db,
        override_id=ovr.id,
        decision="APPROVED",
        decided_by_user_id=decider,
    )
    assert decided.state == OverrideState.APPROVED
    assert decided.decided_by_user_id == decider
    assert decided.decided_at is not None


def test_decide_reject(db: Session) -> None:
    _set_threshold(db, 5.0)
    actor = _admin(db)
    pid = _product(db)
    ovr = crud.create_pricing_override(
        session=db,
        override_in=PricingOverrideCreate(
            target_kind=OverrideTargetKind.SALE_LINE,
            product_id=pid,
            requested_price_thb=Decimal("500.00"),
            reason="x",
        ),
        created_by_user_id=actor,
    )
    decided = crud.decide_pricing_override(
        session=db, override_id=ovr.id, decision="REJECTED", decided_by_user_id=actor
    )
    assert decided.state == OverrideState.REJECTED


def test_decide_non_pending_is_conflict(db: Session) -> None:
    _set_threshold(db, 5.0)
    actor = _admin(db)
    pid = _product(db)
    ovr = crud.create_pricing_override(  # 0% -> AUTO_APPROVED, not PENDING
        session=db,
        override_in=PricingOverrideCreate(
            target_kind=OverrideTargetKind.SALE_LINE,
            product_id=pid,
            requested_price_thb=Decimal("1000.00"),
            reason="no change",
        ),
        created_by_user_id=actor,
    )
    assert ovr.state == OverrideState.AUTO_APPROVED
    with pytest.raises(HTTPException) as exc:
        crud.decide_pricing_override(
            session=db, override_id=ovr.id, decision="APPROVED", decided_by_user_id=actor
        )
    assert exc.value.status_code == 409


def test_list_filters_by_state(db: Session) -> None:
    _set_threshold(db, 5.0)
    actor = _admin(db)
    pid = _product(db, retail="1000.00")
    pending = crud.create_pricing_override(
        session=db,
        override_in=PricingOverrideCreate(
            target_kind=OverrideTargetKind.SALE_LINE,
            product_id=pid,
            requested_price_thb=Decimal("700.00"),  # 30% -> PENDING
            reason="x",
        ),
        created_by_user_id=actor,
    )
    rows = crud.list_pricing_overrides(session=db, state=OverrideState.PENDING)
    assert pending.id in {r.id for r in rows}
    assert all(r.state == OverrideState.PENDING for r in rows)


def test_override_exceptions_report_shape(db: Session) -> None:
    from datetime import datetime, timezone

    _set_threshold(db, 5.0)
    actor = _admin(db)
    pid = _product(db, retail="1000.00")

    def _mk(price: str) -> PricingOverrideRequest:
        return crud.create_pricing_override(
            session=db,
            override_in=PricingOverrideCreate(
                target_kind=OverrideTargetKind.SALE_LINE,
                product_id=pid,
                requested_price_thb=Decimal(price),
                reason="x",
            ),
            created_by_user_id=actor,
        )

    auto = _mk("970.00")  # AUTO_APPROVED
    pend = _mk("900.00")  # PENDING
    appr = _mk("850.00")  # PENDING -> APPROVED
    rej = _mk("800.00")  # PENDING -> REJECTED
    crud.decide_pricing_override(
        session=db, override_id=appr.id, decision="APPROVED", decided_by_user_id=actor
    )
    crud.decide_pricing_override(
        session=db, override_id=rej.id, decision="REJECTED", decided_by_user_id=actor
    )

    now = datetime.now(timezone.utc)
    report = crud.override_exceptions_report(
        session=db, year=now.year, month=now.month
    )
    assert report.month == f"{now.year:04d}-{now.month:02d}"
    by_id = {r.id: r for r in report.rows}
    assert {auto.id, pend.id, appr.id, rej.id} <= set(by_id)
    assert by_id[auto.id].state == OverrideState.AUTO_APPROVED
    assert by_id[appr.id].state == OverrideState.APPROVED
    assert by_id[rej.id].state == OverrideState.REJECTED
    assert by_id[auto.id].sku  # product sku joined in
    assert report.total == len(report.rows)
    assert report.auto_approved >= 1
    assert report.pending >= 1
    assert report.approved >= 1
    assert report.rejected >= 1


def test_create_override_tiny_default_does_not_overflow(db: Session) -> None:
    # Regression (review C-1): a tiny default + large requested price must not
    # overflow Numeric(7,4); deviation is capped and the request goes PENDING.
    _set_threshold(db, 5.0)
    actor = _admin(db)
    pid = _product(db, retail="0.01")
    ovr = crud.create_pricing_override(
        session=db,
        override_in=PricingOverrideCreate(
            target_kind=OverrideTargetKind.SALE_LINE,
            product_id=pid,
            requested_price_thb=Decimal("9999999.00"),
            reason="huge",
        ),
        created_by_user_id=actor,
    )
    assert ovr.state == OverrideState.PENDING
    assert ovr.deviation_pct == Decimal("999.9999")  # capped


def test_create_override_zero_default_forces_pending_even_with_huge_threshold(
    db: Session,
) -> None:
    # Regression (review M-1): a 0 default price can't be auto-approved for a
    # non-zero requested price, regardless of how high the threshold is set.
    _set_threshold(db, 100000.0)
    actor = _admin(db)
    pid = _product(db, retail="0.00")
    ovr = crud.create_pricing_override(
        session=db,
        override_in=PricingOverrideCreate(
            target_kind=OverrideTargetKind.SALE_LINE,
            product_id=pid,
            requested_price_thb=Decimal("50.00"),
            reason="free product priced",
        ),
        created_by_user_id=actor,
    )
    assert ovr.state == OverrideState.PENDING
    # restore a sane threshold so later tests in this session aren't affected
    _set_threshold(db, 5.0)


def test_decide_rejects_invalid_decision(db: Session) -> None:
    _set_threshold(db, 5.0)
    actor = _admin(db)
    pid = _product(db)
    ovr = crud.create_pricing_override(
        session=db,
        override_in=PricingOverrideCreate(
            target_kind=OverrideTargetKind.SALE_LINE,
            product_id=pid,
            requested_price_thb=Decimal("700.00"),
            reason="x",
        ),
        created_by_user_id=actor,
    )
    with pytest.raises(HTTPException) as exc:
        crud.decide_pricing_override(
            session=db, override_id=ovr.id, decision="MAYBE", decided_by_user_id=actor  # type: ignore[arg-type]
        )
    assert exc.value.status_code == 422
