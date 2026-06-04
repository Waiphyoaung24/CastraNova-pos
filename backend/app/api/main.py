from fastapi import APIRouter

from app.api.routes import (
    customers,
    login,
    private,
    projects,
    suppliers,
    users,
    utils,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(suppliers.router)
api_router.include_router(customers.router)
api_router.include_router(projects.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
