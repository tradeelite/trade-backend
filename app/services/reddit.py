"""Reddit public search sentiment helper for stock tickers."""

from __future__ import annotations

import re

import httpx

_BULLISH_TERMS = {
    "buy",
    "bull",
    "bullish",
    "upside",
    "breakout",
    "rally",
    "long",
    "accumulate",
    "moon",
}
_BEARISH_TERMS = {
    "sell",
    "bear",
    "bearish",
    "downside",
    "breakdown",
    "dump",
    "short",
    "overvalued",
    "crash",
}


def _classify(text: str) -> str | None:
    t = text.lower()
    bull_hits = sum(1 for w in _BULLISH_TERMS if re.search(rf"\b{re.escape(w)}\b", t))
    bear_hits = sum(1 for w in _BEARISH_TERMS if re.search(rf"\b{re.escape(w)}\b", t))
    if bull_hits == bear_hits:
        return None
    return "Bullish" if bull_hits > bear_hits else "Bearish"


async def get_sentiment(ticker: str, limit: int = 30) -> dict:
    """
    Pull recent Reddit posts mentioning ticker and estimate coarse sentiment.
    Uses public JSON endpoint (no auth); best-effort only.
    """
    q = f'"{ticker.upper()}" (stocks OR investing OR wallstreetbets OR options)'
    url = "https://www.reddit.com/search.json"
    params = {"q": q, "sort": "new", "limit": max(1, min(limit, 100))}
    headers = {"User-Agent": "TradeElite/1.0 (social sentiment)"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        raw = resp.json()

    children = (((raw or {}).get("data") or {}).get("children")) or []
    posts = []
    bullish = bearish = 0
    for item in children:
        data = (item or {}).get("data") or {}
        title = str(data.get("title") or "")
        body = str(data.get("selftext") or "")
        text = f"{title}\n{body}".strip()
        sentiment = _classify(text)
        if sentiment == "Bullish":
            bullish += 1
        elif sentiment == "Bearish":
            bearish += 1
        posts.append(
            {
                "id": data.get("id"),
                "title": title,
                "body": body[:400],
                "subreddit": data.get("subreddit"),
                "author": data.get("author"),
                "url": f"https://reddit.com{data.get('permalink', '')}",
                "createdAt": data.get("created_utc"),
                "score": data.get("score"),
                "numComments": data.get("num_comments"),
                "sentiment": sentiment,
            }
        )

    tagged = bullish + bearish
    bullish_percent = round(bullish / tagged * 100, 1) if tagged > 0 else None
    return {
        "postCount": len(posts),
        "bullishPercent": bullish_percent,
        "bullishCount": bullish,
        "bearishCount": bearish,
        "posts": posts,
    }
