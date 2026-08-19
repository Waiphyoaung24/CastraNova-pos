import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app import crud
from app.api.deps import SessionDep, get_admin, get_current_user
from app.models import (
    SupplierCreate,
    SupplierOption,
    SupplierPublic,
    SuppliersPublic,
    SupplierUpdate,
)

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get(
    "/",
    response_model=SuppliersPublic,
    dependencies=[Depends(get_current_user)],
)
def read_suppliers(
    session: SessionDep,
    q: Annotated[
        str | None,
        Query(max_length=255, description="Case-insensitive substring match on name"),
    ] = None,
    country: Annotated[
        str | None, Query(max_length=64, description="Exact match on country")
    ] = None,
    skip: Annotated[int, Query(ge=0, le=10_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> SuppliersPublic:
    return SuppliersPublic(
        data=crud.list_suppliers(
            session=session, q=q, country=country, skip=skip, limit=limit
        ),
        count=crud.count_suppliers(session=session, q=q, country=country),
    )


@router.get(
    "/options", response_model=list[SupplierOption], dependencies=[Depends(get_current_user)]
)
def read_options(session: SessionDep) -> list[SupplierOption]:
    return crud.list_supplier_options(session=session)


@router.get(
    "/countries", response_model=list[str], dependencies=[Depends(get_current_user)]
)
def list_countries(session: SessionDep) -> list[str]:
    return crud.list_supplier_countries(session=session)


@router.post(
    "/", response_model=SupplierPublic, dependencies=[Depends(get_admin)]
)
def create_supplier(
    *, session: SessionDep, supplier_in: SupplierCreate
) -> SupplierPublic:
    return crud.create_supplier(session=session, supplier_in=supplier_in)  # type: ignore[return-value]


@router.patch(
    "/{supplier_id}",
    response_model=SupplierPublic,
    dependencies=[Depends(get_admin)],
)
def update_supplier(
    *, session: SessionDep, supplier_id: uuid.UUID, supplier_in: SupplierUpdate
) -> SupplierPublic:
    db_supplier = crud.get_supplier(session=session, supplier_id=supplier_id)
    if not db_supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return crud.update_supplier(  # type: ignore[return-value]
        session=session, db_supplier=db_supplier, supplier_in=supplier_in
    )
