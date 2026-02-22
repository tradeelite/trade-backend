"""Stock data API routes."""

import asyncio

from fastapi import APIRouter, HTTPException, Query

from app.services import indicators as ind_svc
from app.services import stocktwits, yahoo_finance as yf_svc

router = APIRouter(prefix="/api/stocks", tags=["stocks"])

VALID_RANGES = {"1D", "1W", "1M", "3M", "1Y", "5Y"}


@router.get("/search")
def search(q: str = Query(...)):
    if not q:
        raise HTTPException(400, "Query required")
    try:
        return yf_svc.search_stocks(q)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/quote")
def quote(ticker: str):
    try:
        return yf_svc.get_quote(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/chart")
def chart(ticker: str, range: str = Query("1M")):
    if range not in VALID_RANGES:
        raise HTTPException(400, f"Invalid range. Use one of: {', '.join(VALID_RANGES)}")
    try:
        return yf_svc.get_chart(ticker.upper(), range)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/summary")
def summary(ticker: str):
    try:
        return yf_svc.get_company_summary(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/indicators")
def indicators(ticker: str, range: str = Query("1M")):
    if range not in VALID_RANGES:
        raise HTTPException(400, f"Invalid range.")
    try:
        chart_data = yf_svc.get_chart(ticker.upper(), range)
        return ind_svc.compute_all(chart_data)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/news")
def news(ticker: str):
    try:
        return yf_svc.get_news(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/sentiment")
async def sentiment(ticker: str):
    try:
        return await stocktwits.get_sentiment(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/earnings")
async def earnings(tickers: str = Query(...)):
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]

    async def _fetch(ticker: str) -> tuple[str, str | None]:
        try:
            return ticker, yf_svc.get_earnings_date(ticker)
        except Exception:
            return ticker, None

    results = await asyncio.gather(*[_fetch(t) for t in ticker_list])
    return dict(results)
