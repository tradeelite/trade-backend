"""Portfolio and holdings CRUD API routes."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.db.firestore import get_firestore
from app.db.repositories.holdings import HoldingRepository
from app.db.repositories.portfolios import PortfolioRepository
from app.db.schemas import HoldingCreate, PortfolioCreate, PortfolioUpdate, PortfolioWithStats
from app.routers.auth import get_request_user_email
from app.services import yahoo_finance as yf_svc

router = APIRouter(prefix="/api/portfolios", tags=["portfolios"])


def get_portfolio_repo() -> PortfolioRepository:
    return PortfolioRepository(get_firestore())


def get_holding_repo() -> HoldingRepository:
    return HoldingRepository(get_firestore())


PortfolioDB = Annotated[PortfolioRepository, Depends(get_portfolio_repo)]
HoldingDB = Annotated[HoldingRepository, Depends(get_holding_repo)]
UserEmail = Annotated[str, Depends(get_request_user_email)]


# ---------------------------------------------------------------------------
# Portfolios
# ---------------------------------------------------------------------------

@router.get("")
async def list_portfolios(
    repo: PortfolioDB,
    holding_repo: HoldingDB,
    user_email: UserEmail,
) -> list[PortfolioWithStats]:
    portfolios = await repo.get_all(user_email=user_email)
    out = []
    for p in portfolios:
        holdings = await holding_repo.get_by_portfolio(p["id"])

        async def _value(h: dict) -> float | None:
            try:
                return yf_svc.get_quote(h["ticker"])["price"]
            except Exception:
                return None

        prices = await asyncio.gather(*[_value(h) for h in holdings])
        total_value = total_cost = 0.0
        for h, price in zip(holdings, prices):
            cost = h["shares"] * h["avg_cost"]
            total_cost += cost
            if price:
                total_value += h["shares"] * price

        gain_loss = total_value - total_cost
        gain_loss_pct = (gain_loss / total_cost * 100) if total_cost else 0

        out.append(PortfolioWithStats(
            id=p["id"], name=p["name"], description=p.get("description"),
            created_at=p["created_at"], updated_at=p["updated_at"],
            total_value=round(total_value, 2), total_cost=round(total_cost, 2),
            total_gain_loss=round(gain_loss, 2),
            total_gain_loss_percent=round(gain_loss_pct, 2),
            holdings_count=len(holdings),
        ))
    return out


@router.post("", status_code=201)
async def create_portfolio(body: PortfolioCreate, repo: PortfolioDB, user_email: UserEmail):
    return await repo.create(
        name=body.name,
        description=body.description,
        user_email=user_email,
    )


@router.get("/{portfolio_id}")
async def get_portfolio(portfolio_id: str, repo: PortfolioDB, user_email: UserEmail):
    p = await repo.get_by_id(portfolio_id, user_email=user_email)
    if not p:
        raise HTTPException(404, "Portfolio not found")
    return p


@router.put("/{portfolio_id}")
async def update_portfolio(
    portfolio_id: str,
    body: PortfolioUpdate,
    repo: PortfolioDB,
    user_email: UserEmail,
):
    data = body.model_dump(exclude_none=True)
    p = await repo.update(portfolio_id, data, user_email=user_email)
    if not p:
        raise HTTPException(404, "Portfolio not found")
    return p


@router.delete("/{portfolio_id}")
async def delete_portfolio(portfolio_id: str, repo: PortfolioDB, user_email: UserEmail):
    deleted = await repo.delete(portfolio_id, user_email=user_email)
    if not deleted:
        raise HTTPException(404, "Portfolio not found")
    return {"success": True}


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------

@router.get("/{portfolio_id}/holdings")
async def list_holdings(
    portfolio_id: str,
    holding_repo: HoldingDB,
    repo: PortfolioDB,
    user_email: UserEmail,
):
    portfolio = await repo.get_by_id(portfolio_id, user_email=user_email)
    if not portfolio:
        raise HTTPException(404, "Portfolio not found")
    holdings = await holding_repo.get_by_portfolio(portfolio_id)

    async def _enrich(h: dict) -> dict:
        added_at = h["added_at"]
        base = {
            "id": h["id"],
            "portfolioId": h["portfolio_id"],
            "ticker": h["ticker"],
            "shares": h["shares"],
            "avgCost": h["avg_cost"],
            "addedAt": added_at.isoformat() if hasattr(added_at, "isoformat") else added_at,
        }
        try:
            price = yf_svc.get_quote(h["ticker"])["price"]
            value = h["shares"] * price
            cost = h["shares"] * h["avg_cost"]
            base.update({
                "currentPrice": price,
                "currentValue": round(value, 2),
                "gainLoss": round(value - cost, 2),
                "gainLossPercent": round((value - cost) / cost * 100, 2) if cost else 0,
            })
        except Exception:
            pass
        return base

    return await asyncio.gather(*[_enrich(h) for h in holdings])


@router.post("/{portfolio_id}/holdings", status_code=201)
async def upsert_holding(
    portfolio_id: str,
    body: HoldingCreate,
    holding_repo: HoldingDB,
    repo: PortfolioDB,
    user_email: UserEmail,
):
    portfolio = await repo.get_by_id(portfolio_id, user_email=user_email)
    if not portfolio:
        raise HTTPException(404, "Portfolio not found")
    return await holding_repo.upsert(
        portfolio_id=portfolio_id,
        ticker=body.ticker.upper(),
        shares=body.shares,
        avg_cost=body.avg_cost,
    )


@router.delete("/{portfolio_id}/holdings")
async def delete_holding(
    portfolio_id: str,
    holding_id: str,
    holding_repo: HoldingDB,
    repo: PortfolioDB,
    user_email: UserEmail,
):
    portfolio = await repo.get_by_id(portfolio_id, user_email=user_email)
    if not portfolio:
        raise HTTPException(404, "Portfolio not found")
    holding = await holding_repo.get_by_id(holding_id)
    if not holding or holding.get("portfolio_id") != portfolio_id:
        raise HTTPException(404, "Holding not found")
    deleted = await holding_repo.delete(holding_id)
    if not deleted:
        raise HTTPException(404, "Holding not found")
    return {"success": True}
