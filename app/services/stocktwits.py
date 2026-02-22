"""StockTwits public API service."""

import httpx


async def get_sentiment(ticker: str) -> dict:
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker.upper()}.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers={"User-Agent": "TradeElite/1.0"})
        resp.raise_for_status()
        data = resp.json()

    messages_raw = data.get("messages") or []
    messages = [
        {
            "id": m["id"],
            "body": m["body"],
            "user": m["user"]["username"],
            "sentiment": (m.get("entities") or {}).get("sentiment", {}).get("basic") if m.get("entities") else None,
            "createdAt": m["created_at"],
        }
        for m in messages_raw
    ]

    bullish = sum(1 for m in messages if m["sentiment"] == "Bullish")
    bearish = sum(1 for m in messages if m["sentiment"] == "Bearish")
    tagged = bullish + bearish
    bullish_percent = round(bullish / tagged * 100) if tagged > 0 else None

    return {
        "watchlistCount": (data.get("symbol") or {}).get("watchlist_count"),
        "bullishPercent": bullish_percent,
        "bullishCount": bullish,
        "bearishCount": bearish,
        "messages": messages,
    }
