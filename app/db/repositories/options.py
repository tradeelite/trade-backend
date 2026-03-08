"""Firestore repository for option_trades collection."""

from datetime import datetime, timezone

from google.cloud.firestore import AsyncClient


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OptionRepository:
    def __init__(self, db: AsyncClient):
        self.col = db.collection("option_trades")

    def _to_dict(self, doc) -> dict:
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    async def get_all(self, status: str | None = None) -> list[dict]:
        q = self.col
        if status in ("open", "closed"):
            q = q.where("status", "==", status)
        result = []
        async for doc in q.stream():
            result.append(self._to_dict(doc))
        return result

    async def get_by_id(self, id: str) -> dict | None:
        doc = await self.col.document(id).get()
        if not doc.exists:
            return None
        return self._to_dict(doc)

    async def create(self, data: dict) -> dict:
        now = _now()
        payload = {**data, "created_at": now, "updated_at": now}
        _ts, ref = await self.col.add(payload)
        doc = await ref.get()
        return self._to_dict(doc)

    async def update(self, id: str, data: dict) -> dict | None:
        ref = self.col.document(id)
        doc = await ref.get()
        if not doc.exists:
            return None
        data["updated_at"] = _now()
        await ref.update(data)
        doc = await ref.get()
        return self._to_dict(doc)

    async def delete(self, id: str) -> bool:
        ref = self.col.document(id)
        doc = await ref.get()
        if not doc.exists:
            return False
        await ref.delete()
        return True
