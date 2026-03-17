"""Finnhub API service — real-time quotes, news with NLP sentiment, insider transactions.

Free tier: 60 calls/minute.
Covers: company news + sentiment scores, insider buy/sell transactions,
        analyst recommendation trends, financial metrics, earnings calendar.
"""

import asyncio
import httpx
from datetime import date, timedelta

from app.core.config import settings

FINNHUB_BASE = "https://finnhub.io/api/v1"


async def _get(path: str, params: dict | None = None) -> dict | list:
    url = f"{FINNHUB_BASE}{path}"
    p = {"token": settings.finnhub_api_key}
    if params:
        p.update(params)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=p)
        r.raise_for_status()
        return r.json()


async def get_news_with_sentiment(ticker: str, days: int = 7) -> dict:
    """
    Get recent company news articles and aggregate NLP sentiment scores.

    Returns:
        articles: list of recent headlines with source, url, datetime, summary
        sentiment: aggregate buzz score, sentiment signal, bearish/bullish %
    """
    to_date = date.today().isoformat()
    from_date = (date.today() - timedelta(days=days)).isoformat()

    news_raw, sentiment_raw = await asyncio.gather(
        _get("/company-news", {"symbol": ticker, "from": from_date, "to": to_date}),
        _get("/news-sentiment", {"symbol": ticker}),
    )

    articles = []
    for a in (news_raw[:20] if isinstance(news_raw, list) else []):
        articles.append({
            "headline": a.get("headline", ""),
            "source": a.get("source", ""),
            "url": a.get("url", ""),
            "publishedAt": a.get("datetime", ""),
            "summary": a.get("summary", ""),
            "image": a.get("image", ""),
        })

    sentiment = sentiment_raw if isinstance(sentiment_raw, dict) else {}

    return {
        "ticker": ticker,
        "articles": articles,
        "sentiment": {
            "buzz": sentiment.get("buzz", {}),
            "companyNewsScore": sentiment.get("companyNewsScore"),
            "sectorAverageBullishPercent": sentiment.get("sectorAverageBullishPercent"),
            "sectorAverageNewsScore": sentiment.get("sectorAverageNewsScore"),
            "sentiment": sentiment.get("sentiment", {}),
        },
    }


async def get_insider_transactions(ticker: str) -> dict:
    """
    Insider buy/sell transactions from SEC Form 4 filings.

    Returns list of transactions with: name, title, transactionType,
    transactionDate, transactionPrice, transactionShares, sharesOwned.
    """
    data = await _get("/stock/insider-transactions", {"symbol": ticker})
    if not isinstance(data, dict):
        return {"ticker": ticker, "data": []}

    transactions = data.get("data", []) or []
    return {
        "ticker": ticker,
        "transactions": [
            {
                "name": t.get("name", ""),
                "title": t.get("share", ""),
                "transactionType": t.get("transactionCode", ""),
                "transactionDate": t.get("transactionDate", ""),
                "transactionPrice": t.get("transactionPrice"),
                "transactionShares": t.get("change"),
                "sharesOwned": t.get("share"),
                "filingDate": t.get("filingDate", ""),
            }
            for t in transactions[:20]
        ],
    }


async def get_recommendation_trends(ticker: str) -> list[dict]:
    """
    Latest analyst recommendation trends (last 4 months).

    Each entry: period, strongBuy, buy, hold, sell, strongSell counts.
    """
    data = await _get("/stock/recommendation", {"symbol": ticker})
    items = data if isinstance(data, list) else []
    return [
        {
            "period": r.get("period", ""),
            "strongBuy": r.get("strongBuy", 0),
            "buy": r.get("buy", 0),
            "hold": r.get("hold", 0),
            "sell": r.get("sell", 0),
            "strongSell": r.get("strongSell", 0),
        }
        for r in items[:4]
    ]


async def get_basic_financials(ticker: str) -> dict:
    """
    60+ financial metrics from Finnhub: 52-week high/low, beta, P/E, P/S,
    revenue growth, margin trends, EPS, and more.
    """
    data = await _get("/stock/metric", {"symbol": ticker, "metric": "all"})
    return data if isinstance(data, dict) else {}


async def get_earnings_calendar(ticker: str) -> list[dict]:
    """Upcoming and recent earnings dates with EPS/revenue estimates and actuals."""
    to_date = (date.today() + timedelta(days=90)).isoformat()
    from_date = (date.today() - timedelta(days=90)).isoformat()
    data = await _get("/calendar/earnings", {"symbol": ticker, "from": from_date, "to": to_date})
    if isinstance(data, dict):
        earnings_list = data.get("earningsCalendar", []) or []
    else:
        earnings_list = []
    return [
        {
            "date": e.get("date", ""),
            "epsEstimate": e.get("epsEstimate"),
            "epsActual": e.get("epsActual"),
            "revenueEstimate": e.get("revenueEstimate"),
            "revenueActual": e.get("revenueActual"),
            "quarter": e.get("quarter"),
            "year": e.get("year"),
        }
        for e in earnings_list
    ]
