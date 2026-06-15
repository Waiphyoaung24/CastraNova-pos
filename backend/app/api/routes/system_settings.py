from fastapi import APIRouter, Depends

from app import crud
from app.api.deps import AdminUser, SessionDep, get_admin
from app.models import ExchangeRatesPublic, ExchangeRatesUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get(
    "/exchange-rates",
    response_model=ExchangeRatesPublic,
    dependencies=[Depends(get_admin)],
)
def get_exchange_rates(*, session: SessionDep) -> ExchangeRatesPublic:
    """Current USD/MMK -> THB conversion rates (admin-only config)."""
    return crud.get_exchange_rates(session=session)


@router.put("/exchange-rates", response_model=ExchangeRatesPublic)
def update_exchange_rates(
    *, session: SessionDep, admin: AdminUser, payload: ExchangeRatesUpdate
) -> ExchangeRatesPublic:
    """Set the USD/MMK -> THB conversion rates (admin-only)."""
    return crud.set_exchange_rates(
        session=session, rates=payload, updated_by_user_id=admin.id
    )
