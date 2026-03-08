"""Stock data API routes."""

import asyncio
import time

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
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

    pe = val.get("peRatio") or val.get("pe_ratio") or fund.get("peRatio")
    val_signal = val.get("signal") or ("overvalued" if pe and float(pe) > 35 else "undervalued" if pe and float(pe) < 15 else "fairly_valued")

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

    normalized_fund = {
        "ticker": raw.get("ticker", ""),
        "valuation": {
            "signal": val_signal,
            "peRatio": float(pe) if pe is not None else None,
            "forwardPE": val.get("forwardPE") or val.get("forward_pe"),
            "pegRatio": val.get("pegRatio") or val.get("peg_ratio") or val.get("pegRatio"),
            "priceToBook": val.get("priceToBook") or val.get("priceToBookRatio") or val.get("price_to_book"),
        },
        "financialHealth": {
            "signal": _normalize_signal(health.get("signal") or health.get("overallHealth") or "moderate"),
            "debtToEquity": health.get("debtToEquity") or health.get("debtToEquityRatio"),
            "currentRatio": health.get("currentRatio"),
            "operatingMargin": str(health.get("operatingMargin") or health.get("profitMargin") or "N/A"),
            "returnOnEquity": str(health.get("returnOnEquity") or "N/A"),
        },
        "growth": {
            "signal": _normalize_signal(growth.get("signal") or "moderate"),
            "revenueGrowth": str(growth.get("revenueGrowth") or "N/A"),
            "earningsGrowth": str(growth.get("earningsGrowth") or growth.get("epsGrowth") or "N/A"),
            "epsTTM": growth.get("epsTTM") or growth.get("eps"),
        },
        "analystConsensus": {
            "rating": str(analyst.get("rating") or "Hold"),
            "targetPrice": analyst.get("targetPrice") or analyst.get("target_price"),
            "numAnalysts": analyst.get("numAnalysts") or analyst.get("num_analysts") or 0,
            "breakdown": {
                "strongBuy": int(breakdown.get("strongBuy") or breakdown.get("strong_buy") or 0),
                "buy": int(breakdown.get("buy") or 0),
                "hold": int(breakdown.get("hold") or 0),
                "sell": int(breakdown.get("sell") or breakdown.get("strongSell") or 0),
            },
        },
        "earnings": {
            "trend": earnings_trend,
            "lastQuarters": earnings_quarters,
        },
        "recommendation": fund.get("recommendation") or "Hold",
        "summary": fund.get("summary") or fund.get("description") or "",
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

VALID_RANGES = {"1D", "1W", "1M", "3M", "1Y", "5Y"}

_analysis_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 600  # 10 minutes


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


@router.get("/{ticker}/analyst-ratings")
def analyst_ratings(ticker: str):
    try:
        return fund_svc.get_analyst_ratings(ticker.upper())
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
