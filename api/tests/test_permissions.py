from dataclasses import dataclass

import pytest

from app.deps import require_role
from app.exceptions import ForbiddenError
from app.models.enums import UserRole


@dataclass
class _FakeUser:
    role: UserRole


@pytest.mark.parametrize(
    ("user_role", "minimum_role", "allowed"),
    [
        (UserRole.viewer, UserRole.viewer, True),
        (UserRole.viewer, UserRole.operator, False),
        (UserRole.viewer, UserRole.admin, False),
        (UserRole.operator, UserRole.viewer, True),
        (UserRole.operator, UserRole.operator, True),
        (UserRole.operator, UserRole.admin, False),
        (UserRole.admin, UserRole.viewer, True),
        (UserRole.admin, UserRole.operator, True),
        (UserRole.admin, UserRole.admin, True),
    ],
)
async def test_require_role(user_role: UserRole, minimum_role: UserRole, allowed: bool) -> None:
    dependency = require_role(minimum_role)
    user = _FakeUser(role=user_role)

    if allowed:
        result = await dependency(user)  # type: ignore[arg-type]
        assert result is user
    else:
        with pytest.raises(ForbiddenError):
            await dependency(user)  # type: ignore[arg-type]


# --- Il guardiano giusto sulla rotta giusta -----------------------------
#
# `require_role` funziona; la domanda che questi test pongono è un'altra:
# **è stato messo** dove serve. La differenza non è teorica — `GET /settings`
# era leggibile da un utente in sola lettura mentre la scrittura era riservata
# agli amministratori, e nessun test se ne accorgeva perché nessuno guardava
# le rotte una per una.

def _ruolo_minimo(funzione) -> UserRole | None:
    """Il ruolo che una rotta pretende, letto dalle sue dipendenze."""
    import inspect

    for parametro in inspect.signature(funzione).parameters.values():
        predefinito = parametro.default
        dipendenza = getattr(predefinito, "dependency", None)
        richiesto = getattr(dipendenza, "ruolo_minimo", None)
        if richiesto is not None:
            return richiesto
    return None


@pytest.mark.parametrize(
    ("modulo", "funzione", "atteso"),
    [
        # Amministrazione: la configurazione si legge e si scrive solo da admin.
        ("app.api.v1.settings_router", "list_settings", UserRole.admin),
        ("app.api.v1.settings_router", "update_setting", UserRole.admin),
        ("app.api.v1.ai", "stato", UserRole.admin),
        ("app.api.v1.ai", "scegli_modello", UserRole.admin),
        ("app.api.v1.maintenance", "stato_backup", UserRole.admin),
        ("app.api.v1.maintenance", "esegui_backup", UserRole.admin),
        ("app.api.v1.maintenance", "ripristina_backup", UserRole.admin),
        # Archivio: chi scrive dev'essere almeno operatore.
        ("app.api.v1.documents", "carica", UserRole.operator),
        ("app.api.v1.documents", "scegli_fornitore", UserRole.operator),
        ("app.api.v1.documents", "riesamina_fornitori", UserRole.operator),
        ("app.api.v1.documents", "elimina", UserRole.admin),
    ],
)
def test_la_rotta_pretende_il_ruolo_che_deve(modulo, funzione, atteso) -> None:
    import importlib

    rotta = getattr(importlib.import_module(modulo), funzione)

    assert _ruolo_minimo(rotta) == atteso, (
        f"{modulo}.{funzione} non pretende {atteso.value}"
    )
