"""Options trades CRUD + OCR + suggestions API routes."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import OptionTrade
from app.db.schemas import OptionTradeCreate, OptionTradeUpdate
from app.services import ocr as ocr_svc
from app.services import suggestions as sug_svc
from app.services import yahoo_finance as yf_svc

router = APIRouter(prefix="/api/options", tags=["options"])
DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("")
async def list_trades(db: DB, status: str = Query(None)):
    q = select(OptionTrade)
    if status in ("open", "closed"):
        q = q.where(OptionTrade.status == status)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("", status_code=201)
async def create_trade(body: OptionTradeCreate, db: DB):
    trade = OptionTrade(
        ticker=body.ticker.upper(),
        option_type=body.option_type,
        direction=body.direction,
        strike_price=body.strike_price,
        expiry_date=body.expiry_date,
        premium=body.premium,
        quantity=body.quantity,
        brokerage=body.brokerage,
        notes=body.notes,
        source=body.source,
    )
    db.add(trade)
    await db.commit()
    await db.refresh(trade)
    return trade


@router.get("/suggestions")
async def suggestions(db: DB):
    result = await db.execute(select(OptionTrade).where(OptionTrade.status == "open"))
    trades = result.scalars().all()
    tickers = list({t.ticker for t in trades})

    async def _price(ticker: str) -> tuple[str, float | None]:
        try:
            return ticker, yf_svc.get_quote(ticker)["price"]
        except Exception:
            return ticker, None

    price_results = await asyncio.gather(*[_price(t) for t in tickers])
    prices = {ticker: price for ticker, price in price_results if price is not None}

    trade_dicts = [
        {
            "id": t.id, "ticker": t.ticker, "option_type": t.option_type,
            "direction": t.direction, "strike_price": t.strike_price,
            "expiry_date": t.expiry_date, "premium": t.premium,
            "quantity": t.quantity, "status": t.status,
        }
        for t in trades
    ]
    return sug_svc.evaluate_all(trade_dicts, prices)


@router.get("/{trade_id}")
async def get_trade(trade_id: int, db: DB):
    result = await db.execute(select(OptionTrade).where(OptionTrade.id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(404, "Trade not found")
    return trade


@router.put("/{trade_id}")
async def update_trade(trade_id: int, body: OptionTradeUpdate, db: DB):
    result = await db.execute(select(OptionTrade).where(OptionTrade.id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(404, "Trade not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(trade, field, value)
    await db.commit()
    await db.refresh(trade)
    return trade


@router.delete("/{trade_id}")
async def delete_trade(trade_id: int, db: DB):
    result = await db.execute(select(OptionTrade).where(OptionTrade.id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(404, "Trade not found")
    await db.delete(trade)
    await db.commit()
    return {"success": True}


@router.post("/ocr")
async def ocr_upload(file: UploadFile = File(...)):
    contents = await file.read()
    media_type = file.content_type or "image/png"
    try:
        trades = ocr_svc.extract_trades_from_image(contents, media_type)
        return trades
    except Exception as e:
        raise HTTPException(500, f"OCR failed: {e}")
