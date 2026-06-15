from decimal import Decimal

from sqlmodel import Session

from app import crud
from app.models import ExchangeRatesUpdate


def test_get_setting_returns_default_when_absent(db: Session) -> None:
    assert crud.get_setting(session=db, key="missing_key", default=5.0) == 5.0


def test_set_then_get_setting_roundtrip(db: Session) -> None:
    # Throwaway key (the shared session-scoped db has no per-test truncation,
    # so we never mutate the seeded threshold other tests rely on).
    crud.set_setting(session=db, key="roundtrip_test_key", value=7.5)
    assert crud.get_setting(session=db, key="roundtrip_test_key") == 7.5


def test_set_setting_upserts_in_place(db: Session) -> None:
    crud.set_setting(session=db, key="upsert_test_key", value=1)
    crud.set_setting(session=db, key="upsert_test_key", value=2)
    assert crud.get_setting(session=db, key="upsert_test_key") == 2


def test_seed_system_settings_creates_override_threshold(db: Session) -> None:
    crud.seed_system_settings(session=db)
    assert (
        crud.get_setting(
            session=db, key="override_deviation_threshold_pct"
        )
        is not None
    )


def test_default_exchange_rates_parse_to_zero() -> None:
    # Pure: no DB/order dependency (the shared session db is mutated by other tests).
    raw = crud.DEFAULT_EXCHANGE_RATES
    assert Decimal(raw["USD_THB"]) == Decimal("0")
    assert Decimal(raw["MMK_THB"]) == Decimal("0")


def test_seed_includes_exchange_rates_key(db: Session) -> None:
    crud.seed_system_settings(session=db)
    assert crud.get_setting(session=db, key=crud.EXCHANGE_RATES_KEY) is not None


def test_set_exchange_rates_roundtrip_preserves_precision(db: Session) -> None:
    crud.set_exchange_rates(
        session=db,
        rates=ExchangeRatesUpdate(
            usd_thb=Decimal("36.50"), mmk_thb=Decimal("0.0135")
        ),
    )
    rates = crud.get_exchange_rates(session=db)
    assert rates.usd_thb == Decimal("36.50")
    assert rates.mmk_thb == Decimal("0.0135")
