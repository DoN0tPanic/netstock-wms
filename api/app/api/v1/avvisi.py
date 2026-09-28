"""Gli avvisi per gli amministratori: backup, disco e ora del server.

Solo per gli amministratori, che sono i soli a poterci fare qualcosa. L'ora
del server viaggia con gli avvisi perché il confronto con l'orologio lo fa il
browser: il server, da solo, non può sapere di essere avanti.
"""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends

from app.deps import require_role
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.avvisi import AvvisiResponse, AvvisoResponse
from app.services.avvisi import controlla_backup, controlla_disco

router = APIRouter(tags=["avvisi"])


@router.get("/avvisi", response_model=AvvisiResponse)
def avvisi(user: User = Depends(require_role(UserRole.admin))) -> Any:
    elenco = controlla_backup() + controlla_disco()
    return AvvisiResponse(
        ora_server=datetime.now(UTC),
        avvisi=[AvvisoResponse(**asdict(avviso)) for avviso in elenco],
    )
