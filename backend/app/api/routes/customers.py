import uuid

from fastapi import APIRouter, Depends, HTTPException

from app import crud
from app.api.deps import SessionDep, get_admin, get_current_user
from app.models import CustomerCreate, CustomerPublic, CustomerUpdate

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get(
    "/",
    response_model=list[CustomerPublic],
    dependencies=[Depends(get_current_user)],
)
def read_customers(
    session: SessionDep,
    skip: int = 0,
    limit: int = 100,
) -> list[CustomerPublic]:
    return crud.list_customers(session=session, skip=skip, limit=limit)  # type: ignore[return-value]


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
