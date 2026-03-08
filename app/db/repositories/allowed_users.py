"""Firestore repository for allowed_users collection."""

from datetime import datetime, timezone

from google.cloud.firestore import AsyncClient


class AllowedUsersRepository:
    def __init__(self, db: AsyncClient):
        self.col = db.collection("allowed_users")

    async def list_all(self) -> list[dict]:
        users = []
        async for doc in self.col.order_by("added_at").stream():
            data = doc.to_dict()
            users.append({"email": doc.id, "added_at": data.get("added_at", "")})
        return users

    async def is_allowed(self, email: str) -> bool:
        doc = await self.col.document(email).get()
        return doc.exists

    async def add(self, email: str) -> None:
        await self.col.document(email).set(
            {"added_at": datetime.now(timezone.utc).isoformat()}
        )

    async def remove(self, email: str) -> None:
        await self.col.document(email).delete()
