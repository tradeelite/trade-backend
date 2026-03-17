"""App settings key-value store routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.db.firestore import get_firestore
from app.db.repositories.settings import SettingsRepository
from app.db.schemas import SettingUpdate
from app.routers.auth import require_admin_user

router = APIRouter(prefix="/api/settings", tags=["settings"])


def get_settings_repo() -> SettingsRepository:
    return SettingsRepository(get_firestore())


SettingsDB = Annotated[SettingsRepository, Depends(get_settings_repo)]
AdminUser = Annotated[str, Depends(require_admin_user)]


@router.get("")
async def get_settings(repo: SettingsDB) -> dict:
    return await repo.get_all()


@router.put("")
async def update_setting(body: SettingUpdate, repo: SettingsDB, _admin_user: AdminUser):
    await repo.set(body.key, body.value)
    return {"success": True}
