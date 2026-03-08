"""Fundamental analysis data service using yfinance."""

import yfinance as yf


def get_fundamentals(ticker: str) -> dict:
    """Get fundamental financial metrics for a stock."""
    info = yf.Ticker(ticker).info or {}
    return {
        "ticker": ticker,
        "peRatio": info.get("trailingPE"),
        "forwardPE": info.get("forwardPE"),
        "pegRatio": info.get("pegRatio"),
        "priceToBook": info.get("priceToBook"),
        "priceToSales": info.get("priceToSalesTrailing12Months"),
        "epsTTM": info.get("trailingEps"),
        "revenue": info.get("totalRevenue"),
        "revenueGrowth": info.get("revenueGrowth"),
        "grossMargins": info.get("grossMargins"),
        "operatingMargins": info.get("operatingMargins"),
        "profitMargins": info.get("profitMargins"),
        "debtToEquity": info.get("debtToEquity"),
        "currentRatio": info.get("currentRatio"),
        "returnOnEquity": info.get("returnOnEquity"),
        "returnOnAssets": info.get("returnOnAssets"),
        "dividendYield": info.get("dividendYield"),
        "beta": info.get("beta"),
        "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh"),
        "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow"),
        "analystTargetPrice": info.get("targetMeanPrice"),
    }


def get_analyst_ratings(ticker: str) -> dict:
    """Get analyst ratings and consensus for a stock."""
    info = yf.Ticker(ticker).info or {}
    return {
        "ticker": ticker,
        "strongBuy": info.get("strongBuy", 0),
        "buy": info.get("buy", 0),
        "hold": info.get("hold", 0),
        "sell": info.get("sell", 0),
        "strongSell": info.get("strongSell", 0),
        "consensus": info.get("recommendationKey", "").replace("_", " ").title(),
        "targetMeanPrice": info.get("targetMeanPrice"),
        "targetHighPrice": info.get("targetHighPrice"),
        "targetLowPrice": info.get("targetLowPrice"),
        "numAnalysts": info.get("numberOfAnalystOpinions"),
    }


def get_earnings_history(ticker: str) -> list[dict]:
    """Get last 4 quarters of earnings history."""
    t = yf.Ticker(ticker)
    results = []
    try:
        hist = t.earnings_history
        if hist is not None and not hist.empty:
            for _, row in hist.tail(4).iterrows():
                results.append({
                    "date": str(row.name)[:10] if hasattr(row.name, '__str__') else str(row.name),
                    "epsEstimate": float(row.get("epsEstimate") or row.get("EPS Estimate", 0)) if row.get("epsEstimate") is not None or row.get("EPS Estimate") is not None else None,
                    "epsActual": float(row.get("epsActual") or row.get("Reported EPS", 0)) if row.get("epsActual") is not None or row.get("Reported EPS") is not None else None,
                    "surprisePercent": float(row.get("surprisePercent") or row.get("Surprise(%)", 0)) if row.get("surprisePercent") is not None or row.get("Surprise(%)") is not None else None,
                })
    except Exception:
        pass
    return results


def get_volume_analysis(ticker: str) -> dict:
    """Get volume analysis metrics for a stock."""
    t = yf.Ticker(ticker)
    hist = t.history(period="3mo")
    if hist.empty:
        return {"ticker": ticker, "error": "No data available"}

    volumes = hist["Volume"].dropna()
    avg20 = float(volumes.tail(20).mean()) if len(volumes) >= 20 else float(volumes.mean())
    avg50 = float(volumes.tail(50).mean()) if len(volumes) >= 50 else float(volumes.mean())
    current_vol = float(volumes.iloc[-1]) if len(volumes) > 0 else 0
    relative_volume = round(current_vol / avg20, 2) if avg20 > 0 else 1.0

    # Determine trend: compare recent 10-day avg vs prior 10-day avg
    trend = "stable"
    if len(volumes) >= 20:
        recent = float(volumes.tail(10).mean())
        prior = float(volumes.iloc[-20:-10].mean())
        if prior > 0:
            change = (recent - prior) / prior
            if change > 0.1:
                trend = "increasing"
            elif change < -0.1:
                trend = "decreasing"

    return {
        "ticker": ticker,
        "avg20DayVolume": round(avg20),
        "avg50DayVolume": round(avg50),
        "currentVolume": round(current_vol),
        "relativeVolume": relative_volume,
        "volumeTrend": trend,
    }
