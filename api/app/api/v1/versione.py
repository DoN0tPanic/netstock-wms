"""La versione in esecuzione, per la pagina Impostazioni.

Serve a una domanda precisa: produzione e sviluppo girano lo stesso codice?
Il commit risponde; lo schema del database dice se le migrazioni sono
passate. Solo per gli amministratori: a un estraneo la versione esatta
direbbe quali difetti noti cercare.
"""

import platform
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.deps import DbSession, require_role
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.versione import VersioneResponse
from app.versione import AVVIO, della_build, revisione_prevista

router = APIRouter(tags=["versione"])


@router.get("/versione", response_model=VersioneResponse)
async def versione(
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    build = della_build()
    return VersioneResponse(
        commit=build["commit"],
        data_commit=build["data_commit"],
        costruita=build["costruita"],
        avviata=AVVIO,
        schema_attuale=(
            await db.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none(),
        schema_previsto=revisione_prevista(),
        python=platform.python_version(),
        postgresql=(await db.execute(text("SHOW server_version"))).scalar_one(),
    )
