from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.generic_crud import build_registry_router
from app.exceptions import ValidationAppError
from app.models.catalog import Category as CategoryModel
from app.models.catalog import Location, Supplier, Vendor
from app.models.stock import StockUnit
from app.schemas.catalog import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
    LocationCreate,
    LocationResponse,
    LocationUpdate,
    SupplierCreate,
    SupplierResponse,
    SupplierUpdate,
    VendorCreate,
    VendorResponse,
    VendorUpdate,
)
from app.services.codes import codice_libero

vendors_router = build_registry_router(
    prefix="/vendors",
    tag="vendors",
    model=Vendor,
    create_schema=VendorCreate,
    update_schema=VendorUpdate,
    response_schema=VendorResponse,
    search_fields=["code", "name"],
    entity_name="vendor",
)

categories_router = build_registry_router(
    prefix="/categories",
    tag="categories",
    model=CategoryModel,
    create_schema=CategoryCreate,
    update_schema=CategoryUpdate,
    response_schema=CategoryResponse,
    search_fields=["code", "name"],
    entity_name="category",
    supports_deactivate=False,
)

suppliers_router = build_registry_router(
    prefix="/suppliers",
    tag="suppliers",
    model=Supplier,
    create_schema=SupplierCreate,
    update_schema=SupplierUpdate,
    response_schema=SupplierResponse,
    search_fields=["name"],
    entity_name="supplier",
)

async def _location_code(db: AsyncSession, valori: dict) -> dict:
    """Ricava il codice dal nome quando chi crea l'ubicazione non lo scrive.

    Il codice resta — è la chiave dell'import e quello che finisce
    sull'etichetta dello scaffale — ma smette di essere una cosa da inventare
    ogni volta: a schermo si legge comunque il nome per esteso.
    """
    if not (valori.get("code") or "").strip():
        valori["code"] = await codice_libero(db, Location, valori.get("name") or "")
    else:
        valori["code"] = valori["code"].strip()
    return valori


async def _location_is_empty(db: AsyncSession, location: Location) -> None:
    """Refuse to retire a location that still holds goods.

    Otherwise the pieces stay there but the location disappears from every
    dropdown, leaving them unreachable — the operator can no longer move them
    out of a place they can no longer select.
    """
    units = (
        await db.execute(
            select(func.count())
            .select_from(StockUnit)
            .where(StockUnit.location_id == location.id)
        )
    ).scalar_one()
    bulk = (
        await db.execute(
            text(
                "SELECT COALESCE(SUM(quantity), 0) FROM v_stock_balance WHERE location_id = :id"
            ),
            {"id": location.id},
        )
    ).scalar_one()
    if units or bulk:
        raise ValidationAppError(
            "L'ubicazione contiene ancora merce: spostala altrove prima di disattivarla.",
            details={"unita": int(units), "quantita_sfusa": str(bulk)},
        )


locations_router = build_registry_router(
    prefix="/locations",
    tag="locations",
    model=Location,
    create_schema=LocationCreate,
    update_schema=LocationUpdate,
    response_schema=LocationResponse,
    search_fields=["code", "name"],
    entity_name="location",
    deactivate_guard=_location_is_empty,
    prepare_create=_location_code,
)
