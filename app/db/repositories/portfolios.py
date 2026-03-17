"""Firestore repository for portfolios collection."""

import os
from datetime import datetime, timezone

from google.cloud.firestore import AsyncClient


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PortfolioRepository:
    def __init__(self, db: AsyncClient):
        self.col = db.collection("portfolios")

    def _to_dict(self, doc) -> dict:
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    @staticmethod
    def _admin_email() -> str:
        return os.getenv("ALLOWED_EMAIL", "").lower().strip()

    @classmethod
    def _is_admin(cls, user_email: str) -> bool:
        admin_email = cls._admin_email()
        return bool(admin_email and user_email.lower() == admin_email)

    async def get_all(self, user_email: str) -> list[dict]:
        result = []
        async for doc in self.col.where("user_email", "==", user_email).stream():
            result.append(self._to_dict(doc))
        if self._is_admin(user_email):
            async for doc in self.col.stream():
                data = doc.to_dict() or {}
                if data.get("user_email"):
                    continue
                if any(existing["id"] == doc.id for existing in result):
                    continue
                result.append(self._to_dict(doc))
        return result

    async def get_by_id(self, id: str, user_email: str) -> dict | None:
        doc = await self.col.document(id).get()
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        owner = (data.get("user_email") or "").lower()
        if owner:
            if owner != user_email.lower():
                return None
            return self._to_dict(doc)
        if self._is_admin(user_email):
            return self._to_dict(doc)
        return None

    async def create(self, name: str, description: str | None, user_email: str) -> dict:
        now = _now()
        data = {
            "name": name,
            "description": description,
            "user_email": user_email.lower(),
            "created_at": now,
            "updated_at": now,
        }
        _ts, ref = await self.col.add(data)
        doc = await ref.get()
        return self._to_dict(doc)

    async def update(self, id: str, data: dict, user_email: str) -> dict | None:
        ref = self.col.document(id)
        doc = await ref.get()
        if not doc.exists:
            return None
        current = doc.to_dict() or {}
        owner = (current.get("user_email") or "").lower()
        if owner and owner != user_email.lower():
            return None
        if not owner and not self._is_admin(user_email):
            return None
        data["updated_at"] = _now()
        data.pop("user_email", None)
        await ref.update(data)
        doc = await ref.get()
        return self._to_dict(doc)

    async def delete(self, id: str, user_email: str) -> bool:
        ref = self.col.document(id)
        doc = await ref.get()
        if not doc.exists:
            return False
        data = doc.to_dict() or {}
        owner = (data.get("user_email") or "").lower()
        if owner and owner != user_email.lower():
            return False
        if not owner and not self._is_admin(user_email):
            return False
        await ref.delete()
        return True
