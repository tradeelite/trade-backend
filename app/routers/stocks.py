"""Stock data API routes."""

import asyncio
import time

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.services import edgar as edgar_svc
from app.services import finnhub as finnhub_svc
from app.services import fmp as fmp_svc
from app.services import fundamentals as fund_svc
from app.services import indicators as ind_svc
from app.services import stocktwits, yahoo_finance as yf_svc
from app.services import technical_signals as ts_svc

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


def _normalize_signal(v: str | None) -> str:
    """Map any directional string to bullish/bearish/neutral."""
    if not v:
        return "neutral"
    v = str(v).lower()
    if v in ("bullish", "up", "positive", "strong", "buy"):
        return "bullish"
    if v in ("bearish", "down", "negative", "weak", "sell"):
        return "bearish"
    return "neutral"


def _normalize_analysis(raw: dict) -> dict:
    """Normalize agent output to match the frontend TypeScript schema."""
    import re as _re

    def _d(v) -> dict:
        """Ensure value is a dict; return {} if it's a string or None."""
        return v if isinstance(v, dict) else {}

    def _to_float(v):
        """Best-effort numeric coercion for model outputs (handles scalar/list/dict/string)."""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, list):
            for item in v:
                coerced = _to_float(item)
                if coerced is not None:
                    return coerced
            return None
        if isinstance(v, dict):
            # Prefer common numeric keys first.
            for k in ("value", "current", "mean", "number"):
                if k in v:
                    coerced = _to_float(v.get(k))
                    if coerced is not None:
                        return coerced
            # Fallback: first coercible value.
            for item in v.values():
                coerced = _to_float(item)
                if coerced is not None:
                    return coerced
            return None
        try:
            s = str(v).strip().replace("%", "").replace(",", "")
            if not s:
                return None
            return float(s)
        except Exception:
            return None

    tech = _d(raw.get("technical"))
    fund = _d(raw.get("fundamental"))
    news = _d(raw.get("news"))

    # ── Technical ──────────────────────────────────────────────────────────
    trend = _d(tech.get("trend"))
    momentum = _d(tech.get("momentum"))
    volume = _d(tech.get("volume"))
    signals = _d(tech.get("signals"))

    # support/resistance may be top-level or inside supportResistance
    sr = _d(tech.get("supportResistance"))
    support = sr.get("support") or tech.get("support")
    resistance = sr.get("resistance") or tech.get("resistance")

    # rsi can be a number or nested
    rsi = momentum.get("rsi")
    if isinstance(rsi, dict):
        rsi = rsi.get("value") or rsi.get("rsi")

    # macd: accept object or string
    macd_raw = momentum.get("macd") or momentum.get("macdLine") or ""
    if isinstance(macd_raw, dict):
        ml = macd_raw.get("macdLine", 0)
        sl = macd_raw.get("signalLine", 0)
        macd_str = "bullish" if ml > sl else "bearish" if ml < sl else "neutral"
    else:
        macd_str = str(macd_raw)

    # bollinger position
    bb_raw = momentum.get("bollingerPosition") or momentum.get("bollingerBands") or ""
    if isinstance(bb_raw, dict):
        upper = bb_raw.get("upper", 0)
        lower = bb_raw.get("lower", 0)
        bb_str = "upper" if upper else "middle" if lower else str(bb_raw)
    else:
        bb_str = str(bb_raw)

    # momentum signal
    mom_signal = _normalize_signal(momentum.get("signal") or momentum.get("overallSignal"))
    if mom_signal == "neutral" and rsi:
        mom_signal = "bullish" if float(rsi) < 40 else "bearish" if float(rsi) > 65 else "neutral"

    # volume metrics
    vol_avg = volume.get("average") or volume.get("avgVolume") or 0
    vol_recent = volume.get("recent") or volume.get("currentVolume") or vol_avg
    rel_vol = round(vol_recent / vol_avg, 2) if vol_avg else None
    vol_signal = _normalize_signal(volume.get("signal") or ("bullish" if rel_vol and rel_vol > 1.2 else "neutral"))
    vol_trend = volume.get("trend") or ("increasing" if rel_vol and rel_vol > 1.1 else "stable")

    # snapshot
    snap = _d(tech.get("snapshot"))
    normalized_snapshot = {
        "currentPrice": snap.get("currentPrice"),
        "changePercent": snap.get("changePercent"),
        "relativeVolume": snap.get("relativeVolume") or rel_vol,
        "distanceFrom52wHigh": snap.get("distanceFrom52wHigh"),
        "distanceFrom52wLow": snap.get("distanceFrom52wLow"),
        "distanceFrom200SMA": snap.get("distanceFrom200SMA"),
    } if snap else None

    # moving averages — pass through as-is (agent returns full array)
    moving_averages = tech.get("movingAverages") or []
    for ma in moving_averages:
        if isinstance(ma.get("value"), (int, float)):
            ma["value"] = float(ma["value"])

    # trendStrength
    ts = _d(tech.get("trendStrength"))
    normalized_ts = {
        "adx": float(ts["adx"]) if ts.get("adx") is not None else None,
        "adxStrength": ts.get("adxStrength") or "moderate",
        "plusDI": float(ts["plusDI"]) if ts.get("plusDI") is not None else None,
        "minusDI": float(ts["minusDI"]) if ts.get("minusDI") is not None else None,
        "diControl": ts.get("diControl") or "neutral",
        "relativeStrength1M": ts.get("relativeStrength1M"),
        "relativeStrength3M": ts.get("relativeStrength3M"),
        "relativeStrength6M": ts.get("relativeStrength6M"),
    } if ts else None

    # volatility
    vola = _d(tech.get("volatility"))
    normalized_vola = {
        "bollingerPosition": vola.get("bollingerPosition") or bb_str,
        "bollingerBandwidth": vola.get("bollingerBandwidth"),
        "atr": float(vola["atr"]) if vola.get("atr") is not None else None,
        "atrPercent": float(vola["atrPercent"]) if vola.get("atrPercent") is not None else None,
        "beta": float(vola["beta"]) if vola.get("beta") is not None else None,
        "iv": vola.get("iv"),
    } if vola else None

    # aggregatedSignals
    agg = _d(tech.get("aggregatedSignals"))
    sig_count = _d(agg.get("signalCount"))
    normalized_agg = {
        "barchartOpinion": agg.get("barchartOpinion") or "",
        "tradingViewRating": agg.get("tradingViewRating") or "",
        "signalCount": {
            "buy": int(sig_count.get("buy") or 0),
            "neutral": int(sig_count.get("neutral") or 0),
            "sell": int(sig_count.get("sell") or 0),
        },
    } if agg else None

    # predictions — pass through directly
    def _pass_prediction(p):
        if not p or not isinstance(p, dict):
            return None
        return p

    normalized_tech = {
        "ticker": raw.get("ticker", ""),
        "snapshot": normalized_snapshot,
        "trend": {
            "direction": _normalize_signal(trend.get("direction") or tech.get("overallTrend")),
            "strength": trend.get("strength") or "moderate",
            "detail": trend.get("detail") or trend.get("description") or "",
            "chartPattern": trend.get("chartPattern"),
            "goldenCross": trend.get("goldenCross"),
            "deathCross": trend.get("deathCross"),
        },
        "movingAverages": moving_averages,
        "momentum": {
            "signal": mom_signal,
            "rsi": float(rsi) if rsi is not None else None,
            "rsiWeekly": momentum.get("rsiWeekly"),
            "rsiStatus": momentum.get("rsiStatus"),
            "rsiDivergence": momentum.get("rsiDivergence"),
            "macd": macd_str,
            "macdHistogram": momentum.get("macdHistogram"),
            "bollingerPosition": bb_str,
            "stochasticK": momentum.get("stochasticK"),
            "stochasticD": momentum.get("stochasticD"),
            "stochasticStatus": momentum.get("stochasticStatus"),
            "roc10d": momentum.get("roc10d"),
            "roc20d": momentum.get("roc20d"),
        },
        "trendStrength": normalized_ts,
        "volume": {
            "signal": vol_signal,
            "relativeVolume": rel_vol,
            "trend": vol_trend,
            "obv": volume.get("obv"),
            "vwap": volume.get("vwap"),
            "priceVsVWAP": volume.get("priceVsVWAP"),
            "accDistribution": volume.get("accDistribution"),
            "volumeConfirms": volume.get("volumeConfirms"),
        },
        "volatility": normalized_vola,
        "supportResistance": {
            "support": float(support) if support is not None else None,
            "resistance": float(resistance) if resistance is not None else None,
            "support2": tech.get("supportResistance", {}).get("support2"),
            "resistance2": tech.get("supportResistance", {}).get("resistance2"),
        },
        "aggregatedSignals": normalized_agg,
        "signals": {
            "shortTerm": _normalize_signal(signals.get("shortTerm") or raw.get("shortTerm")),
            "mediumTerm": _normalize_signal(signals.get("mediumTerm") or raw.get("mediumTerm")),
            "longTerm": _normalize_signal(signals.get("longTerm") or raw.get("longTerm")),
        },
        "shortTermPrediction": _pass_prediction(tech.get("shortTermPrediction")),
        "mediumTermPrediction": _pass_prediction(tech.get("mediumTermPrediction")),
        "longTermPrediction": _pass_prediction(tech.get("longTermPrediction")),
        "risks": tech.get("risks") or [],
        "recommendation": tech.get("recommendation") or "Hold",
        "summary": tech.get("summary") or tech.get("description") or "",
    }

    # ── Fundamental ────────────────────────────────────────────────────────
    val = _d(fund.get("valuation"))
    health = _d(fund.get("financialHealth"))
    growth = _d(fund.get("growth"))
    analyst = _d(fund.get("analystConsensus"))
    earnings_raw = _d(fund.get("earnings") or fund.get("earningsHistory"))
    attrs = _d(fund.get("attributes"))
    ai_analysis = _d(fund.get("aiAnalysis"))

    attr_valuation = _d(attrs.get("valuation"))
    attr_growth = _d(attrs.get("growth"))
    attr_fin_strength = _d(attrs.get("financialStrength"))
    attr_analyst = _d(attrs.get("analystSentiment"))

    pe = (
        val.get("peRatio")
        or val.get("pe_ratio")
        or fund.get("peRatio")
        or _d(attr_valuation.get("metrics")).get("pe")
    )
    pe_num = _to_float(pe)
    val_signal = val.get("signal") or ("overvalued" if pe_num is not None and pe_num > 35 else "undervalued" if pe_num is not None and pe_num < 15 else "fairly_valued")

    breakdown = _d(analyst.get("breakdown"))
    if not breakdown:
        # build a minimal breakdown so the bar chart doesn't crash
        rating_str = str(analyst.get("rating") or "hold").lower()
        if "strong buy" in rating_str:
            breakdown = {"strongBuy": 5, "buy": 3, "hold": 1, "sell": 0}
        elif "buy" in rating_str:
            breakdown = {"strongBuy": 2, "buy": 5, "hold": 2, "sell": 0}
        elif "sell" in rating_str:
            breakdown = {"strongBuy": 0, "buy": 1, "hold": 2, "sell": 5}
        else:
            breakdown = {"strongBuy": 1, "buy": 2, "hold": 5, "sell": 1}

    earnings_quarters = earnings_raw.get("lastQuarters") or []
    earnings_trend = earnings_raw.get("trend") or earnings_raw.get("consistency") or "inline"
    if "positive" in str(earnings_trend).lower() or "beat" in str(earnings_trend).lower():
        earnings_trend = "beating"
    elif "negative" in str(earnings_trend).lower() or "miss" in str(earnings_trend).lower():
        earnings_trend = "missing"
    else:
        earnings_trend = "inline"

    # Backward-compatible fields + full pass-through for enhanced schema.
    normalized_fund = {
        "ticker": raw.get("ticker", ""),
        "asOf": fund.get("asOf"),
        "priceContext": fund.get("priceContext"),
        "attributes": attrs or None,
        "aiAnalysis": ai_analysis or None,
        "sources": fund.get("sources") or [],
        "valuation": {
            "signal": val_signal,
            "peRatio": pe_num,
            "forwardPE": _to_float(val.get("forwardPE") or val.get("forward_pe") or _d(attr_valuation.get("metrics")).get("forwardPe")),
            "pegRatio": _to_float(val.get("pegRatio") or val.get("peg_ratio") or _d(attr_valuation.get("metrics")).get("peg")),
            "priceToBook": _to_float(val.get("priceToBook") or val.get("priceToBookRatio") or val.get("price_to_book") or _d(attr_valuation.get("metrics")).get("priceToBook")),
        },
        "financialHealth": {
            "signal": health.get("signal") or health.get("overallHealth") or ("strong" if attr_fin_strength.get("signal") == "bullish" else "weak" if attr_fin_strength.get("signal") == "bearish" else "moderate"),
            "debtToEquity": _to_float(health.get("debtToEquity") or health.get("debtToEquityRatio") or _d(attr_fin_strength.get("metrics")).get("debtToEquity")),
            "currentRatio": _to_float(health.get("currentRatio") or _d(attr_fin_strength.get("metrics")).get("currentRatio")),
            "operatingMargin": str(health.get("operatingMargin") or health.get("profitMargin") or "N/A"),
            "returnOnEquity": str(health.get("returnOnEquity") or "N/A"),
        },
        "growth": {
            "signal": growth.get("signal") or ("strong" if attr_growth.get("signal") == "bullish" else "weak" if attr_growth.get("signal") == "bearish" else "moderate"),
            "revenueGrowth": str(growth.get("revenueGrowth") or _d(attr_growth.get("metrics")).get("revenueGrowthYoYPercent") or "N/A"),
            "earningsGrowth": str(growth.get("earningsGrowth") or growth.get("epsGrowth") or _d(attr_growth.get("metrics")).get("epsGrowthYoYPercent") or "N/A"),
            "epsTTM": _to_float(growth.get("epsTTM") or growth.get("eps")),
        },
        "analystConsensus": {
            "rating": str(analyst.get("rating") or _d(attr_analyst.get("metrics")).get("consensus") or "Hold"),
            "targetPrice": _to_float(analyst.get("targetPrice") or analyst.get("target_price") or _d(attr_analyst.get("metrics")).get("targetMean")),
            "numAnalysts": int(_to_float(analyst.get("numAnalysts") or analyst.get("num_analysts") or _d(attr_analyst.get("metrics")).get("numAnalysts")) or 0),
            "breakdown": {
                "strongBuy": int(breakdown.get("strongBuy") or breakdown.get("strong_buy") or _d(attr_analyst.get("metrics")).get("strongBuy") or 0),
                "buy": int(breakdown.get("buy") or _d(attr_analyst.get("metrics")).get("buy") or 0),
                "hold": int(breakdown.get("hold") or _d(attr_analyst.get("metrics")).get("hold") or 0),
                "sell": int(breakdown.get("sell") or breakdown.get("strongSell") or (_d(attr_analyst.get("metrics")).get("sell") or 0) + (_d(attr_analyst.get("metrics")).get("strongSell") or 0)),
            },
        },
        "earnings": {
            "trend": earnings_trend,
            "lastQuarters": earnings_quarters,
        },
        "recommendation": fund.get("recommendation") or ai_analysis.get("recommendation") or "Hold",
        "summary": fund.get("summary") or ai_analysis.get("finalExplanation") or fund.get("description") or "",
    }

    # ── News ───────────────────────────────────────────────────────────────
    social = _d(news.get("socialSentiment"))
    raw_headlines = news.get("headlines") or []
    headlines = []
    for h in raw_headlines:
        if isinstance(h, dict):
            headlines.append(h)
        elif isinstance(h, str):
            headlines.append({"title": h, "source": "", "url": "", "publishedAt": ""})

    normalized_news = {
        "ticker": raw.get("ticker", ""),
        "overallSentiment": _normalize_signal(news.get("overallSentiment") or news.get("stockTwitsSentiment")),
        "socialSentiment": {
            "signal": _normalize_signal(social.get("signal") or news.get("stockTwitsSentiment")),
            "bullishPercent": social.get("bullishPercent") or (72 if _normalize_signal(news.get("stockTwitsSentiment")) == "bullish" else 40),
            "watchlistCount": social.get("watchlistCount"),
        },
        "newsSentiment": str(news.get("newsSentiment") or news.get("newsArticleSentiment") or "mixed").lower().replace("positive", "positive").replace("negative", "negative"),
        "catalysts": list(news.get("catalysts") or []),
        "risks": list(news.get("risks") or []),
        "keyEvents": list(news.get("keyEvents") or []),
        "headlines": headlines,
        "recommendation": news.get("recommendation") or "Hold",
        "summary": news.get("summary") or news.get("description") or "",
    }

    return {
        "ticker": raw.get("ticker", ""),
        "overallSignal": _normalize_signal(raw.get("overallSignal")),
        "overallRecommendation": raw.get("overallRecommendation") or "Hold",
        "confidence": raw.get("confidence") or "medium",
        "shortTerm": _normalize_signal(raw.get("shortTerm")),
        "mediumTerm": _normalize_signal(raw.get("mediumTerm")),
        "longTerm": _normalize_signal(raw.get("longTerm")),
        "technical": normalized_tech,
        "fundamental": normalized_fund,
        "news": normalized_news,
        "executiveSummary": raw.get("executiveSummary") or raw.get("summary") or "",
    }


_RICH_SECTION_KEYS = {"valuation", "profitability", "financialHealth", "growth", "earnings", "dividends"}


def _is_rich_fundamental(data: dict) -> bool:
    """Return True if the dict matches the RichFundamentalAnalysis schema."""
    return (
        isinstance(data, dict)
        and isinstance(data.get("header"), dict)
        and len(_RICH_SECTION_KEYS & set(data.keys())) >= 4
    )


def _coerce_metric_arrays(data: dict) -> dict:
    """Ensure all metric sections are lists of MetricRow dicts."""
    result = dict(data)
    for section in _RICH_SECTION_KEYS:
        val = result.get(section)
        if isinstance(val, list):
            continue  # already correct
        if isinstance(val, dict):
            # Convert dict of {name: metric_obj} to list
            rows = []
            for k, v in val.items():
                if isinstance(v, dict):
                    rows.append({
                        "metric": v.get("metric", k),
                        "value": v.get("value"),
                        "benchmark": v.get("benchmark"),
                        "signal": v.get("signal", "neutral"),
                        "signalLabel": v.get("signalLabel", "N/A"),
                        "interpretation": v.get("interpretation", ""),
                    })
                else:
                    rows.append({
                        "metric": k,
                        "value": str(v) if v is not None else None,
                        "benchmark": None,
                        "signal": "neutral",
                        "signalLabel": "N/A",
                        "interpretation": "",
                    })
            result[section] = rows
        else:
            result[section] = []
    # Ensure verdict is a list
    if not isinstance(result.get("verdict"), list):
        result["verdict"] = []
    # Ensure header has expected price/marketCap/revenue/netIncome keys
    header = result.get("header")
    if isinstance(header, dict) and "price" not in header:
        # Agent returned company-info style header — convert to expected format
        result["header"] = {
            "price": str(header.get("price", header.get("currentPrice", "N/A"))),
            "marketCap": str(header.get("marketCap", "N/A")),
            "revenue": str(header.get("revenue", header.get("totalRevenue", "N/A"))),
            "netIncome": str(header.get("netIncome", header.get("netIncomeToCommon", "N/A"))),
        }
    return result


async def _build_rich_fundamental(ticker: str) -> dict:
    """Build a RichFundamentalAnalysis dict from backend data services (no agent call)."""
    import datetime
    import yfinance as yf

    # Formatting helpers
    def _fmt_price(v) -> str:
        if v is None:
            return "N/A"
        return f"${float(v):,.2f}"

    def _fmt_large(v) -> str:
        if v is None:
            return "N/A"
        v = float(v)
        if abs(v) >= 1e12:
            return f"${v/1e12:.2f}T"
        if abs(v) >= 1e9:
            return f"${v/1e9:.2f}B"
        if abs(v) >= 1e6:
            return f"${v/1e6:.2f}M"
        return f"${v:,.0f}"

    def _fmt_pct(v, mult=1) -> str:
        if v is None:
            return "N/A"
        return f"{float(v)*mult:.2f}%"

    def _fmt_ratio(v) -> str:
        if v is None:
            return "N/A"
        return f"{float(v):.2f}x"

    # Fetch all data concurrently
    fundamentals, analyst_ratings, earnings_history, dividends = await asyncio.gather(
        asyncio.to_thread(fund_svc.get_fundamentals, ticker),
        asyncio.to_thread(fund_svc.get_analyst_ratings, ticker),
        asyncio.to_thread(fund_svc.get_earnings_history, ticker),
        asyncio.to_thread(fund_svc.get_dividends, ticker),
    )

    # Fetch extra fields from yfinance info
    yf_info: dict = {}
    try:
        yf_info = await asyncio.to_thread(lambda: yf.Ticker(ticker).info or {})
    except Exception:
        pass

    def _g(d: dict, key: str):
        v = d.get(key)
        try:
            import math
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return None
            return v
        except Exception:
            return v

    # Pull raw values
    pe_ttm = _g(fundamentals, "peRatio")
    pe_fwd = _g(fundamentals, "forwardPE")
    peg = _g(fundamentals, "pegRatio")
    ps = _g(fundamentals, "priceToSales")
    pb = _g(fundamentals, "priceToBook")
    ev_ebitda = _g(fundamentals, "evToEbitda")
    ev_revenue = _g(fundamentals, "evToRevenue")
    profit_margin = _g(fundamentals, "profitMargins")
    gross_margin = _g(fundamentals, "grossMargins")
    op_margin = _g(fundamentals, "operatingMargins")
    roe = _g(fundamentals, "returnOnEquity")
    roa = _g(fundamentals, "returnOnAssets")
    de_ratio = _g(fundamentals, "debtToEquity")
    current_ratio = _g(fundamentals, "currentRatio")
    quick_ratio = _g(fundamentals, "quickRatio")
    free_cashflow = _g(fundamentals, "freeCashflow")
    short_pct = _g(fundamentals, "shortPercentOfFloat")
    beta = _g(fundamentals, "beta")
    eps_ttm = _g(fundamentals, "epsTTM")
    eps_fwd = _g(fundamentals, "forwardEps")
    rev_growth = _g(fundamentals, "revenueGrowth")
    earn_growth = _g(fundamentals, "earningsGrowth")
    earn_q_growth = _g(fundamentals, "earningsQuarterlyGrowth")
    div_yield = _g(fundamentals, "dividendYield")
    payout_ratio = _g(fundamentals, "payoutRatio")
    market_cap = _g(fundamentals, "marketCap")

    current_price = _g(yf_info, "currentPrice") or _g(yf_info, "regularMarketPrice")
    total_revenue = _g(yf_info, "totalRevenue")
    net_income = _g(yf_info, "netIncomeToCommon")
    ebitda = _g(yf_info, "ebitda")
    float_shares = _g(yf_info, "floatShares")
    shares_outstanding = _g(yf_info, "sharesOutstanding")
    last_split_date = _g(yf_info, "lastSplitDate")
    last_split_factor = _g(yf_info, "lastSplitFactor")
    institution_pct = _g(yf_info, "heldPercentInstitutions")
    interest_expense = _g(yf_info, "interestExpense")
    company_name = _g(yf_info, "longName") or _g(yf_info, "shortName") or ticker
    sector = _g(yf_info, "sector") or "N/A"

    consensus_str = (analyst_ratings.get("consensus") or "").lower()
    num_analysts = analyst_ratings.get("numAnalysts") or analyst_ratings.get("numberOfAnalystOpinions")
    target_mean = analyst_ratings.get("targetMeanPrice")

    # Signal helpers
    def _pe_ttm_signal(v):
        if v is None:
            return "neutral", "N/A"
        v = float(v)
        if v < 15:
            return "bullish", "Undervalued"
        if v <= 25:
            return "neutral", "Fair"
        if v <= 35:
            return "neutral", "Premium"
        return "bearish", "Overvalued"

    def _pe_fwd_signal(v):
        if v is None:
            return "neutral", "N/A"
        v = float(v)
        if v < 14:
            return "bullish", "Undervalued"
        if v <= 22:
            return "neutral", "Fair"
        if v < 30:
            return "neutral", "Elevated"
        return "bearish", "Overvalued"

    def _peg_signal(v):
        if v is None:
            return "neutral", "N/A"
        v = float(v)
        if v < 1:
            return "bullish", "Undervalued"
        if v <= 1.5:
            return "neutral", "Fair"
        if v < 2.5:
            return "neutral", "Rich"
        return "bearish", "Risky"

    def _ps_signal(v):
        if v is None:
            return "neutral", "N/A"
        v = float(v)
        if v < 2:
            return "bullish", "Cheap"
        if v <= 5:
            return "neutral", "Fair"
        if v < 10:
            return "neutral", "Elevated"
        return "bearish", "Expensive"

    def _pb_signal(v):
        if v is None:
            return "neutral", "N/A"
        v = float(v)
        if v < 1:
            return "bullish", "Undervalued"
        if v <= 3:
            return "bullish", "Reasonable"
        if v <= 8:
            return "neutral", "Premium"
        return "bearish", "Very High"

    def _margin_signal(v):
        if v is None:
            return "neutral", "N/A"
        v = float(v)
        if v < 0:
            return "bearish", "Loss-making"
        if v < 0.05:
            return "neutral", "Thin"
        if v < 0.15:
            return "neutral", "Moderate"
        if v < 0.25:
            return "bullish", "Strong"
        return "bullish", "Exceptional"

    def _roe_signal(v):
        if v is None:
            return "neutral", "N/A"
        v = float(v)
        if v < 0:
            return "bearish", "Negative"
        if v < 0.10:
            return "neutral", "Low"
        if v <= 0.20:
            return "bullish", "Good"
        return "bullish", "Exceptional"

    def _roa_signal(v):
        if v is None:
            return "neutral", "N/A"
        v = float(v)
        if v < 0:
            return "bearish", "Negative"
        if v < 0.05:
            return "neutral", "Low"
        if v < 0.15:
            return "bullish", "Strong"
        return "bullish", "Exceptional"

    def _de_signal(v):
        if v is None:
            return "neutral", "N/A"
        # yfinance returns D/E as a ratio (e.g., 150 means 150%)
        v = float(v)
        # Normalize: yfinance D/E is often expressed as percentage points (divide by 100)
        de = v / 100 if v > 20 else v
        if de < 0.5:
            return "bullish", "Fortress"
        if de <= 1.5:
            return "neutral", "Healthy"
        if de <= 3:
            return "neutral", "Elevated"
        return "bearish", "High Risk"

    def _short_signal(v):
        if v is None:
            return "neutral", "N/A"
        v = float(v)
        if v < 0.05:
            return "bullish", "Low"
        if v <= 0.10:
            return "neutral", "Moderate"
        return "bearish", "High"

    def _beta_signal(v):
        if v is None:
            return "neutral", "N/A"
        v = float(v)
        if v < 0.8:
            return "neutral", "Low Volatility"
        if v <= 1.3:
            return "neutral", "Market Beta"
        if v < 2:
            return "neutral", "High Volatility"
        return "bearish", "Very Volatile"

    def _eps_growth_signal(v):
        if v is None:
            return "neutral", "N/A"
        v = float(v)
        if v < 0:
            return "bearish", "Declining"
        if v <= 0.10:
            return "neutral", "Slow Growth"
        return "bullish", "Strong Growth"

    def _div_yield_signal(v):
        if v is None or float(v) == 0:
            return "neutral", "None"
        v = float(v)
        if v < 0.02:
            return "neutral", "Symbolic"
        if v <= 0.04:
            return "bullish", "Income"
        return "bullish", "High Yield"

    def _consensus_signal(v: str):
        v = v.lower()
        if "strong buy" in v:
            return "bullish", "Strong Buy"
        if "buy" in v:
            return "bullish", "Buy"
        if "hold" in v or "neutral" in v:
            return "neutral", "Hold"
        if "sell" in v or "underperform" in v:
            return "bearish", "Sell"
        return "neutral", "N/A"

    # Build EPS YoY growth from earnings history
    eps_yoy_growth = None
    if len(earnings_history) >= 5:
        try:
            latest = earnings_history[0].get("epsActual")
            prior_yr = earnings_history[4].get("epsActual")
            if latest is not None and prior_yr is not None and prior_yr != 0:
                eps_yoy_growth = (float(latest) - float(prior_yr)) / abs(float(prior_yr))
        except Exception:
            pass

    # Beat rate from earnings history
    beat_count = sum(
        1 for e in earnings_history
        if e.get("epsActual") is not None and e.get("epsEstimate") is not None
        and float(e["epsActual"]) >= float(e["epsEstimate"])
    )
    beat_rate = beat_count / len(earnings_history) if earnings_history else None

    # Compute signals for all key metrics
    sig_pe_ttm, lbl_pe_ttm = _pe_ttm_signal(pe_ttm)
    sig_pe_fwd, lbl_pe_fwd = _pe_fwd_signal(pe_fwd)
    sig_peg, lbl_peg = _peg_signal(peg)
    sig_ps, lbl_ps = _ps_signal(ps)
    sig_pb, lbl_pb = _pb_signal(pb)
    sig_margin, lbl_margin = _margin_signal(profit_margin)
    sig_gross, lbl_gross = _margin_signal(gross_margin)
    sig_op_margin, lbl_op_margin = _margin_signal(op_margin)
    sig_roe, lbl_roe = _roe_signal(roe)
    sig_roa, lbl_roa = _roa_signal(roa)
    sig_de, lbl_de = _de_signal(de_ratio)
    sig_short, lbl_short = _short_signal(short_pct)
    sig_beta, lbl_beta = _beta_signal(beta)
    sig_earn_growth, lbl_earn_growth = _eps_growth_signal(earn_growth)
    sig_rev_growth, lbl_rev_growth = _eps_growth_signal(rev_growth)
    sig_eps_yoy, lbl_eps_yoy = _eps_growth_signal(eps_yoy_growth)
    sig_div, lbl_div = _div_yield_signal(div_yield)
    sig_consensus, lbl_consensus = _consensus_signal(consensus_str)

    # Collect all signals to determine overall verdict
    all_signals = [
        sig_pe_ttm, sig_pe_fwd, sig_peg, sig_ps, sig_pb,
        sig_margin, sig_roe, sig_roa, sig_de,
        sig_earn_growth, sig_rev_growth, sig_eps_yoy,
        sig_div, sig_consensus,
    ]
    bullish_count = all_signals.count("bullish")
    bearish_count = all_signals.count("bearish")

    if bullish_count > bearish_count:
        overall_verdict = "Buy"
        overall_signal = "bullish"
    elif bearish_count > bullish_count:
        if bearish_count >= 4:
            overall_verdict = "Avoid"
        else:
            overall_verdict = "Hold"
        overall_signal = "bearish"
    else:
        overall_verdict = "Hold"
        overall_signal = "neutral"

    # Find most bearish metric for key risk
    bearish_metrics = []
    if sig_de == "bearish":
        bearish_metrics.append(f"High debt-to-equity ratio ({_fmt_ratio(de_ratio / 100 if de_ratio and float(de_ratio) > 20 else de_ratio)})")
    if sig_margin == "bearish":
        bearish_metrics.append(f"Loss-making profit margin ({_fmt_pct(profit_margin, 100)})")
    if sig_pe_ttm == "bearish":
        bearish_metrics.append(f"Overvalued P/E TTM ({_fmt_ratio(pe_ttm)})")
    if sig_short == "bearish":
        bearish_metrics.append(f"High short interest ({_fmt_pct(short_pct, 100)})")
    if sig_roe == "bearish":
        bearish_metrics.append(f"Negative return on equity ({_fmt_pct(roe, 100)})")
    if sig_earn_growth == "bearish":
        bearish_metrics.append(f"Declining earnings growth ({_fmt_pct(earn_growth, 100)})")
    key_risk = bearish_metrics[0] if bearish_metrics else "Monitor valuation and macro conditions."

    price_str = _fmt_price(current_price)
    intro = f"{ticker} — {company_name} | {sector} | Price {price_str} | Overall: {overall_verdict}"

    # Build summary
    val_desc = f"trading at P/E of {_fmt_ratio(pe_ttm)}" if pe_ttm else "valuation data limited"
    margin_desc = f"profit margin of {_fmt_pct(profit_margin, 100)}" if profit_margin else "margin data limited"
    roe_desc = f"ROE of {_fmt_pct(roe, 100)}" if roe else "ROE data limited"
    growth_desc = f"earnings growth of {_fmt_pct(earn_growth, 100)}" if earn_growth else "growth data limited"
    consensus_desc = lbl_consensus if lbl_consensus != "N/A" else "no analyst consensus"
    summary = (
        f"{company_name} ({ticker}) is {val_desc} with a {margin_desc}. "
        f"The company shows {roe_desc} and {growth_desc} year-over-year. "
        f"Analyst consensus is {consensus_desc} with a mean price target of {_fmt_price(target_mean)}. "
        f"Overall assessment: {overall_verdict} based on {bullish_count} bullish and {bearish_count} bearish signals across key metrics."
    )

    # D/E display value — normalize for display
    de_display = None
    if de_ratio is not None:
        de_val = float(de_ratio)
        de_display = de_val / 100 if de_val > 20 else de_val

    valuation_rows = [
        {
            "metric": "P/E (TTM)",
            "value": _fmt_ratio(pe_ttm),
            "benchmark": "15–25x = fair",
            "signal": sig_pe_ttm,
            "signalLabel": lbl_pe_ttm,
            "interpretation": "Trailing price-to-earnings ratio",
        },
        {
            "metric": "P/E (Forward)",
            "value": _fmt_ratio(pe_fwd),
            "benchmark": "14–22x = fair",
            "signal": sig_pe_fwd,
            "signalLabel": lbl_pe_fwd,
            "interpretation": "Forward price-to-earnings ratio",
        },
        {
            "metric": "PEG Ratio",
            "value": _fmt_ratio(peg),
            "benchmark": "<1 = undervalued",
            "signal": sig_peg,
            "signalLabel": lbl_peg,
            "interpretation": "P/E relative to growth rate",
        },
        {
            "metric": "Price/Sales",
            "value": _fmt_ratio(ps),
            "benchmark": "<2 = cheap",
            "signal": sig_ps,
            "signalLabel": lbl_ps,
            "interpretation": "Market cap vs annual revenue",
        },
        {
            "metric": "Price/Book",
            "value": _fmt_ratio(pb),
            "benchmark": "<3 = reasonable",
            "signal": sig_pb,
            "signalLabel": lbl_pb,
            "interpretation": "Market cap vs book value",
        },
        {
            "metric": "EV/EBITDA",
            "value": _fmt_ratio(ev_ebitda),
            "benchmark": "<12x = fair",
            "signal": "neutral",
            "signalLabel": "N/A",
            "interpretation": "Enterprise value vs EBITDA",
        },
        {
            "metric": "EV/Revenue",
            "value": _fmt_ratio(ev_revenue),
            "benchmark": "<3x = fair",
            "signal": "neutral",
            "signalLabel": "N/A",
            "interpretation": "Enterprise value vs revenue",
        },
    ]

    profitability_rows = [
        {
            "metric": "Profit Margin",
            "value": _fmt_pct(profit_margin, 100),
            "benchmark": ">15% = strong",
            "signal": sig_margin,
            "signalLabel": lbl_margin,
            "interpretation": "Net income as % of revenue",
        },
        {
            "metric": "Gross Margin",
            "value": _fmt_pct(gross_margin, 100),
            "benchmark": ">40% = strong",
            "signal": sig_gross,
            "signalLabel": lbl_gross,
            "interpretation": "Gross profit as % of revenue",
        },
        {
            "metric": "Operating Margin",
            "value": _fmt_pct(op_margin, 100),
            "benchmark": ">15% = healthy",
            "signal": sig_op_margin,
            "signalLabel": lbl_op_margin,
            "interpretation": "Operating income as % of revenue",
        },
        {
            "metric": "ROE",
            "value": _fmt_pct(roe, 100),
            "benchmark": ">15% = good",
            "signal": sig_roe,
            "signalLabel": lbl_roe,
            "interpretation": "Return on shareholder equity",
        },
        {
            "metric": "ROA",
            "value": _fmt_pct(roa, 100),
            "benchmark": ">5% = strong",
            "signal": sig_roa,
            "signalLabel": lbl_roa,
            "interpretation": "Return on total assets",
        },
    ]

    financial_health_rows = [
        {
            "metric": "Debt/Equity",
            "value": _fmt_ratio(de_display),
            "benchmark": "<1.5 = healthy",
            "signal": sig_de,
            "signalLabel": lbl_de,
            "interpretation": "Total debt relative to equity",
        },
        {
            "metric": "Current Ratio",
            "value": _fmt_ratio(current_ratio),
            "benchmark": ">1.5 = healthy",
            "signal": "bullish" if current_ratio and float(current_ratio) >= 1.5 else ("neutral" if current_ratio and float(current_ratio) >= 1.0 else "bearish"),
            "signalLabel": "Healthy" if current_ratio and float(current_ratio) >= 1.5 else ("Adequate" if current_ratio and float(current_ratio) >= 1.0 else "Stressed"),
            "interpretation": "Short-term assets vs liabilities",
        },
        {
            "metric": "Quick Ratio",
            "value": _fmt_ratio(quick_ratio),
            "benchmark": ">1.0 = healthy",
            "signal": "bullish" if quick_ratio and float(quick_ratio) >= 1.0 else "bearish",
            "signalLabel": "Healthy" if quick_ratio and float(quick_ratio) >= 1.0 else "Stressed",
            "interpretation": "Liquid assets vs current liabilities",
        },
        {
            "metric": "Free Cash Flow",
            "value": _fmt_large(free_cashflow),
            "benchmark": "Positive = healthy",
            "signal": "bullish" if free_cashflow and float(free_cashflow) > 0 else "bearish",
            "signalLabel": "Positive" if free_cashflow and float(free_cashflow) > 0 else "Negative",
            "interpretation": "Cash after capex — funds growth",
        },
        {
            "metric": "Short Interest",
            "value": _fmt_pct(short_pct, 100),
            "benchmark": "<5% = low",
            "signal": sig_short,
            "signalLabel": lbl_short,
            "interpretation": "Shares sold short as % of float",
        },
        {
            "metric": "Beta",
            "value": f"{float(beta):.2f}" if beta is not None else "N/A",
            "benchmark": "0.8–1.3 = market",
            "signal": sig_beta,
            "signalLabel": lbl_beta,
            "interpretation": "Volatility vs market benchmark",
        },
    ]

    growth_rows = [
        {
            "metric": "Revenue Growth (YoY)",
            "value": _fmt_pct(rev_growth, 100),
            "benchmark": ">10% = strong",
            "signal": sig_rev_growth,
            "signalLabel": lbl_rev_growth,
            "interpretation": "Year-over-year revenue growth",
        },
        {
            "metric": "Earnings Growth (YoY)",
            "value": _fmt_pct(earn_growth, 100),
            "benchmark": ">10% = strong",
            "signal": sig_earn_growth,
            "signalLabel": lbl_earn_growth,
            "interpretation": "Year-over-year earnings growth",
        },
        {
            "metric": "EPS Growth (YoY)",
            "value": _fmt_pct(eps_yoy_growth, 100),
            "benchmark": ">10% = strong",
            "signal": sig_eps_yoy,
            "signalLabel": lbl_eps_yoy,
            "interpretation": "EPS growth vs prior year quarter",
        },
        {
            "metric": "EPS Quarterly Growth",
            "value": _fmt_pct(earn_q_growth, 100),
            "benchmark": ">5% = healthy",
            "signal": _eps_growth_signal(earn_q_growth)[0],
            "signalLabel": _eps_growth_signal(earn_q_growth)[1],
            "interpretation": "Sequential quarterly EPS growth",
        },
        {
            "metric": "EPS Beat Rate",
            "value": _fmt_pct(beat_rate) if beat_rate is not None else "N/A",
            "benchmark": ">75% = consistent",
            "signal": "bullish" if beat_rate and beat_rate >= 0.75 else ("neutral" if beat_rate and beat_rate >= 0.50 else "bearish"),
            "signalLabel": "Consistent" if beat_rate and beat_rate >= 0.75 else ("Mixed" if beat_rate and beat_rate >= 0.50 else "Misses"),
            "interpretation": "% of quarters EPS beat estimate",
        },
        {
            "metric": "5-yr Stock Return",
            "value": "N/A",
            "benchmark": ">S&P 500 = outperform",
            "signal": "neutral",
            "signalLabel": "N/A",
            "interpretation": "5-year price appreciation",
        },
        {
            "metric": "Institutional Ownership",
            "value": _fmt_pct(institution_pct, 100),
            "benchmark": ">50% = high confidence",
            "signal": "bullish" if institution_pct and float(institution_pct) >= 0.50 else "neutral",
            "signalLabel": "High" if institution_pct and float(institution_pct) >= 0.50 else "Moderate",
            "interpretation": "% held by institutions",
        },
    ]

    # Earnings rows from history
    earnings_rows = []
    for e in earnings_history[:4]:
        est = e.get("epsEstimate")
        act = e.get("epsActual")
        surprise = e.get("surprisePercent")
        beat = act is not None and est is not None and float(act) >= float(est)
        earnings_rows.append({
            "metric": f"EPS {e.get('date', 'N/A')}",
            "value": _fmt_price(act) if act is not None else "N/A",
            "benchmark": f"Est: {_fmt_price(est)}" if est is not None else "N/A",
            "signal": "bullish" if beat else "bearish",
            "signalLabel": "Beat" if beat else "Miss",
            "interpretation": f"Surprise: {_fmt_pct(surprise / 100) if surprise is not None else 'N/A'}",
        })
    # Pad to 7 rows if needed
    while len(earnings_rows) < 4:
        earnings_rows.append({
            "metric": "EPS N/A",
            "value": None,
            "benchmark": None,
            "signal": "neutral",
            "signalLabel": "N/A",
            "interpretation": "No earnings data available",
        })
    earnings_rows.extend([
        {
            "metric": "EPS (TTM)",
            "value": _fmt_price(eps_ttm),
            "benchmark": "Positive = profitable",
            "signal": "bullish" if eps_ttm and float(eps_ttm) > 0 else "bearish",
            "signalLabel": "Profitable" if eps_ttm and float(eps_ttm) > 0 else "Loss",
            "interpretation": "Trailing 12-month earnings per share",
        },
        {
            "metric": "EPS (Forward)",
            "value": _fmt_price(eps_fwd),
            "benchmark": "Positive = expected profit",
            "signal": "bullish" if eps_fwd and float(eps_fwd) > 0 else "bearish",
            "signalLabel": "Profitable" if eps_fwd and float(eps_fwd) > 0 else "Loss",
            "interpretation": "Expected next-year earnings per share",
        },
        {
            "metric": "Analyst Target",
            "value": _fmt_price(target_mean),
            "benchmark": f"vs current {price_str}",
            "signal": "bullish" if target_mean and current_price and float(target_mean) > float(current_price) * 1.05 else ("bearish" if target_mean and current_price and float(target_mean) < float(current_price) * 0.95 else "neutral"),
            "signalLabel": "Upside" if target_mean and current_price and float(target_mean) > float(current_price) * 1.05 else ("Downside" if target_mean and current_price and float(target_mean) < float(current_price) * 0.95 else "At Market"),
            "interpretation": "Mean analyst 12-month price target",
        },
    ])
    earnings_rows = earnings_rows[:7]

    five_yr_avg_div = dividends.get("fiveYearAvgDividendYield")
    div_rate = dividends.get("dividendRate")
    dividend_rows = [
        {
            "metric": "Dividend Yield",
            "value": _fmt_pct(div_yield, 100),
            "benchmark": "2–4% = income",
            "signal": sig_div,
            "signalLabel": lbl_div,
            "interpretation": "Annual dividend as % of price",
        },
        {
            "metric": "Payout Ratio",
            "value": _fmt_pct(payout_ratio, 100),
            "benchmark": "<60% = sustainable",
            "signal": "bullish" if payout_ratio and float(payout_ratio) < 0.60 else ("neutral" if payout_ratio and float(payout_ratio) < 0.80 else "bearish"),
            "signalLabel": "Sustainable" if payout_ratio and float(payout_ratio) < 0.60 else ("Elevated" if payout_ratio and float(payout_ratio) < 0.80 else "At Risk"),
            "interpretation": "% of earnings paid as dividends",
        },
        {
            "metric": "Annual Dividend Rate",
            "value": _fmt_price(div_rate),
            "benchmark": "Consistent = quality",
            "signal": "bullish" if div_rate and float(div_rate) > 0 else "neutral",
            "signalLabel": "Paying" if div_rate and float(div_rate) > 0 else "None",
            "interpretation": "Annual dividend per share",
        },
        {
            "metric": "5-yr Avg Div Yield",
            "value": _fmt_pct(five_yr_avg_div, 1) if five_yr_avg_div else "N/A",
            "benchmark": "Stable = reliable income",
            "signal": "bullish" if five_yr_avg_div and float(five_yr_avg_div) >= 2 else "neutral",
            "signalLabel": "Stable" if five_yr_avg_div else "N/A",
            "interpretation": "Historical average dividend yield",
        },
    ]

    verdict_rows = [
        {
            "investorType": "Long-term investor (3–5 yr)",
            "verdict": overall_verdict,
            "reasoning": f"ROE {_fmt_pct(roe, 100)}, earnings growth {_fmt_pct(earn_growth, 100)}, profit margin {_fmt_pct(profit_margin, 100)}. {'Strong fundamentals support long-term holding.' if bullish_count > bearish_count else 'Monitor fundamentals before committing long-term.'}",
        },
        {
            "investorType": "Current holder",
            "verdict": "Hold" if overall_verdict in ("Hold", "Buy") else "Consider reducing",
            "reasoning": f"Overall signal is {overall_signal} with {bullish_count} bullish and {bearish_count} bearish indicators. {'Maintain position and monitor earnings.' if overall_signal != 'bearish' else 'Review position given bearish signals.'}",
        },
        {
            "investorType": "Short-term trader",
            "verdict": "Neutral" if sig_pe_ttm == "neutral" else ("Caution" if sig_pe_ttm == "bearish" else "Watch"),
            "reasoning": f"P/E TTM {_fmt_ratio(pe_ttm)} ({lbl_pe_ttm}), beta {f'{float(beta):.2f}' if beta else 'N/A'} ({lbl_beta}). {'Valuation premium limits short-term upside.' if sig_pe_ttm == 'bearish' else 'Monitor momentum and volume for entry.'}",
        },
        {
            "investorType": "Income / conservative",
            "verdict": "Buy" if sig_div == "bullish" else ("Hold" if sig_div == "neutral" else "Skip"),
            "reasoning": f"Dividend yield {_fmt_pct(div_yield, 100)} ({lbl_div}), payout ratio {_fmt_pct(payout_ratio, 100)}. {'Good income characteristics.' if sig_div == 'bullish' else 'Limited income appeal — seek alternatives.' if sig_div == 'neutral' else 'Unsustainable dividend or no yield.'}",
        },
    ]

    return {
        "ticker": ticker,
        "asOf": datetime.date.today().isoformat(),
        "header": {
            "price": price_str,
            "marketCap": _fmt_large(market_cap),
            "revenue": _fmt_large(total_revenue),
            "netIncome": _fmt_large(net_income),
        },
        "valuation": valuation_rows,
        "profitability": profitability_rows,
        "financialHealth": financial_health_rows,
        "growth": growth_rows,
        "earnings": earnings_rows,
        "dividends": dividend_rows,
        "verdict": verdict_rows,
        "keyRisk": key_risk,
        "intro": intro,
        "summary": summary,
        "sources": ["Yahoo Finance"],
    }


def _normalize_fundamental_only(raw: dict, ticker: str) -> dict:
    """Normalize a fundamental-only payload into frontend FundamentalAnalysis schema."""
    # If agent returned rich fundamental schema, coerce arrays and return
    if _is_rich_fundamental(raw):
        return _coerce_metric_arrays(raw)

    # Accept either the fundamental object itself or a wrapped stock-analysis object.
    fundamental_payload = raw.get("fundamental") if isinstance(raw.get("fundamental"), dict) else raw
    wrapped = {
        "ticker": ticker,
        "overallSignal": "neutral",
        "overallRecommendation": "Hold",
        "confidence": "medium",
        "shortTerm": "neutral",
        "mediumTerm": "neutral",
        "longTerm": "neutral",
        "technical": {},
        "fundamental": fundamental_payload,
        "news": {},
        "executiveSummary": "",
    }
    normalized = _normalize_analysis(wrapped)["fundamental"]
    return _ensure_enhanced_fundamental_shape(normalized)


def _ensure_enhanced_fundamental_shape(fund: dict) -> dict:
    """Backfill enhanced attributes/aiAnalysis when upstream model returns legacy shape."""
    if isinstance(fund.get("attributes"), dict) and isinstance(fund.get("aiAnalysis"), dict):
        return fund

    def _num(v):
        if isinstance(v, (int, float)):
            return float(v)
        try:
            s = str(v).strip().replace("%", "").replace(",", "")
            if not s or s.lower() == "n/a":
                return None
            return float(s)
        except Exception:
            return None

    def _signal_from_text(v: str | None) -> str:
        s = (v or "").lower()
        if "buy" in s or "bull" in s or "under" in s or "strong" in s:
            return "bullish"
        if "sell" in s or "bear" in s or "over" in s or "weak" in s:
            return "bearish"
        return "neutral"

    def _score_from_signal(signal: str) -> int:
        return 8 if signal == "bullish" else 3 if signal == "bearish" else 5

    valuation = fund.get("valuation", {}) if isinstance(fund.get("valuation"), dict) else {}
    health = fund.get("financialHealth", {}) if isinstance(fund.get("financialHealth"), dict) else {}
    growth = fund.get("growth", {}) if isinstance(fund.get("growth"), dict) else {}
    analyst = fund.get("analystConsensus", {}) if isinstance(fund.get("analystConsensus"), dict) else {}

    val_sig = _signal_from_text(valuation.get("signal"))
    growth_sig = _signal_from_text(growth.get("signal"))
    health_sig = _signal_from_text(health.get("signal"))
    analyst_sig = _signal_from_text(analyst.get("rating"))
    rec_sig = _signal_from_text(fund.get("recommendation"))

    attributes = {
        "valuation": {
            "signal": val_sig,
            "score": _score_from_signal(val_sig),
            "metrics": {
                "pe": _num(valuation.get("peRatio")),
                "forwardPe": _num(valuation.get("forwardPE")),
                "peg": _num(valuation.get("pegRatio")),
                "priceToBook": _num(valuation.get("priceToBook")),
            },
            "explanation": "Derived from valuation multiples available in the current analysis payload.",
        },
        "growth": {
            "signal": growth_sig,
            "score": _score_from_signal(growth_sig),
            "metrics": {
                "revenueGrowthYoYPercent": _num(growth.get("revenueGrowth")),
                "epsGrowthYoYPercent": _num(growth.get("earningsGrowth")),
                "epsTtm": _num(growth.get("epsTTM")),
            },
            "explanation": "Based on reported revenue and earnings growth values.",
        },
        "profitability": {
            "signal": health_sig,
            "score": _score_from_signal(health_sig),
            "metrics": {
                "operatingMarginPercent": _num(health.get("operatingMargin")),
                "roePercent": _num(health.get("returnOnEquity")),
            },
            "explanation": "Estimated from operating margin and ROE where available.",
        },
        "financialStrength": {
            "signal": health_sig,
            "score": _score_from_signal(health_sig),
            "metrics": {
                "debtToEquity": _num(health.get("debtToEquity")),
                "currentRatio": _num(health.get("currentRatio")),
            },
            "explanation": "Balance-sheet strength inferred from leverage and liquidity metrics.",
        },
        "cashFlowQuality": {
            "signal": "neutral",
            "score": 5,
            "metrics": {},
            "explanation": "Insufficient explicit cash-flow detail in upstream payload; marked neutral.",
        },
        "earningsQuality": {
            "signal": "neutral",
            "score": 5,
            "metrics": {},
            "explanation": "Limited quarter-level earnings surprise detail available in upstream payload.",
        },
        "capitalAllocation": {
            "signal": "neutral",
            "score": 5,
            "metrics": {},
            "explanation": "Dividend/buyback/share-count trend data not present in upstream payload.",
        },
        "analystSentiment": {
            "signal": analyst_sig,
            "score": _score_from_signal(analyst_sig),
            "metrics": {
                "consensus": analyst.get("rating"),
                "targetMean": _num(analyst.get("targetPrice")),
                "numAnalysts": int(_num(analyst.get("numAnalysts")) or 0),
            },
            "explanation": "Built from analyst consensus rating and target price.",
        },
        "businessQualityMoat": {
            "signal": "neutral",
            "score": 5,
            "metrics": {},
            "explanation": "Moat/segment breakdown was not provided in upstream response.",
        },
        "risksRedFlags": {
            "signal": "neutral",
            "score": 5,
            "items": [],
            "explanation": "No explicit risks list in upstream fundamental payload.",
        },
    }

    overall_score = float(
        round(
            sum(
                float(v.get("score", 5))
                for v in attributes.values()
                if isinstance(v, dict)
            )
            / 10.0
            * 10.0,
            1,
        )
    )

    recommendation = fund.get("recommendation") or ("Buy" if overall_score >= 65 else "Hold")
    fund["attributes"] = attributes
    fund["aiAnalysis"] = {
        "overallScore": overall_score,
        "recommendation": recommendation,
        "confidence": "medium",
        "horizonView": {
            "shortTerm": rec_sig,
            "mediumTerm": rec_sig,
            "longTerm": rec_sig,
        },
        "bullCase": [],
        "bearCase": [],
        "keyDrivers": [],
        "finalExplanation": fund.get("summary") or "AI recommendation synthesized from available valuation, growth, health, and analyst fields.",
    }
    fund["sources"] = fund.get("sources") or []
    return fund

VALID_RANGES = {"1D", "1W", "1M", "3M", "1Y", "5Y"}

_analysis_cache: dict[str, tuple[float, dict]] = {}
_fundamental_cache: dict[str, tuple[float, dict]] = {}
_news_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 600  # 10 minutes
_NEWS_CACHE_TTL = 300  # 5 minutes


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


@router.get("/{ticker}/fundamentals")
def fundamentals(ticker: str):
    try:
        return fund_svc.get_fundamentals(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/financial-statements")
def financial_statements(ticker: str):
    """Full income statement, balance sheet, and cash flow (annual + quarterly) from Yahoo Finance."""
    try:
        return fund_svc.get_financial_statements(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/insider-transactions")
def insider_transactions(ticker: str):
    """Recent insider buy/sell transactions (Form 4) from Yahoo Finance."""
    try:
        return fund_svc.get_insider_transactions(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/institutional-holders")
def institutional_holders(ticker: str):
    """Top institutional and mutual fund holders with % held (13F) from Yahoo Finance."""
    try:
        return fund_svc.get_institutional_holders(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/analyst-ratings")
def analyst_ratings(ticker: str):
    """Analyst consensus, price targets, upgrades/downgrades from Yahoo Finance."""
    try:
        return fund_svc.get_analyst_ratings(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/dividends")
def dividends(ticker: str):
    """Dividend history, yield, payout ratio from Yahoo Finance."""
    try:
        return fund_svc.get_dividends(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/volume-analysis")
def volume_analysis(ticker: str):
    try:
        return fund_svc.get_volume_analysis(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/technical-signals")
def technical_signals(ticker: str):
    """
    Compute all Tier 1 technical indicators (per TradeElite spec Part 6).
    Returns composite score, per-indicator values, and Buy/Sell/Neutral signals.
    """
    try:
        return ts_svc.compute_technical_signals(ticker.upper())
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/ai-analysis")
async def ai_analysis(ticker: str):
    ticker = ticker.upper()
    now = time.time()
    if ticker in _analysis_cache:
        ts, data = _analysis_cache[ticker]
        if now - ts < _CACHE_TTL:
            return data

    if not settings.tradeview_agent_resource_id:
        raise HTTPException(503, "Agent not configured — set TRADEVIEW_AGENT_RESOURCE_ID")

    try:
        import json
        import re
        import vertexai
        from vertexai import agent_engines

        vertexai.init(
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
        )

        remote_agent = agent_engines.get(settings.tradeview_agent_resource_id)
        user_id = f"ai-analysis-{ticker}"
        session = remote_agent.create_session(user_id=user_id)
        session_id = session["id"]

        message = (
            f"Perform a complete stock analysis for {ticker}. "
            "Delegate to stock_analyst sub-agent."
        )

        # Drain the stream to let all agents complete
        response_text = ""
        event_reprs: list[str] = []
        for event in remote_agent.stream_query(
            user_id=user_id,
            session_id=session_id,
            message=message,
        ):
            event_reprs.append(repr(event)[:200])
            # Collect text from various event formats
            if hasattr(event, "text") and event.text:
                response_text += event.text
            elif isinstance(event, dict):
                content = event.get("content", {})
                if isinstance(content, dict):
                    for part in content.get("parts", []):
                        if isinstance(part, dict) and part.get("text"):
                            response_text += part["text"]
            elif hasattr(event, "content") and event.content:
                for part in getattr(event.content, "parts", []):
                    if hasattr(part, "text") and part.text:
                        response_text += part.text

        # Read structured output from session state (set by stock_analyst output_key)
        result = None
        state_keys: list[str] = []
        try:
            session_data = remote_agent.get_session(user_id=user_id, session_id=session_id)
            if isinstance(session_data, dict):
                state = session_data.get("state", {}) or {}
            else:
                state = getattr(session_data, "state", None) or {}
            state_keys = list(state.keys()) if isinstance(state, dict) else []
            # Scan all state values for one that looks like our analysis JSON
            for key in state_keys:
                raw = state[key]
                if not raw:
                    continue
                try:
                    if isinstance(raw, dict):
                        candidate = raw
                    else:
                        # Strip markdown code fences before parsing
                        cleaned = re.sub(r"^```(?:json)?\s*", "", str(raw).strip())
                        cleaned = re.sub(r"\s*```$", "", cleaned.strip())
                        json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
                        candidate = json.loads(json_match.group()) if json_match else None
                    if isinstance(candidate, dict) and "ticker" in candidate:
                        result = candidate
                        break
                except Exception:
                    pass
        except Exception as sess_err:
            state_keys = [f"session_err:{sess_err}"]

        # Fall back to extracting JSON from the text response
        if result is None and response_text.strip():
            try:
                cleaned = re.sub(r"^```(?:json)?\s*", "", response_text.strip())
                cleaned = re.sub(r"\s*```$", "", cleaned.strip())
                json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
            except Exception:
                pass

        remote_agent.delete_session(user_id=user_id, session_id=session_id)

        if result:
            result = _normalize_analysis(result)

        if result is None:
            raise ValueError(
                f"No analysis output. State keys={state_keys}, "
                f"response_len={len(response_text)}, "
                f"response_sample={response_text[:300]!r}, "
                f"events={event_reprs[:3]}"
            )

        _analysis_cache[ticker] = (now, result)
        return result

    except Exception as e:
        raise HTTPException(500, f"AI analysis failed: {e}")


@router.get("/{ticker}/fundamental-analysis")
async def fundamental_analysis(ticker: str):
    ticker = ticker.upper()
    now = time.time()
    if ticker in _fundamental_cache:
        ts, data = _fundamental_cache[ticker]
        if now - ts < _CACHE_TTL:
            return data

    try:
        result = await _build_rich_fundamental(ticker)
        _fundamental_cache[ticker] = (now, result)
        return result
    except Exception:
        pass  # fall through to agent path

    if not settings.tradeview_agent_resource_id:
        raise HTTPException(503, "Agent not configured — set TRADEVIEW_AGENT_RESOURCE_ID")

    try:
        import json
        import re
        import vertexai
        from vertexai import agent_engines

        vertexai.init(
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
        )

        remote_agent = agent_engines.get(settings.tradeview_agent_resource_id)
        user_id = f"fundamental-analysis-{ticker}"
        session = remote_agent.create_session(user_id=user_id)
        session_id = session["id"]

        message = f"Perform a complete fundamental analysis for {ticker}."

        response_text = ""
        event_reprs: list[str] = []
        result = None
        state_keys: list[str] = []

        try:
            for event in remote_agent.stream_query(
                user_id=user_id,
                session_id=session_id,
                message=message,
            ):
                event_reprs.append(repr(event)[:200])
                if hasattr(event, "text") and event.text:
                    response_text += event.text
                elif isinstance(event, dict):
                    content = event.get("content", {})
                    if isinstance(content, dict):
                        for part in content.get("parts", []):
                            if isinstance(part, dict) and part.get("text"):
                                response_text += part["text"]
                elif hasattr(event, "content") and event.content:
                    for part in getattr(event.content, "parts", []):
                        if hasattr(part, "text") and part.text:
                            response_text += part.text

            session_data = remote_agent.get_session(user_id=user_id, session_id=session_id)
            if isinstance(session_data, dict):
                state = session_data.get("state", {}) or {}
            else:
                state = getattr(session_data, "state", None) or {}
            state_keys = list(state.keys()) if isinstance(state, dict) else []

            def _parse_state_value(raw_state):
                """Parse a session state value into a dict, or return None."""
                if not raw_state:
                    return None
                try:
                    if isinstance(raw_state, dict):
                        return raw_state
                    cleaned = re.sub(r"^```(?:json)?\s*", "", str(raw_state).strip())
                    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
                    json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
                    return json.loads(json_match.group()) if json_match else None
                except Exception:
                    return None

            def _has_fundamental_shape(candidate: dict) -> bool:
                return (
                    isinstance(candidate.get("header"), dict)  # rich fundamental schema
                    or isinstance(candidate.get("attributes"), dict)
                    or isinstance(candidate.get("aiAnalysis"), dict)
                    or isinstance(candidate.get("fundamental"), dict)
                    or ("ticker" in candidate and ("valuation" in candidate or "summary" in candidate))
                )

            # Priority 1: direct fundamental_analysis_output (fundamental_analyst wrote it)
            if "fundamental_analysis_output" in state:
                candidate = _parse_state_value(state["fundamental_analysis_output"])
                if isinstance(candidate, dict) and _has_fundamental_shape(candidate):
                    result = candidate

            # Priority 2: extract fundamental from stock_analysis_output (stock_analyst path)
            if result is None and "stock_analysis_output" in state:
                candidate = _parse_state_value(state["stock_analysis_output"])
                if isinstance(candidate, dict):
                    # prefer the nested fundamental sub-object if present
                    nested = candidate.get("fundamental")
                    if isinstance(nested, dict) and _has_fundamental_shape(nested):
                        result = nested
                    elif _has_fundamental_shape(candidate):
                        result = candidate

            # Priority 3: scan remaining state keys for fundamental shape
            if result is None:
                for key in state_keys:
                    if key in ("fundamental_analysis_output", "stock_analysis_output"):
                        continue  # already tried
                    candidate = _parse_state_value(state[key])
                    if isinstance(candidate, dict) and _has_fundamental_shape(candidate):
                        result = candidate
                        break

            # Priority 3: extract from streamed response text
            if result is None and response_text.strip():
                try:
                    cleaned = re.sub(r"^```(?:json)?\s*", "", response_text.strip())
                    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
                    json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
                    if json_match:
                        result = json.loads(json_match.group())
                except Exception:
                    pass
        finally:
            try:
                remote_agent.delete_session(user_id=user_id, session_id=session_id)
            except Exception:
                pass

        if result is None:
            raise ValueError(
                f"No fundamental output. State keys={state_keys}, "
                f"response_len={len(response_text)}, "
                f"response_sample={response_text[:300]!r}, "
                f"events={event_reprs[:3]}"
            )

        normalized = _normalize_fundamental_only(result, ticker)
        _fundamental_cache[ticker] = (now, normalized)
        return normalized

    except Exception as e:
        raise HTTPException(500, f"Fundamental analysis failed: {e}")


@router.get("/{ticker}/financials")
async def financials(ticker: str, period: str = Query("annual")):
    """Income statement, balance sheet, and cash flow from FMP (annual + quarterly)."""
    try:
        return await fmp_svc.get_financials(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/key-metrics")
async def key_metrics(ticker: str, period: str = Query("annual")):
    """Key financial metrics and ratios from FMP: FCF yield, EV/EBITDA, ROIC, margins."""
    try:
        km, ratios = await asyncio.gather(
            fmp_svc.get_key_metrics(ticker.upper(), period),
            fmp_svc.get_financial_ratios(ticker.upper(), period),
        )
        return {"ticker": ticker.upper(), "keyMetrics": km, "ratios": ratios}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/earnings-history")
async def earnings_history(ticker: str):
    """Earnings surprise history from FMP: last 8 quarters, EPS estimate vs actual."""
    try:
        return await fmp_svc.get_earnings_surprises(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/dividends")
async def dividends(ticker: str):
    """Dividend payment history from FMP: amount, ex-date, payment date."""
    try:
        return await fmp_svc.get_dividends(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/dcf")
async def dcf_valuation(ticker: str):
    """DCF fair value estimate from FMP: intrinsic value vs current price."""
    try:
        return await fmp_svc.get_dcf(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/insider-transactions")
async def insider_transactions(ticker: str):
    """Insider buy/sell transactions from Finnhub (SEC Form 4 filings)."""
    try:
        return await finnhub_svc.get_insider_transactions(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


async def _build_news_analysis(ticker: str) -> dict:
    """Build rich NewsAnalysis from Yahoo Finance, Finnhub, StockTwits, and Gemini synthesis."""
    import json
    from datetime import datetime, timezone

    # Fetch in parallel; handle individual failures gracefully
    results = await asyncio.gather(
        asyncio.to_thread(yf_svc.get_news, ticker, 20),
        finnhub_svc.get_news_with_sentiment(ticker, days=14),
        stocktwits.get_sentiment(ticker),
        return_exceptions=True,
    )
    yf_news = results[0] if not isinstance(results[0], Exception) else []
    finnhub_data = results[1] if not isinstance(results[1], Exception) else {"articles": [], "sentiment": {}}
    twits_data = results[2] if not isinstance(results[2], Exception) else {}

    # Merge headlines; yf first (has thumbnails), then finnhub (has summaries)
    seen: set[str] = set()
    articles: list[dict] = []
    for item in (yf_news if isinstance(yf_news, list) else []):
        title = item.get("title", "").strip()
        if title and title.lower() not in seen:
            seen.add(title.lower())
            articles.append({
                "title": title,
                "source": item.get("publisher", ""),
                "url": item.get("url", ""),
                "publishedAt": str(item.get("publishedAt", "")),
                "summary": "",
                "thumbnail": item.get("thumbnail"),
            })
    for art in (finnhub_data.get("articles", []) if isinstance(finnhub_data, dict) else []):
        title = art.get("headline", "").strip()
        if title and title.lower() not in seen:
            seen.add(title.lower())
            pub = art.get("publishedAt", "")
            if isinstance(pub, (int, float)):
                pub = datetime.fromtimestamp(pub, tz=timezone.utc).isoformat()
            articles.append({
                "title": title,
                "source": art.get("source", ""),
                "url": art.get("url", ""),
                "publishedAt": str(pub),
                "summary": art.get("summary", ""),
                "thumbnail": art.get("image") or None,
            })

    # Compute sentiment signals from Finnhub scores
    sentiment_meta = (finnhub_data.get("sentiment", {}) if isinstance(finnhub_data, dict) else {}) or {}
    company_news_score = sentiment_meta.get("companyNewsScore")
    finnhub_bullish_pct = None
    raw_sent = sentiment_meta.get("sentiment", {}) or {}
    if raw_sent.get("bullishPercent") is not None:
        finnhub_bullish_pct = round(raw_sent["bullishPercent"] * 100, 1)

    if company_news_score is not None:
        news_sentiment = "positive" if company_news_score > 0.6 else ("negative" if company_news_score < 0.4 else "mixed")
    else:
        news_sentiment = "mixed"

    # StockTwits
    bullish_pct = twits_data.get("bullishPercent") if isinstance(twits_data, dict) else None
    watchlist_count = twits_data.get("watchlistCount") if isinstance(twits_data, dict) else None
    if bullish_pct is None and finnhub_bullish_pct is not None:
        bullish_pct = finnhub_bullish_pct
    social_signal = "bullish" if (bullish_pct or 0) > 60 else ("bearish" if (bullish_pct or 50) < 40 else "neutral")

    score = (1 if news_sentiment == "positive" else -1 if news_sentiment == "negative" else 0) + \
            (1 if social_signal == "bullish" else -1 if social_signal == "bearish" else 0)
    overall = "bullish" if score > 0 else ("bearish" if score < 0 else "neutral")

    # Gemini synthesis: catalysts, risks, keyEvents, recommendation, summary
    catalysts: list[str] = []
    risks: list[str] = []
    key_events: list[str] = []
    recommendation = "Hold"
    summary = ""
    if articles:
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel
            vertexai.init(
                project=settings.google_cloud_project,
                location=settings.google_cloud_location,
            )
            model = GenerativeModel("gemini-2.0-flash-001")
            articles_text = "\n".join(
                f"- {a['title']}: {a.get('summary', '')[:200]}"
                for a in articles[:15]
            )
            prompt = (
                f"Analyze these recent news articles for {ticker} stock.\n\n"
                f"Articles:\n{articles_text}\n\n"
                "Return ONLY valid JSON (no markdown fences):\n"
                '{"catalysts":["3-5 concise positive factors from the news"],'
                '"risks":["3-5 concise negative factors or concerns"],'
                '"keyEvents":["2-3 significant recent events or announcements"],'
                '"recommendation":"Buy|Hold|Sell|Watch",'
                '"summary":"2-3 sentence plain-English overview of the news landscape"}'
            )
            resp = await asyncio.to_thread(model.generate_content, prompt)
            text = resp.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            parsed = json.loads(text)
            catalysts = parsed.get("catalysts", [])
            risks = parsed.get("risks", [])
            key_events = parsed.get("keyEvents", [])
            recommendation = parsed.get("recommendation", "Hold")
            summary = parsed.get("summary", "")
        except Exception:
            pass

    return {
        "ticker": ticker,
        "overallSentiment": overall,
        "socialSentiment": {
            "signal": social_signal,
            "bullishPercent": bullish_pct,
            "watchlistCount": watchlist_count,
        },
        "newsSentiment": news_sentiment,
        "catalysts": catalysts,
        "risks": risks,
        "keyEvents": key_events,
        "headlines": [
            {"title": a["title"], "source": a["source"], "url": a["url"], "publishedAt": a["publishedAt"]}
            for a in articles
        ],
        "articles": articles,
        "recommendation": recommendation,
        "summary": summary,
        "asOf": datetime.now(timezone.utc).isoformat(),
        "finnhubScore": company_news_score,
    }


@router.get("/{ticker}/news-analysis")
async def news_analysis(ticker: str):
    """Merged news + AI sentiment synthesis for the News & Sentiment tab."""
    ticker = ticker.upper()
    now = time.time()
    if ticker in _news_cache:
        ts, data = _news_cache[ticker]
        if now - ts < _NEWS_CACHE_TTL:
            return data
    try:
        result = await _build_news_analysis(ticker)
        _news_cache[ticker] = (now, result)
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/news-sentiment")
async def news_sentiment(ticker: str):
    """Recent news articles with NLP sentiment scores from Finnhub."""
    try:
        return await finnhub_svc.get_news_with_sentiment(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/earnings-calendar")
async def earnings_calendar(ticker: str):
    """Upcoming and recent earnings dates with EPS/revenue estimates from Finnhub."""
    try:
        return await finnhub_svc.get_earnings_calendar(ticker.upper())
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{ticker}/sec-filings")
async def sec_filings(ticker: str):
    """Recent 10-K, 10-Q, 8-K filings with direct SEC document URLs (free, no key)."""
    try:
        return await edgar_svc.get_recent_filings(ticker.upper())
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
