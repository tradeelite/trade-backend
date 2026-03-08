"""Firestore repository for app_settings collection (key-value store)."""

from google.cloud.firestore import AsyncClient


class SettingsRepository:
    def __init__(self, db: AsyncClient):
        self.col = db.collection("app_settings")

    async def get_all(self) -> dict:
        result = {}
        async for doc in self.col.stream():
            result[doc.id] = doc.to_dict().get("value", "")
        return result

    async def get(self, key: str) -> str | None:
        doc = await self.col.document(key).get()
        if not doc.exists:
            return None
        return doc.to_dict().get("value")

    async def set(self, key: str, value: str) -> None:
        await self.col.document(key).set({"value": value})
