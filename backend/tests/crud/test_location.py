from sqlmodel import Session, select

from app import crud
from app.models import Location


def test_seed_locations_present(db: Session) -> None:
    crud.seed_locations(session=db)
    codes = {loc.code for loc in db.exec(select(Location)).all()}
    assert {"YGN_WH", "CUSTOMER", "ADJUSTED_OUT"} <= codes


def test_seed_locations_idempotent(db: Session) -> None:
    crud.seed_locations(session=db)
    crud.seed_locations(session=db)
    ygn = db.exec(select(Location).where(Location.code == "YGN_WH")).all()
    assert len(ygn) == 1
