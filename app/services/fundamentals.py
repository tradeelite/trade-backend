"""Fundamental analysis data service using yfinance.

All data is free with no API key or rate limits.
yfinance wraps Yahoo Finance and covers:
  - Financial statements (income, balance sheet, cash flow — annual + quarterly)
  - Insider transactions (Form 4 filings)
  - Institutional holdings (13F filings)
  - Analyst upgrades/downgrades and price targets
  - Earnings history, dividends, volume analysis
"""

import pandas as pd
import yfinance as yf


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_float(v) -> float | None:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return float(v)
    except Exception:
        return None


def _safe_int(v) -> int | None:
    f = _safe_float(v)
    return int(f) if f is not None else None


def _fmt_date(v) -> str:
    """Convert a pandas Timestamp, datetime, or string to YYYY-MM-DD."""
    try:
        return str(v)[:10]
    except Exception:
        return ""


def _df_to_periods(df: pd.DataFrame, limit: int = 5) -> list[dict]:
    """
    Convert a yfinance financial statement DataFrame to a list of period dicts.

    DataFrame layout: index = metric names, columns = period dates (newest first).
    Returns: [{"date": "YYYY-MM-DD", "MetricName": float, ...}, ...]
    """
    if df is None or df.empty:
        return []
    result = []
    for col in list(df.columns)[:limit]:
        period: dict = {"date": _fmt_date(col)}
        for metric in df.index:
            val = df.loc[metric, col]
            f = _safe_float(val)
            if f is not None:
                # Use a clean key: strip extra whitespace
                period[str(metric).strip()] = f
        result.append(period)
    return result


# ---------------------------------------------------------------------------
# Core fundamentals (from .info)
# ---------------------------------------------------------------------------

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
        "evToEbitda": info.get("enterpriseToEbitda"),
        "evToRevenue": info.get("enterpriseToRevenue"),
        "epsTTM": info.get("trailingEps"),
        "forwardEps": info.get("forwardEps"),
        "bookValuePerShare": info.get("bookValue"),
        "revenue": info.get("totalRevenue"),
        "revenueGrowth": info.get("revenueGrowth"),
        "earningsGrowth": info.get("earningsGrowth"),
        "earningsQuarterlyGrowth": info.get("earningsQuarterlyGrowth"),
        "grossMargins": info.get("grossMargins"),
        "operatingMargins": info.get("operatingMargins"),
        "profitMargins": info.get("profitMargins"),
        "ebitdaMargins": info.get("ebitdaMargins"),
        "freeCashflow": info.get("freeCashflow"),
        "operatingCashflow": info.get("operatingCashflow"),
        "totalCash": info.get("totalCash"),
        "totalDebt": info.get("totalDebt"),
        "debtToEquity": info.get("debtToEquity"),
        "currentRatio": info.get("currentRatio"),
        "quickRatio": info.get("quickRatio"),
        "returnOnEquity": info.get("returnOnEquity"),
        "returnOnAssets": info.get("returnOnAssets"),
        "dividendYield": info.get("dividendYield"),
        "payoutRatio": info.get("payoutRatio"),
        "beta": info.get("beta"),
        "marketCap": info.get("marketCap"),
        "enterpriseValue": info.get("enterpriseValue"),
        "sharesOutstanding": info.get("sharesOutstanding"),
        "floatShares": info.get("floatShares"),
        "sharesShort": info.get("sharesShort"),
        "shortRatio": info.get("shortRatio"),
        "shortPercentOfFloat": info.get("shortPercentOfFloat"),
        "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh"),
        "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow"),
        "fiftyDayAverage": info.get("fiftyDayAverage"),
        "twoHundredDayAverage": info.get("twoHundredDayAverage"),
        "analystTargetPrice": info.get("targetMeanPrice"),
    }


# ---------------------------------------------------------------------------
# Financial statements (income, balance sheet, cash flow)
# ---------------------------------------------------------------------------

def get_financial_statements(ticker: str) -> dict:
    """
    Get full financial statements from Yahoo Finance.

    Returns annual and quarterly data for:
    - Income statement: revenue, gross profit, operating income, net income, EPS, margins
    - Balance sheet: assets, liabilities, equity, debt, cash
    - Cash flow: operating CF, investing CF, FCF, CapEx, dividends, buybacks
    """
    t = yf.Ticker(ticker)
    return {
        "ticker": ticker,
        "incomeStatement": {
            "annual": _df_to_periods(t.income_stmt, limit=5),
            "quarterly": _df_to_periods(t.quarterly_income_stmt, limit=8),
        },
        "balanceSheet": {
            "annual": _df_to_periods(t.balance_sheet, limit=5),
            "quarterly": _df_to_periods(t.quarterly_balance_sheet, limit=8),
        },
        "cashFlow": {
            "annual": _df_to_periods(t.cashflow, limit=5),
            "quarterly": _df_to_periods(t.quarterly_cashflow, limit=8),
        },
    }


# ---------------------------------------------------------------------------
# Insider transactions
# ---------------------------------------------------------------------------

def get_insider_transactions(ticker: str) -> dict:
    """
    Get recent insider buy/sell transactions from Yahoo Finance (Form 4 filings).

    Returns name, title, transaction type (Buy/Sell/Option Exercise),
    date, shares transacted, value, and ownership type.
    """
    t = yf.Ticker(ticker)
    transactions = []
    try:
        df = t.insider_transactions
        if df is not None and not df.empty:
            for _, row in df.head(30).iterrows():
                shares = _safe_int(row.get("Shares"))
                value = _safe_float(row.get("Value"))
                transactions.append({
                    "insider": str(row.get("Insider") or ""),
                    "position": str(row.get("Position") or ""),
                    "transaction": str(row.get("Transaction") or ""),
                    "date": _fmt_date(row.get("Start Date") or row.get("Date") or ""),
                    "shares": shares,
                    "value": value,
                    "ownership": str(row.get("Ownership") or ""),
                    "text": str(row.get("Text") or ""),
                })
    except Exception:
        pass

    # Summary: net buying vs selling
    buys = [tx for tx in transactions if "buy" in tx["transaction"].lower() or "purchase" in tx["transaction"].lower()]
    sells = [tx for tx in transactions if "sale" in tx["transaction"].lower() or "sell" in tx["transaction"].lower()]

    return {
        "ticker": ticker,
        "transactions": transactions,
        "summary": {
            "buyCount": len(buys),
            "sellCount": len(sells),
            "netSignal": "bullish" if len(buys) > len(sells) else "bearish" if len(sells) > len(buys) else "neutral",
        },
    }


# ---------------------------------------------------------------------------
# Institutional holdings
# ---------------------------------------------------------------------------

def get_institutional_holders(ticker: str) -> dict:
    """
    Get institutional ownership data from Yahoo Finance (13F filings).

    Returns:
    - majorHolders: % held by insiders, institutions, float
    - topHolders: top institutional investors with shares, value, % held
    - mutualFundHolders: top mutual fund investors
    """
    t = yf.Ticker(ticker)
    major: dict = {}
    top_holders = []
    mutual_fund_holders = []

    try:
        mh = t.major_holders
        if mh is not None and not mh.empty:
            # major_holders is a 2-column DataFrame: value, breakdown label
            for _, row in mh.iterrows():
                try:
                    vals = row.tolist()
                    if len(vals) >= 2:
                        major[str(vals[1]).strip()] = str(vals[0]).strip()
                except Exception:
                    pass
    except Exception:
        pass

    try:
        ih = t.institutional_holders
        if ih is not None and not ih.empty:
            for _, row in ih.head(20).iterrows():
                top_holders.append({
                    "holder": str(row.get("Holder") or ""),
                    "shares": _safe_int(row.get("Shares")),
                    "value": _safe_float(row.get("Value")),
                    "pctHeld": _safe_float(row.get("pctHeld")),
                    "dateReported": _fmt_date(row.get("Date Reported") or ""),
                    "pctChange": _safe_float(row.get("% Out")),
                })
    except Exception:
        pass

    try:
        mfh = t.mutualfund_holders
        if mfh is not None and not mfh.empty:
            for _, row in mfh.head(10).iterrows():
                mutual_fund_holders.append({
                    "holder": str(row.get("Holder") or ""),
                    "shares": _safe_int(row.get("Shares")),
                    "value": _safe_float(row.get("Value")),
                    "pctHeld": _safe_float(row.get("pctHeld")),
                    "dateReported": _fmt_date(row.get("Date Reported") or ""),
                })
    except Exception:
        pass

    return {
        "ticker": ticker,
        "majorHolders": major,
        "topInstitutionalHolders": top_holders,
        "topMutualFundHolders": mutual_fund_holders,
    }


# ---------------------------------------------------------------------------
# Analyst ratings, upgrades/downgrades, price targets
# ---------------------------------------------------------------------------

def get_analyst_ratings(ticker: str) -> dict:
    """
    Get analyst consensus ratings, price targets, and recent upgrades/downgrades.

    Combines .info consensus + .upgrades_downgrades history.
    """
    t = yf.Ticker(ticker)
    info = t.info or {}

    # Consensus summary from .info
    consensus = {
        "ticker": ticker,
        "strongBuy": info.get("strongBuy", 0) or 0,
        "buy": info.get("buy", 0) or 0,
        "hold": info.get("hold", 0) or 0,
        "sell": info.get("sell", 0) or 0,
        "strongSell": info.get("strongSell", 0) or 0,
        "consensus": (info.get("recommendationKey") or "").replace("_", " ").title(),
        "targetMeanPrice": info.get("targetMeanPrice"),
        "targetHighPrice": info.get("targetHighPrice"),
        "targetLowPrice": info.get("targetLowPrice"),
        "targetMedianPrice": info.get("targetMedianPrice"),
        "numAnalysts": info.get("numberOfAnalystOpinions"),
    }

    # Recent upgrades/downgrades
    upgrades = []
    try:
        df = t.upgrades_downgrades
        if df is not None and not df.empty:
            # Index is date, columns: Firm, To Grade, From Grade, Action
            df_sorted = df.sort_index(ascending=False)
            for date_idx, row in df_sorted.head(20).iterrows():
                upgrades.append({
                    "date": _fmt_date(date_idx),
                    "firm": str(row.get("Firm") or ""),
                    "toGrade": str(row.get("To Grade") or row.get("toGrade") or ""),
                    "fromGrade": str(row.get("From Grade") or row.get("fromGrade") or ""),
                    "action": str(row.get("Action") or ""),
                })
    except Exception:
        pass

    # Recommendation trend (monthly buy/hold/sell counts)
    rec_trend = []
    try:
        df = t.recommendations
        if df is not None and not df.empty:
            for _, row in df.head(6).iterrows():
                rec_trend.append({
                    "period": str(row.get("period") or ""),
                    "strongBuy": _safe_int(row.get("strongBuy")) or 0,
                    "buy": _safe_int(row.get("buy")) or 0,
                    "hold": _safe_int(row.get("hold")) or 0,
                    "sell": _safe_int(row.get("sell")) or 0,
                    "strongSell": _safe_int(row.get("strongSell")) or 0,
                })
    except Exception:
        pass

    return {**consensus, "recentUpgradesDowngrades": upgrades, "recommendationTrend": rec_trend}


# ---------------------------------------------------------------------------
# Earnings history
# ---------------------------------------------------------------------------

def get_earnings_history(ticker: str) -> list[dict]:
    """Get last 8 quarters of earnings history: estimated EPS, actual EPS, surprise %."""
    t = yf.Ticker(ticker)
    results = []
    try:
        hist = t.earnings_history
        if hist is not None and not hist.empty:
            for _, row in hist.tail(8).iterrows():
                results.append({
                    "date": _fmt_date(row.name) if hasattr(row.name, "__str__") else str(row.name),
                    "epsEstimate": _safe_float(row.get("epsEstimate") or row.get("EPS Estimate")),
                    "epsActual": _safe_float(row.get("epsActual") or row.get("Reported EPS")),
                    "surprisePercent": _safe_float(row.get("surprisePercent") or row.get("Surprise(%)")),
                })
    except Exception:
        pass
    return list(reversed(results))  # newest first


# ---------------------------------------------------------------------------
# Dividends
# ---------------------------------------------------------------------------

def get_dividends(ticker: str) -> dict:
    """Get full dividend history and current yield metrics."""
    t = yf.Ticker(ticker)
    info = t.info or {}
    history = []
    try:
        div_series = t.dividends
        if div_series is not None and not div_series.empty:
            for date_idx, amount in div_series.tail(20).items():
                history.append({
                    "date": _fmt_date(date_idx),
                    "amount": _safe_float(amount),
                })
            history = list(reversed(history))  # newest first
    except Exception:
        pass

    return {
        "ticker": ticker,
        "dividendYield": info.get("dividendYield"),
        "dividendRate": info.get("dividendRate"),
        "payoutRatio": info.get("payoutRatio"),
        "exDividendDate": _fmt_date(info.get("exDividendDate") or ""),
        "lastDividendDate": _fmt_date(info.get("lastDividendDate") or ""),
        "fiveYearAvgDividendYield": info.get("fiveYearAvgDividendYield"),
        "history": history,
    }


# ---------------------------------------------------------------------------
# Volume analysis
# ---------------------------------------------------------------------------

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
