import uuid

from fastapi import APIRouter, Depends, HTTPException

from app import crud
from app.api.deps import SessionDep, get_admin
from app.models import ProjectCreate, ProjectPublic, ProjectUpdate

# Projects are admin-only across the board (spec §8).
router = APIRouter(
    prefix="/projects", tags=["projects"], dependencies=[Depends(get_admin)]
)


@router.get("/", response_model=list[ProjectPublic])
def read_projects(
    session: SessionDep, skip: int = 0, limit: int = 100
) -> list[ProjectPublic]:
    return crud.list_projects(session=session, skip=skip, limit=limit)  # type: ignore[return-value]


@router.post("/", response_model=ProjectPublic)
def create_project(*, session: SessionDep, project_in: ProjectCreate) -> ProjectPublic:
    return crud.create_project(session=session, project_in=project_in)  # type: ignore[return-value]


@router.patch("/{project_id}", response_model=ProjectPublic)
def update_project(
    *, session: SessionDep, project_id: uuid.UUID, project_in: ProjectUpdate
) -> ProjectPublic:
    db_project = crud.get_project(session=session, project_id=project_id)
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")
    return crud.update_project(  # type: ignore[return-value]
        session=session, db_project=db_project, project_in=project_in
    )
