"""
Technical Signals Service — Tier 1 indicator stack (Part 6 of TradeElite spec).

Fetches 400 days of daily OHLCV via yfinance, computes all Tier 1 indicators
using pandas-ta, and returns a structured JSON with per-indicator values and
Buy / Sell / Neutral signals following the Part 7 output format.

Tier 1 indicators implemented:
  Trend/MA:      SMA 20/50/200 · EMA 9/21/50
  Momentum:      RSI(14) · MACD(12,26,9) · Stochastic(14,3,3) · Williams %R(14)
  Volume:        OBV · Relative Volume
  Volatility:    Bollinger Bands(20,2) · ATR(14)
  Trend Strength: ADX(14)
"""

from __future__ import annotations

import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pandas_ta as ta  # noqa: F401 — registers df.ta accessor
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _f(val) -> float | None:
    """Safely convert any value to float; return None for NaN/None/inf."""
    if val is None:
        return None
    try:
        v = float(val)
        if v != v or v == float("inf") or v == float("-inf"):  # NaN / inf check
            return None
        return round(v, 4)
    except (TypeError, ValueError):
        return None


def _signal(buy: bool, sell: bool) -> str:
    if buy:
        return "Buy"
    if sell:
        return "Sell"
    return "Neutral"


def _score_label(score: float) -> str:
    """Map raw score (-1..+1) to TradingView-style label."""
    if score >= 0.5:
        return "Strong Buy"
    if score >= 0.1:
        return "Buy"
    if score > -0.1:
        return "Neutral"
    if score > -0.5:
        return "Sell"
    return "Strong Sell"


def _col(df: pd.DataFrame, *names: str) -> float | None:
    """Return last non-NaN value for the first matching column name."""
    for name in names:
        if name in df.columns:
            v = _f(df[name].iloc[-1])
            if v is not None:
                return v
        # case-insensitive fallback
        match = [c for c in df.columns if c.lower() == name.lower()]
        if match:
            v = _f(df[match[0]].iloc[-1])
            if v is not None:
                return v
    return None


def _prev_col(df: pd.DataFrame, *names: str) -> float | None:
    """Return second-to-last non-NaN value for the first matching column."""
    if len(df) < 2:
        return None
    for name in names:
        if name in df.columns:
            v = _f(df[name].iloc[-2])
            if v is not None:
                return v
    return None


def _col_series(df: pd.DataFrame, *names: str) -> pd.Series | None:
    """Return the full series for the first matching column."""
    for name in names:
        if name in df.columns:
            return df[name].dropna()
        match = [c for c in df.columns if c.lower() == name.lower()]
        if match:
            return df[match[0]].dropna()
    return None


# ─── Main computation ─────────────────────────────────────────────────────────

def compute_technical_signals(ticker: str) -> dict:
    """
    Fetch OHLCV data and compute all Tier 1 technical indicators.
    Returns structured dict with per-indicator value + Buy/Sell/Neutral signal.
    """
    ticker = ticker.upper()

    # ── Fetch 400 days daily data (enough for SMA 200 + buffer) ──────────────
    tkr = yf.Ticker(ticker)
    df_raw = tkr.history(period="400d", interval="1d", auto_adjust=True)

    if df_raw is None or df_raw.empty or len(df_raw) < 50:
        raise ValueError(f"Insufficient OHLCV data for {ticker}")

    # pandas-ta expects lowercase ohlcv columns
    df = df_raw.copy()
    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])

    price = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2]) if len(df) > 1 else price

    # ── Compute all indicators via pandas-ta ──────────────────────────────────
    # Moving Averages
    df.ta.sma(length=20, append=True)
    df.ta.sma(length=50, append=True)
    df.ta.sma(length=200, append=True)
    df.ta.ema(length=9, append=True)
    df.ta.ema(length=21, append=True)
    df.ta.ema(length=50, append=True)

    # Momentum
    df.ta.rsi(length=14, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    df.ta.stoch(k=14, d=3, smooth_k=3, append=True)
    df.ta.willr(length=14, append=True)

    # Volatility
    df.ta.bbands(length=20, std=2.0, append=True)
    df.ta.atr(length=14, append=True)

    # Trend Strength
    df.ta.adx(length=14, append=True)

    # Volume
    df.ta.obv(append=True)

    # ── Extract current values ────────────────────────────────────────────────

    # Moving average values
    sma20  = _col(df, "SMA_20")
    sma50  = _col(df, "SMA_50")
    sma200 = _col(df, "SMA_200")
    ema9   = _col(df, "EMA_9")
    ema21  = _col(df, "EMA_21")
    ema50  = _col(df, "EMA_50")

    def _ma_sig(val: float | None) -> str:
        if val is None:
            return "Neutral"
        return _signal(price > val, price < val)

    def _ma_dir(col_name: str) -> str:
        cur = _col(df, col_name)
        prv = _prev_col(df, col_name)
        if cur is None or prv is None:
            return "flat"
        return "up" if cur > prv else "down" if cur < prv else "flat"

    moving_averages = [
        {
            "name": "SMA 20",
            "period": 20,
            "type": "Simple",
            "value": sma20,
            "priceVsMA": "above" if sma20 and price > sma20 else "below",
            "direction": _ma_dir("SMA_20"),
            "signal": _ma_sig(sma20),
            "pctFromPrice": round((price - sma20) / sma20 * 100, 2) if sma20 else None,
        },
        {
            "name": "SMA 50",
            "period": 50,
            "type": "Simple",
            "value": sma50,
            "priceVsMA": "above" if sma50 and price > sma50 else "below",
            "direction": _ma_dir("SMA_50"),
            "signal": _ma_sig(sma50),
            "pctFromPrice": round((price - sma50) / sma50 * 100, 2) if sma50 else None,
        },
        {
            "name": "SMA 200",
            "period": 200,
            "type": "Simple",
            "value": sma200,
            "priceVsMA": "above" if sma200 and price > sma200 else "below",
            "direction": _ma_dir("SMA_200"),
            "signal": _ma_sig(sma200),
            "pctFromPrice": round((price - sma200) / sma200 * 100, 2) if sma200 else None,
        },
        {
            "name": "EMA 9",
            "period": 9,
            "type": "Exponential",
            "value": ema9,
            "priceVsMA": "above" if ema9 and price > ema9 else "below",
            "direction": _ma_dir("EMA_9"),
            "signal": _ma_sig(ema9),
            "pctFromPrice": round((price - ema9) / ema9 * 100, 2) if ema9 else None,
        },
        {
            "name": "EMA 21",
            "period": 21,
            "type": "Exponential",
            "value": ema21,
            "priceVsMA": "above" if ema21 and price > ema21 else "below",
            "direction": _ma_dir("EMA_21"),
            "signal": _ma_sig(ema21),
            "pctFromPrice": round((price - ema21) / ema21 * 100, 2) if ema21 else None,
        },
        {
            "name": "EMA 50",
            "period": 50,
            "type": "Exponential",
            "value": ema50,
            "priceVsMA": "above" if ema50 and price > ema50 else "below",
            "direction": _ma_dir("EMA_50"),
            "signal": _ma_sig(ema50),
            "pctFromPrice": round((price - ema50) / ema50 * 100, 2) if ema50 else None,
        },
    ]

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi_val = _col(df, "RSI_14")
    rsi_status = "neutral"
    if rsi_val is not None:
        if rsi_val < 30:
            rsi_status = "oversold"
        elif rsi_val > 70:
            rsi_status = "overbought"
    rsi_signal = _signal(
        rsi_val is not None and rsi_val < 30,
        rsi_val is not None and rsi_val > 70,
    )

    # ── MACD ──────────────────────────────────────────────────────────────────
    macd_line = _col(df, "MACD_12_26_9")
    macd_sig_line = _col(df, "MACDs_12_26_9")
    macd_hist = _col(df, "MACDh_12_26_9")
    prev_macd = _prev_col(df, "MACD_12_26_9")
    prev_macd_sig = _prev_col(df, "MACDs_12_26_9")
    prev_hist = _prev_col(df, "MACDh_12_26_9")

    macd_signal_str = _signal(
        macd_line is not None and macd_sig_line is not None and macd_line > macd_sig_line,
        macd_line is not None and macd_sig_line is not None and macd_line < macd_sig_line,
    )
    macd_crossover = None
    if all(v is not None for v in [prev_macd, prev_macd_sig, macd_line, macd_sig_line]):
        if prev_macd < prev_macd_sig and macd_line > macd_sig_line:  # type: ignore[operator]
            macd_crossover = "bullish"
        elif prev_macd > prev_macd_sig and macd_line < macd_sig_line:  # type: ignore[operator]
            macd_crossover = "bearish"
    hist_direction = "flat"
    if macd_hist is not None and prev_hist is not None:
        if macd_hist > prev_hist:
            hist_direction = "expanding"
        elif macd_hist < prev_hist:
            hist_direction = "contracting"

    # ── Stochastic ────────────────────────────────────────────────────────────
    stoch_k = _col(df, "STOCHk_14_3_3")
    stoch_d = _col(df, "STOCHd_14_3_3")
    stoch_status = "neutral"
    if stoch_k is not None:
        if stoch_k < 20:
            stoch_status = "oversold"
        elif stoch_k > 80:
            stoch_status = "overbought"
    stoch_signal = _signal(
        stoch_k is not None and stoch_k < 20,
        stoch_k is not None and stoch_k > 80,
    )

    # ── Williams %R ───────────────────────────────────────────────────────────
    willr_val = _col(df, "WILLR_14")
    willr_signal = _signal(
        willr_val is not None and willr_val < -80,
        willr_val is not None and willr_val > -20,
    )

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    bb_lower  = _col(df, "BBL_20_2.0")
    bb_mid    = _col(df, "BBM_20_2.0")
    bb_upper  = _col(df, "BBU_20_2.0")
    bb_width  = _col(df, "BBB_20_2.0")   # bandwidth %
    bb_pct_b  = _col(df, "BBP_20_2.0")   # %B

    bb_position = "middle"
    if bb_pct_b is not None:
        if bb_pct_b > 0.8:
            bb_position = "upper"
        elif bb_pct_b < 0.2:
            bb_position = "lower"

    bb_signal = _signal(
        bb_pct_b is not None and bb_pct_b < 0.2,
        bb_pct_b is not None and bb_pct_b > 0.8,
    )

    bb_bw_trend = "normal"
    bw_series = _col_series(df, "BBB_20_2.0")
    if bw_series is not None and len(bw_series) >= 10:
        recent = float(bw_series.iloc[-5:].mean())
        older  = float(bw_series.iloc[-10:-5].mean())
        if older > 0:
            if recent > older * 1.05:
                bb_bw_trend = "expanding"
            elif recent < older * 0.95:
                bb_bw_trend = "contracting"

    # ── ATR ───────────────────────────────────────────────────────────────────
    # pandas-ta names the column ATRr_14 (ratio) in some builds, ATR_14 in others
    atr_raw = _col(df, "ATRr_14", "ATR_14")
    atr_dollar: float | None = None
    atr_pct: float | None = None
    if atr_raw is not None and price > 0:
        if atr_raw < 1.0:
            # It's a ratio (ATR/Close); convert to dollar and percent
            atr_dollar = round(atr_raw * price, 4)
            atr_pct = round(atr_raw * 100, 2)
        else:
            # It's an absolute dollar value
            atr_dollar = atr_raw
            atr_pct = round(atr_raw / price * 100, 2)

    # ── ADX ───────────────────────────────────────────────────────────────────
    adx_val      = _col(df, "ADX_14")
    adx_plus_di  = _col(df, "DMP_14")
    adx_minus_di = _col(df, "DMN_14")

    adx_strength = "weak"
    adx_di_control = "neutral"
    if adx_val is not None:
        if adx_val >= 40:
            adx_strength = "strong"
        elif adx_val >= 20:
            adx_strength = "moderate"

    if adx_plus_di is not None and adx_minus_di is not None:
        adx_di_control = "bulls" if adx_plus_di > adx_minus_di else "bears"

    adx_signal = _signal(
        adx_val is not None and adx_val > 25
        and adx_plus_di is not None and adx_minus_di is not None
        and adx_plus_di > adx_minus_di,
        adx_val is not None and adx_val > 25
        and adx_plus_di is not None and adx_minus_di is not None
        and adx_minus_di > adx_plus_di,
    )

    # ── OBV ───────────────────────────────────────────────────────────────────
    obv_series = _col_series(df, "OBV")
    obv_trend = "flat"
    obv_signal = "Neutral"
    obv_val: float | None = None
    if obv_series is not None and len(obv_series) >= 21:
        obv_val = _f(obv_series.iloc[-1])
        obv_now = float(obv_series.iloc[-1])
        obv_sma = float(obv_series.iloc[-20:].mean())
        if obv_now > obv_sma:
            obv_trend = "rising"
            obv_signal = "Buy"
        elif obv_now < obv_sma:
            obv_trend = "falling"
            obv_signal = "Sell"

    # ── Volume ────────────────────────────────────────────────────────────────
    vol_today = int(df["volume"].iloc[-1])
    vol_avg_20 = float(df["volume"].iloc[-21:-1].mean()) if len(df) > 20 else float(df["volume"].mean())
    rel_vol = round(vol_today / vol_avg_20, 2) if vol_avg_20 > 0 else None
    vol_signal = _signal(
        rel_vol is not None and rel_vol > 1.2,
        rel_vol is not None and rel_vol < 0.7,
    )

    # ── Golden / Death Cross ──────────────────────────────────────────────────
    golden_cross = False
    death_cross = False
    cross_date: str | None = None
    sma50_s = _col_series(df, "SMA_50")
    sma200_s = _col_series(df, "SMA_200")
    if sma50_s is not None and sma200_s is not None:
        aligned = pd.concat([sma50_s.rename("s50"), sma200_s.rename("s200")], axis=1).dropna()
        if len(aligned) >= 2:
            if float(aligned["s50"].iloc[-1]) > float(aligned["s200"].iloc[-1]):
                golden_cross = True
                for i in range(len(aligned) - 1, 0, -1):
                    if float(aligned["s50"].iloc[i - 1]) <= float(aligned["s200"].iloc[i - 1]):
                        cross_date = str(aligned.index[i].date())
                        break
            else:
                death_cross = True
                for i in range(len(aligned) - 1, 0, -1):
                    if float(aligned["s50"].iloc[i - 1]) >= float(aligned["s200"].iloc[i - 1]):
                        cross_date = str(aligned.index[i].date())
                        break

    # ── 52-week range & distance from key levels ──────────────────────────────
    info = tkr.info or {}
    high_52w = _f(info.get("fiftyTwoWeekHigh")) or _f(df["high"].max())
    low_52w  = _f(info.get("fiftyTwoWeekLow"))  or _f(df["low"].min())
    dist_52w_high = round((price - high_52w) / high_52w * 100, 2) if high_52w else None
    dist_52w_low  = round((price - low_52w)  / low_52w  * 100, 2) if low_52w  else None
    dist_200sma   = round((price - sma200) / sma200 * 100, 2) if sma200 else None

    # ── Composite score ───────────────────────────────────────────────────────
    ma_signals  = [_ma_sig(sma20), _ma_sig(sma50), _ma_sig(sma200),
                   _ma_sig(ema9), _ma_sig(ema21), _ma_sig(ema50)]
    osc_signals = [rsi_signal, macd_signal_str, stoch_signal, willr_signal, bb_signal]
    ts_signals  = [adx_signal]
    vol_signals = [obv_signal]
    all_signals = ma_signals + osc_signals + ts_signals + vol_signals

    buy_count     = all_signals.count("Buy")
    sell_count    = all_signals.count("Sell")
    neutral_count = all_signals.count("Neutral")
    total         = len(all_signals)

    raw_score        = (buy_count - sell_count) / total if total else 0
    composite_score  = round((raw_score + 1) * 5, 1)   # 0–10 scale
    composite_label  = _score_label(raw_score)

    ma_buy  = ma_signals.count("Buy")
    ma_sell = ma_signals.count("Sell")
    ma_neut = ma_signals.count("Neutral")
    osc_buy  = (osc_signals + ts_signals + vol_signals).count("Buy")
    osc_sell = (osc_signals + ts_signals + vol_signals).count("Sell")
    osc_neut = (osc_signals + ts_signals + vol_signals).count("Neutral")

    # ── Build structured output ───────────────────────────────────────────────
    return {
        "ticker": ticker,
        "price": round(price, 2),
        "changePercent": round((price - prev_close) / prev_close * 100, 2) if prev_close else None,
        "generatedAt": datetime.now(timezone.utc).isoformat(),

        # ── Composite (TradingView-style) ─────────────────────────────────────
        "composite": {
            "score": composite_score,        # 0–10
            "rawScore": round(raw_score, 4), # -1 to +1
            "label": composite_label,
            "buy": buy_count,
            "neutral": neutral_count,
            "sell": sell_count,
            "movingAverages": {"buy": ma_buy, "neutral": ma_neut, "sell": ma_sell},
            "oscillators":    {"buy": osc_buy, "neutral": osc_neut, "sell": osc_sell},
        },

        # ── Moving Averages (Barchart-style table) ────────────────────────────
        "movingAverages": moving_averages,

        # ── Oscillators ───────────────────────────────────────────────────────
        "oscillators": [
            {
                "name": "RSI (14)",
                "value": rsi_val,
                "status": rsi_status,
                "signal": rsi_signal,
                "levels": {"oversold": 30, "overbought": 70},
            },
            {
                "name": "MACD (12,26,9)",
                "macdLine": macd_line,
                "signalLine": macd_sig_line,
                "histogram": macd_hist,
                "histogramDirection": hist_direction,
                "crossover": macd_crossover,
                "signal": macd_signal_str,
            },
            {
                "name": "Stochastic (14,3,3)",
                "k": stoch_k,
                "d": stoch_d,
                "status": stoch_status,
                "signal": stoch_signal,
                "levels": {"oversold": 20, "overbought": 80},
            },
            {
                "name": "Williams %R (14)",
                "value": willr_val,
                "signal": willr_signal,
                "levels": {"oversold": -80, "overbought": -20},
            },
            {
                "name": "Bollinger Bands (20,2)",
                "upper": bb_upper,
                "middle": bb_mid,
                "lower": bb_lower,
                "bandwidth": bb_width,
                "percentB": bb_pct_b,
                "position": bb_position,
                "bandwidthTrend": bb_bw_trend,
                "signal": bb_signal,
            },
            {
                "name": "ADX (14)",
                "adx": adx_val,
                "plusDI": adx_plus_di,
                "minusDI": adx_minus_di,
                "strength": adx_strength,
                "diControl": adx_di_control,
                "signal": adx_signal,
            },
            {
                "name": "OBV",
                "value": obv_val,
                "trend": obv_trend,
                "signal": obv_signal,
            },
        ],

        # ── Volume ────────────────────────────────────────────────────────────
        "volume": {
            "today": vol_today,
            "avg20d": int(vol_avg_20),
            "relativeVolume": rel_vol,
            "signal": vol_signal,
        },

        # ── Volatility ────────────────────────────────────────────────────────
        "volatility": {
            "atr": {
                "value": atr_dollar,
                "percent": atr_pct,
            },
            "bollingerBands": {
                "upper": bb_upper,
                "middle": bb_mid,
                "lower": bb_lower,
                "percentB": bb_pct_b,
                "position": bb_position,
                "bandwidthTrend": bb_bw_trend,
            },
        },

        # ── Trend Strength ────────────────────────────────────────────────────
        "trendStrength": {
            "adx": adx_val,
            "plusDI": adx_plus_di,
            "minusDI": adx_minus_di,
            "strength": adx_strength,
            "diControl": adx_di_control,
        },

        # ── Snapshot ──────────────────────────────────────────────────────────
        "snapshot": {
            "fiftyTwoWeekHigh": high_52w,
            "fiftyTwoWeekLow":  low_52w,
            "distanceFrom52wHigh": dist_52w_high,
            "distanceFrom52wLow":  dist_52w_low,
            "distanceFrom200SMA":  dist_200sma,
            "goldenCross": golden_cross,
            "deathCross":  death_cross,
            "crossDate":   cross_date,
        },
    }
