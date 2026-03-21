"""Prototype market-data ingest: fetch one symbol and store timeframe chunks in Firestore."""

import argparse
import asyncio
import json
from datetime import datetime, timezone

from app.db.firestore import get_firestore
from app.services.yahoo_finance import TIMEFRAME_CONFIG, get_bars_for_timeframe

COLLECTION = "market_series_demo"


def _build_chunk_id(symbol: str, timeframe: str, bars: list[dict]) -> str:
    start = datetime.fromtimestamp(bars[0]["time"], tz=timezone.utc).strftime("%Y%m%d")
    end = datetime.fromtimestamp(bars[-1]["time"], tz=timezone.utc).strftime("%Y%m%d")
    return f"{symbol}_{timeframe}_{start}_{end}"


async def ingest_timeframe(symbol: str, timeframe: str) -> dict:
    bars = get_bars_for_timeframe(symbol, timeframe)
    if not bars:
        raise RuntimeError(f"No bars returned for {symbol} ({timeframe})")

    chunk_id = _build_chunk_id(symbol, timeframe, bars)
    payload = {
        "symbol": symbol,
        "timeframe": timeframe,
        "source": "yahoo",
        "providerInterval": TIMEFRAME_CONFIG[timeframe]["interval"],
        "providerPeriod": TIMEFRAME_CONFIG[timeframe]["period"],
        "startTs": bars[0]["time"],
        "endTs": bars[-1]["time"],
        "count": len(bars),
        "bars": bars,
        "ingestedAt": datetime.now(timezone.utc).isoformat(),
    }

    db = get_firestore()
    doc_ref = (
        db.collection(COLLECTION)
        .document(symbol)
        .collection("timeframes")
        .document(timeframe)
        .collection("chunks")
        .document(chunk_id)
    )
    await doc_ref.set(payload)

    stored = await doc_ref.get()
    if not stored.exists:
        raise RuntimeError(f"Write succeeded but document {doc_ref.path} was not readable")

    doc = stored.to_dict() or {}
    stored_bars = doc.get("bars", [])
    return {
        "path": doc_ref.path,
        "timeframe": timeframe,
        "providerInterval": doc.get("providerInterval"),
        "providerPeriod": doc.get("providerPeriod"),
        "count": doc.get("count"),
        "startTs": doc.get("startTs"),
        "endTs": doc.get("endTs"),
        "firstBar": stored_bars[0] if stored_bars else None,
        "lastBar": stored_bars[-1] if stored_bars else None,
    }


async def ingest_many(symbol: str, timeframes: list[str]) -> dict:
    results = []
    for timeframe in timeframes:
        try:
            results.append(await ingest_timeframe(symbol, timeframe))
        except Exception as exc:
            results.append({
                "timeframe": timeframe,
                "error": str(exc),
            })
    return {
        "symbol": symbol,
        "collection": COLLECTION,
        "timeframes": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument(
        "--timeframes",
        nargs="+",
        default=["1d"],
        choices=sorted(TIMEFRAME_CONFIG.keys()),
        help="Timeframes to ingest. Example: --timeframes 1d 1h 5m 1m",
    )
    args = parser.parse_args()

    result = asyncio.run(ingest_many(args.symbol.upper(), args.timeframes))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
