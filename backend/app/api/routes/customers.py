import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_admin, get_current_user, is_admin
from app.models import (
    CustomerCreate,
    CustomerDashboardAdminPublic,
    CustomerDashboardStaffPublic,
    CustomerOption,
    CustomerPublic,
    CustomersPublic,
    CustomerUpdate,
)

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get(
    "/",
    response_model=CustomersPublic,
    dependencies=[Depends(get_current_user)],
)
def read_customers(
    session: SessionDep,
    skip: Annotated[int, Query(ge=0, le=10_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> CustomersPublic:
    return CustomersPublic(
        data=crud.list_customers(session=session, skip=skip, limit=limit),
        count=crud.count_customers(session=session),
    )


@router.get(
    "/options", response_model=list[CustomerOption], dependencies=[Depends(get_current_user)]
)
def read_options(session: SessionDep) -> list[CustomerOption]:
    return crud.list_customer_options(session=session)


@router.post(
    "/", response_model=CustomerPublic, dependencies=[Depends(get_current_user)]
)
def create_customer(
    *,
    session: SessionDep,
    customer_in: CustomerCreate,
) -> CustomerPublic:
    # Staff may create customers inline during a sale (FR-007 + D25).
    # v1 tolerates duplicates from offline inline-create; admin merge is v1.1 (S3).
    return crud.create_customer(session=session, customer_in=customer_in)  # type: ignore[return-value]


@router.get(
    "/{customer_id}/dashboard",
    response_model=CustomerDashboardAdminPublic | CustomerDashboardStaffPublic,
)
def get_customer_dashboard(
    customer_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> CustomerDashboardAdminPublic | CustomerDashboardStaffPublic:
    # Access model (spec §6.5/S7): any authenticated user may view any customer
    # dashboard; financial fields are redacted for staff via the role-dispatched
    # response schema below (no per-customer IDOR scoping by design).
    data = crud.get_customer_dashboard(session=session, customer_id=customer_id)
    if is_admin(current_user):
        return CustomerDashboardAdminPublic.model_validate(data)
    return CustomerDashboardStaffPublic.model_validate(data)


@router.patch(
    "/{customer_id}",
    response_model=CustomerPublic,
    dependencies=[Depends(get_admin)],
)
def update_customer(
    *, session: SessionDep, customer_id: uuid.UUID, customer_in: CustomerUpdate
) -> CustomerPublic:
    db_customer = crud.get_customer(session=session, customer_id=customer_id)
    if not db_customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return crud.update_customer(  # type: ignore[return-value]
        session=session, db_customer=db_customer, customer_in=customer_in
    )
