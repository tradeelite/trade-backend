"""Options trades CRUD + OCR + suggestions API routes."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.db.firestore import get_firestore
from app.db.repositories.options import OptionRepository
from app.db.schemas import OptionTradeCreate, OptionTradeUpdate
from app.services import ocr as ocr_svc
from app.services import suggestions as sug_svc
from app.services import yahoo_finance as yf_svc

router = APIRouter(prefix="/api/options", tags=["options"])


def get_option_repo() -> OptionRepository:
    return OptionRepository(get_firestore())


OptionDB = Annotated[OptionRepository, Depends(get_option_repo)]


@router.get("")
async def list_trades(repo: OptionDB, status: str = Query(None)):
    return await repo.get_all(status=status)


@router.post("", status_code=201)
async def create_trade(body: OptionTradeCreate, repo: OptionDB):
    data = body.model_dump()
    data["ticker"] = data["ticker"].upper()
    data["status"] = "open"
    return await repo.create(data)


@router.get("/suggestions")
async def suggestions(repo: OptionDB):
    trades = await repo.get_all(status="open")
    tickers = list({t["ticker"] for t in trades})

    async def _price(ticker: str) -> tuple[str, float | None]:
        try:
            return ticker, yf_svc.get_quote(ticker)["price"]
        except Exception:
            return ticker, None

    price_results = await asyncio.gather(*[_price(t) for t in tickers])
    prices = {ticker: price for ticker, price in price_results if price is not None}
    return sug_svc.evaluate_all(trades, prices)


@router.get("/{trade_id}")
async def get_trade(trade_id: str, repo: OptionDB):
    trade = await repo.get_by_id(trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    return trade


@router.put("/{trade_id}")
async def update_trade(trade_id: str, body: OptionTradeUpdate, repo: OptionDB):
    data = body.model_dump(exclude_none=True)
    trade = await repo.update(trade_id, data)
    if not trade:
        raise HTTPException(404, "Trade not found")
    return trade


@router.delete("/{trade_id}")
async def delete_trade(trade_id: str, repo: OptionDB):
    deleted = await repo.delete(trade_id)
    if not deleted:
        raise HTTPException(404, "Trade not found")
    return {"success": True}


@router.post("/ocr")
async def ocr_upload(file: UploadFile = File(...)):
    contents = await file.read()
    media_type = file.content_type or "image/png"
    try:
        return ocr_svc.extract_trades_from_image(contents, media_type)
    except Exception as e:
        raise HTTPException(500, f"OCR failed: {e}")
