from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.deps import CurrentUser, DbSession, require_role
from app.exceptions import ValidationAppError
from app.models.app_settings import AppSetting
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.settings import AppSettingResponse, AppSettingUpdate
from app.services.audit import write_audit

# Impostazioni che hanno una pagina propria, con i controlli che servono:
# `extraction_model` si sceglie fra i modelli installati, e scriverlo qui come
# JSON grezzo scavalcherebbe quella verifica lasciando l'estrazione rotta.
CHIAVI_CON_PAGINA = {"extraction_model", "extraction_mode"}

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=list[AppSettingResponse])
async def list_settings(db: DbSession, user: CurrentUser) -> Any:
    result = await db.execute(select(AppSetting))
    return result.scalars().all()


@router.put("/{key}", response_model=AppSettingResponse)
async def update_setting(
    key: str,
    payload: AppSettingUpdate,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    if key in CHIAVI_CON_PAGINA:
        raise ValidationAppError(
            f"«{key}» si cambia dalla sezione «Lettura automatica dei documenti», "
            "che verifica che il modello sia davvero installato."
        )
    setting = await db.get(AppSetting, key)
    if setting is None:
        setting = AppSetting(key=key, value=payload.value, updated_by=user.id)
        db.add(setting)
    else:
        setting.value = payload.value
        setting.updated_by = user.id
    await db.flush()
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="settings.update",
        entity_type="app_setting",
        entity_id=key,
        details={"value": payload.value},
    )
    return setting
