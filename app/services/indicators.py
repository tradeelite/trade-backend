"""Technical indicator computation — ported from src/lib/data-providers/indicators.ts."""

from typing import TypedDict


class OHLCV(TypedDict):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: int


def compute_sma(data: list[OHLCV], period: int) -> list[dict]:
    result = []
    for i in range(period - 1, len(data)):
        avg = sum(d["close"] for d in data[i - period + 1 : i + 1]) / period
        result.append({"time": data[i]["time"], "value": avg})
    return result


def compute_ema(data: list[OHLCV], period: int) -> list[dict]:
    if len(data) < period:
        return []
    k = 2 / (period + 1)
    seed = sum(d["close"] for d in data[:period]) / period
    ema = seed
    result = [{"time": data[period - 1]["time"], "value": ema}]
    for i in range(period, len(data)):
        ema = data[i]["close"] * k + ema * (1 - k)
        result.append({"time": data[i]["time"], "value": ema})
    return result


def compute_rsi(data: list[OHLCV], period: int = 14) -> list[dict]:
    if len(data) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = data[i]["close"] - data[i - 1]["close"]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    result = []

    def _rsi(ag, al):
        if al == 0:
            return 100.0
        return 100 - 100 / (1 + ag / al)

    result.append({"time": data[period]["time"], "value": _rsi(avg_gain, avg_loss)})
    for i in range(period + 1, len(data)):
        diff = data[i]["close"] - data[i - 1]["close"]
        gain = max(diff, 0)
        loss = max(-diff, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        result.append({"time": data[i]["time"], "value": _rsi(avg_gain, avg_loss)})
    return result


def compute_macd(
    data: list[OHLCV],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> list[dict]:
    fast_ema = compute_ema(data, fast)
    slow_ema = compute_ema(data, slow)
    slow_map = {p["time"]: p["value"] for p in slow_ema}
    macd_line = [
        {"time": p["time"], "value": p["value"] - slow_map[p["time"]]}
        for p in fast_ema
        if p["time"] in slow_map
    ]
    if len(macd_line) < signal:
        return []
    k = 2 / (signal + 1)
    sig_val = sum(p["value"] for p in macd_line[:signal]) / signal
    result = []
    for i, p in enumerate(macd_line):
        if i >= signal - 1:
            if i > signal - 1:
                sig_val = p["value"] * k + sig_val * (1 - k)
            result.append({
                "time": p["time"],
                "macd": p["value"],
                "signal": sig_val,
                "histogram": p["value"] - sig_val,
            })
    return result


def compute_bollinger(data: list[OHLCV], period: int = 20, std_dev: int = 2) -> list[dict]:
    import math
    result = []
    for i in range(period - 1, len(data)):
        window = [d["close"] for d in data[i - period + 1 : i + 1]]
        mid = sum(window) / period
        variance = sum((c - mid) ** 2 for c in window) / period
        sd = math.sqrt(variance)
        result.append({
            "time": data[i]["time"],
            "upper": mid + std_dev * sd,
            "middle": mid,
            "lower": mid - std_dev * sd,
        })
    return result


def compute_all(data: list[OHLCV]) -> dict:
    return {
        "sma20": compute_sma(data, 20),
        "sma50": compute_sma(data, 50),
        "sma200": compute_sma(data, 200),
        "ema12": compute_ema(data, 12),
        "ema26": compute_ema(data, 26),
        "rsi": compute_rsi(data, 14),
        "macd": compute_macd(data, 12, 26, 9),
        "bollingerBands": compute_bollinger(data, 20, 2),
    }
