from fastapi import APIRouter

from app.api.routes import (
    audit,
    customers,
    login,
    low_stock,
    notifications,
    pricing_overrides,
    private,
    products,
    project_pulls,
    projects,
    receipts,
    reports,
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
api_router.include_router(low_stock.router)
api_router.include_router(reports.router)
api_router.include_router(audit.router)
api_router.include_router(pricing_overrides.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
