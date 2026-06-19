from sqlmodel import Session

from app import crud


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
