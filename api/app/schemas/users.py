import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import UserRole
from app.schemas.common import OrmModel


class UserCreate(BaseModel):
    username: str
    full_name: str
    email: str | None = None
    role: UserRole = UserRole.viewer
    initial_password: str = Field(min_length=12)


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserResponse(OrmModel):
    id: uuid.UUID
    username: str
    email: str | None
    full_name: str
    role: UserRole
    auth_provider: str
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None
    deleted_at: datetime | None
    # Vero solo per un account eliminato che nessuna riga di registro cita:
    # sono gli unici che si possono ancora togliere davvero dal database.
    can_purge: bool = False
    created_at: datetime
    updated_at: datetime


class ResetPasswordResponse(BaseModel):
    temporary_password: str


class UserDeleteResponse(BaseModel):
    """Esito di un'eliminazione, nelle sue due fasi.

    `removed` è falso per la chiusura dell'account — che è quello che fa
    `DELETE /users/{id}` — e vero solo per la rimozione definitiva dal
    database. `traces` dice quante righe di registro portano la firma di
    quell'utente e in quali tabelle, e `purgeable` se la rimozione definitiva
    è ancora possibile: sono le due cose che servono per spiegare a schermo
    perché un account resta, invece di limitarsi ad affermarlo.
    """

    removed: bool
    username: str
    traces: dict[str, int] = Field(default_factory=dict)
    purgeable: bool = False
