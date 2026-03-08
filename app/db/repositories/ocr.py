"""Firestore repository for ocr_uploads collection."""

from datetime import datetime, timezone

from google.cloud.firestore import AsyncClient


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OcrRepository:
    def __init__(self, db: AsyncClient):
        self.col = db.collection("ocr_uploads")

    async def create(self, filename: str) -> dict:
        data = {"filename": filename, "status": "pending", "extracted_data": None, "created_at": _now()}
        _ts, ref = await self.col.add(data)
        doc = await ref.get()
        result = doc.to_dict()
        result["id"] = doc.id
        return result

    async def update(self, id: str, status: str, extracted_data: str | None = None) -> dict | None:
        ref = self.col.document(id)
        doc = await ref.get()
        if not doc.exists:
            return None
        await ref.update({"status": status, "extracted_data": extracted_data})
        doc = await ref.get()
        result = doc.to_dict()
        result["id"] = doc.id
        return result
