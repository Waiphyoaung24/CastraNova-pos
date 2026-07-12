import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_admin, is_admin
from app.models import (
    ProjectCreate,
    ProjectDashboardAdminPublic,
    ProjectDashboardStaffPublic,
    ProjectOption,
    ProjectPublic,
    ProjectsPublic,
    ProjectUpdate,
)

# Project CRUD is admin-only (spec §8); the dashboard is role-tiered (FR-020/S7).
router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "/", response_model=ProjectsPublic, dependencies=[Depends(get_admin)]
)
def read_projects(
    session: SessionDep,
    skip: Annotated[int, Query(ge=0, le=10_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> ProjectsPublic:
    return ProjectsPublic(
        data=crud.list_projects(session=session, skip=skip, limit=limit),
        count=crud.count_projects(session=session),
    )


@router.get("/options", response_model=list[ProjectOption], dependencies=[Depends(get_admin)])
def read_options(session: SessionDep) -> list[ProjectOption]:
    return crud.list_project_options(session=session)


@router.post(
    "/", response_model=ProjectPublic, dependencies=[Depends(get_admin)]
)
def create_project(*, session: SessionDep, project_in: ProjectCreate) -> ProjectPublic:
    return crud.create_project(session=session, project_in=project_in)  # type: ignore[return-value]


@router.get(
    "/{project_id}/dashboard",
    response_model=ProjectDashboardAdminPublic | ProjectDashboardStaffPublic,
)
def get_project_dashboard(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> ProjectDashboardAdminPublic | ProjectDashboardStaffPublic:
    # Access model (spec §6.5/S7): any authenticated user may view any project
    # dashboard; budget/consumed-cost fields are redacted for staff via the
    # role-dispatched response schema below (no per-project IDOR scoping by design).
    data = crud.get_project_dashboard(session=session, project_id=project_id)
    if is_admin(current_user):
        return ProjectDashboardAdminPublic.model_validate(data)
    return ProjectDashboardStaffPublic.model_validate(data)


@router.patch(
    "/{project_id}", response_model=ProjectPublic, dependencies=[Depends(get_admin)]
)
def update_project(
    *, session: SessionDep, project_id: uuid.UUID, project_in: ProjectUpdate
) -> ProjectPublic:
    db_project = crud.get_project(session=session, project_id=project_id)
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")
    return crud.update_project(  # type: ignore[return-value]
        session=session, db_project=db_project, project_in=project_in
    )
