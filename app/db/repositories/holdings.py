"""Firestore repository for holdings collection."""

from datetime import datetime, timezone

from google.cloud.firestore import AsyncClient


def _now() -> datetime:
    return datetime.now(timezone.utc)


class HoldingRepository:
    def __init__(self, db: AsyncClient):
        self.col = db.collection("holdings")

    def _to_dict(self, doc) -> dict:
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    async def get_by_portfolio(self, portfolio_id: str) -> list[dict]:
        result = []
        async for doc in self.col.where("portfolio_id", "==", portfolio_id).stream():
            result.append(self._to_dict(doc))
        return result

    async def get_by_id(self, holding_id: str) -> dict | None:
        doc = await self.col.document(holding_id).get()
        if not doc.exists:
            return None
        return self._to_dict(doc)

    async def upsert(self, portfolio_id: str, ticker: str, shares: float, avg_cost: float) -> dict:
        # Find existing holding for this portfolio+ticker
        existing_doc = None
        async for doc in (
            self.col.where("portfolio_id", "==", portfolio_id)
            .where("ticker", "==", ticker)
            .stream()
        ):
            existing_doc = doc
            break

        if existing_doc:
            await existing_doc.reference.update({"shares": shares, "avg_cost": avg_cost})
            doc = await existing_doc.reference.get()
            return self._to_dict(doc)
        else:
            data = {
                "portfolio_id": portfolio_id,
                "ticker": ticker,
                "shares": shares,
                "avg_cost": avg_cost,
                "added_at": _now(),
            }
            _ts, ref = await self.col.add(data)
            doc = await ref.get()
            return self._to_dict(doc)

    async def delete(self, holding_id: str) -> bool:
        ref = self.col.document(holding_id)
        doc = await ref.get()
        if not doc.exists:
            return False
        await ref.delete()
        return True
