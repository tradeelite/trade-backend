"""Yahoo Finance data service using yfinance."""

from datetime import datetime, timedelta, timezone

import yfinance as yf

RANGE_MAP = {
    "1D": {"days": 1,    "interval": "5m"},
    "1W": {"days": 7,    "interval": "15m"},
    "1M": {"days": 30,   "interval": "1d"},
    "3M": {"days": 90,   "interval": "1d"},
    "1Y": {"days": 365,  "interval": "1d"},
    "5Y": {"days": 1825, "interval": "1wk"},
}


def search_stocks(query: str) -> list[dict]:
    results = yf.Search(query, max_results=10)
    quotes = getattr(results, "quotes", []) or []
    return [
        {
            "ticker": q.get("symbol", ""),
            "name": q.get("shortname") or q.get("longname") or q.get("symbol", ""),
            "exchange": q.get("exchange", ""),
            "type": q.get("quoteType", "EQUITY"),
        }
        for q in quotes
        if q.get("symbol")
    ]


def get_quote(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    info = t.info or {}
    return {
        "ticker": ticker,
        "name": info.get("shortName") or info.get("longName") or ticker,
        "price": info.get("currentPrice") or info.get("regularMarketPrice") or 0,
        "change": info.get("regularMarketChange") or 0,
        "changePercent": info.get("regularMarketChangePercent") or 0,
        "open": info.get("regularMarketOpen") or info.get("open") or 0,
        "high": info.get("dayHigh") or info.get("regularMarketDayHigh") or 0,
        "low": info.get("dayLow") or info.get("regularMarketDayLow") or 0,
        "previousClose": info.get("previousClose") or info.get("regularMarketPreviousClose") or 0,
        "volume": info.get("volume") or info.get("regularMarketVolume") or 0,
        "marketCap": info.get("marketCap"),
        "peRatio": info.get("trailingPE"),
        "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh") or 0,
        "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow") or 0,
        "exchange": info.get("exchange") or "",
    }


def get_chart(ticker: str, range: str = "1M") -> list[dict]:
    cfg = RANGE_MAP.get(range, RANGE_MAP["1M"])
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=cfg["days"])
    t = yf.Ticker(ticker)
    hist = t.history(start=start, end=end, interval=cfg["interval"])
    result = []
    for ts, row in hist.iterrows():
        unix = int(ts.timestamp())
        if row["Open"] is None or row["Close"] is None:
            continue
        result.append({
            "time": unix,
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row.get("Volume") or 0),
        })
    return result


def get_company_summary(ticker: str) -> dict:
    info = yf.Ticker(ticker).info or {}
    return {
        "description": info.get("longBusinessSummary") or "",
        "sector": info.get("sector") or "",
        "industry": info.get("industry") or "",
        "website": info.get("website") or "",
        "employees": info.get("fullTimeEmployees"),
    }


def get_news(ticker: str, count: int = 10) -> list[dict]:
    t = yf.Ticker(ticker)
    news = t.news or []
    result = []
    for item in news[:count]:
        content = item.get("content", {})
        thumbnail = None
        thumb_data = content.get("thumbnail") or item.get("thumbnail")
        if isinstance(thumb_data, dict):
            resolutions = thumb_data.get("resolutions") or []
            if resolutions:
                thumbnail = resolutions[0].get("url")
        pub_time = content.get("pubDate") or item.get("providerPublishTime")
        if isinstance(pub_time, (int, float)):
            pub_time = datetime.fromtimestamp(pub_time, tz=timezone.utc).isoformat()
        result.append({
            "title": content.get("title") or item.get("title") or "",
            "publisher": content.get("provider", {}).get("displayName") or item.get("publisher") or "",
            "url": content.get("canonicalUrl", {}).get("url") or item.get("link") or "",
            "publishedAt": pub_time,
            "thumbnail": thumbnail,
        })
    return result


def get_earnings_date(ticker: str) -> str | None:
    try:
        cal = yf.Ticker(ticker).calendar or {}
        earnings = cal.get("Earnings Date")
        if earnings and len(earnings) > 0:
            d = earnings[0]
            if hasattr(d, "strftime"):
                return d.strftime("%Y-%m-%d")
            return str(d)[:10]
    except Exception:
        pass
    return None
