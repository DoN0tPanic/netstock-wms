from fastapi import APIRouter

from app.api.v1 import (
    audit,
    auth,
    bulk_export,
    catalog_items,
    dashboard,
    delivery_notes,
    documents,
    extraction,
    inventory,
    maintenance,
    movements,
    registries,
    reservations,
    search,
    settings_router,
    stock,
    units,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(registries.vendors_router)
api_router.include_router(registries.categories_router)
api_router.include_router(registries.suppliers_router)
api_router.include_router(registries.locations_router)
api_router.include_router(catalog_items.router)
api_router.include_router(delivery_notes.router)
api_router.include_router(documents.router)
api_router.include_router(units.router)
api_router.include_router(stock.router)
api_router.include_router(inventory.router)
api_router.include_router(dashboard.router)
api_router.include_router(search.router)
api_router.include_router(movements.router)
api_router.include_router(reservations.router)
api_router.include_router(extraction.router)
api_router.include_router(users.router)
api_router.include_router(audit.router)
api_router.include_router(settings_router.router)
api_router.include_router(maintenance.router)
api_router.include_router(bulk_export.router)
