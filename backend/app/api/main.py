from fastapi import APIRouter

from app.api.routes import (
    customers,
    login,
    notifications,
    private,
    products,
    project_pulls,
    projects,
    receipts,
    sales,
    service_tickets,
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
api_router.include_router(project_pulls.router)
api_router.include_router(products.router)
api_router.include_router(receipts.router)
api_router.include_router(sales.router)
api_router.include_router(service_tickets.router)
api_router.include_router(notifications.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
