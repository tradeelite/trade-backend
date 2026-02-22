"""App settings key-value store routes."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import AppSetting
from app.db.schemas import SettingUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("")
async def get_settings(db: DB) -> dict:
    result = await db.execute(select(AppSetting))
    return {s.key: s.value for s in result.scalars().all()}


@router.put("")
async def update_setting(body: SettingUpdate, db: DB):
    stmt = (
        insert(AppSetting)
        .values(key=body.key, value=body.value)
        .on_conflict_do_update(index_elements=["key"], set_={"value": body.value})
    )
    await db.execute(stmt)
    await db.commit()
    return {"success": True}
