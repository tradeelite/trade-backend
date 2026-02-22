"""Portfolio and holdings CRUD API routes."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Holding, Portfolio
from app.db.schemas import HoldingCreate, PortfolioCreate, PortfolioUpdate, PortfolioWithStats
from app.services import yahoo_finance as yf_svc

router = APIRouter(prefix="/api/portfolios", tags=["portfolios"])
DB = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Portfolios
# ---------------------------------------------------------------------------

@router.get("")
async def list_portfolios(db: DB) -> list[PortfolioWithStats]:
    result = await db.execute(select(Portfolio))
    portfolios = result.scalars().all()
    out = []
    for p in portfolios:
        holdings_result = await db.execute(select(Holding).where(Holding.portfolio_id == p.id))
        holdings = holdings_result.scalars().all()

        async def _value(h: Holding) -> float | None:
            try:
                q = yf_svc.get_quote(h.ticker)
                return q["price"]
            except Exception:
                return None

        prices = await asyncio.gather(*[_value(h) for h in holdings])
        total_value = total_cost = 0.0
        for h, price in zip(holdings, prices):
            cost = h.shares * h.avg_cost
            total_cost += cost
            if price:
                total_value += h.shares * price

        gain_loss = total_value - total_cost
        gain_loss_pct = (gain_loss / total_cost * 100) if total_cost else 0

        out.append(PortfolioWithStats(
            id=p.id, name=p.name, description=p.description,
            created_at=p.created_at, updated_at=p.updated_at,
            total_value=round(total_value, 2), total_cost=round(total_cost, 2),
            total_gain_loss=round(gain_loss, 2),
            total_gain_loss_percent=round(gain_loss_pct, 2),
            holdings_count=len(holdings),
        ))
    return out


@router.post("", status_code=201)
async def create_portfolio(body: PortfolioCreate, db: DB):
    p = Portfolio(name=body.name, description=body.description)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@router.get("/{portfolio_id}")
async def get_portfolio(portfolio_id: int, db: DB):
    result = await db.execute(select(Portfolio).where(Portfolio.id == portfolio_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Portfolio not found")
    return p


@router.put("/{portfolio_id}")
async def update_portfolio(portfolio_id: int, body: PortfolioUpdate, db: DB):
    result = await db.execute(select(Portfolio).where(Portfolio.id == portfolio_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Portfolio not found")
    if body.name is not None:
        p.name = body.name
    if body.description is not None:
        p.description = body.description
    await db.commit()
    await db.refresh(p)
    return p


@router.delete("/{portfolio_id}")
async def delete_portfolio(portfolio_id: int, db: DB):
    result = await db.execute(select(Portfolio).where(Portfolio.id == portfolio_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Portfolio not found")
    await db.delete(p)
    await db.commit()
    return {"success": True}


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------

@router.get("/{portfolio_id}/holdings")
async def list_holdings(portfolio_id: int, db: DB):
    result = await db.execute(select(Holding).where(Holding.portfolio_id == portfolio_id))
    holdings = result.scalars().all()

    async def _enrich(h: Holding) -> dict:
        base = {
            "id": h.id, "portfolioId": h.portfolio_id, "ticker": h.ticker,
            "shares": h.shares, "avgCost": h.avg_cost, "addedAt": h.added_at.isoformat(),
        }
        try:
            q = yf_svc.get_quote(h.ticker)
            price = q["price"]
            value = h.shares * price
            cost = h.shares * h.avg_cost
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
async def upsert_holding(portfolio_id: int, body: HoldingCreate, db: DB):
    ticker = body.ticker.upper()
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id, Holding.ticker == ticker)
    )
    holding = result.scalar_one_or_none()
    if holding:
        holding.shares = body.shares
        holding.avg_cost = body.avg_cost
    else:
        holding = Holding(portfolio_id=portfolio_id, ticker=ticker, shares=body.shares, avg_cost=body.avg_cost)
        db.add(holding)
    await db.commit()
    await db.refresh(holding)
    return holding


@router.delete("/{portfolio_id}/holdings")
async def delete_holding(portfolio_id: int, holding_id: int, db: DB):
    await db.execute(
        delete(Holding).where(Holding.id == holding_id, Holding.portfolio_id == portfolio_id)
    )
    await db.commit()
    return {"success": True}
