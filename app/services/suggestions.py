"""Options suggestion rules — ported from src/lib/options/suggestions.ts."""

from datetime import date


PROFIT_TARGET_PERCENT = 50
ROLL_DTE_THRESHOLD = 21
STRIKE_PROXIMITY_PERCENT = 3
EARNINGS_ALERT_DAYS = 14


def _dte(expiry_date: str) -> int:
    try:
        expiry = date.fromisoformat(expiry_date)
        delta = (expiry - date.today()).days
        return max(delta, 0)
    except Exception:
        return 0


def evaluate_trade(trade: dict, current_price: float | None, earnings_date: str | None = None) -> list[dict]:
    suggestions = []
    ticker = trade["ticker"]
    trade_id = trade["id"]

    # 1. Profit target (sold options only)
    if trade["direction"] == "sell" and current_price is not None:
        entry = trade["premium"]
        if entry > 0 and (entry - current_price) / entry * 100 >= PROFIT_TARGET_PERCENT:
            suggestions.append({
                "tradeId": trade_id, "ticker": ticker, "action": "close",
                "reason": "Profit target reached",
                "urgency": "medium",
                "details": f"Premium dropped {round((entry - current_price) / entry * 100)}% from entry — lock in profit.",
            })

    # 2. DTE roll
    dte = _dte(trade["expiry_date"])
    if 0 < dte <= ROLL_DTE_THRESHOLD:
        suggestions.append({
            "tradeId": trade_id, "ticker": ticker, "action": "roll",
            "reason": f"{dte} days to expiry",
            "urgency": "high" if dte <= 7 else "medium",
            "details": f"{'Urgent: only ' if dte <= 7 else ''}{dte} DTE — consider rolling to a later expiry.",
        })

    # 3. Strike proximity (assignment risk)
    if current_price is not None:
        strike = trade["strike_price"]
        proximity = abs(current_price - strike) / strike * 100
        if proximity <= STRIKE_PROXIMITY_PERCENT:
            suggestions.append({
                "tradeId": trade_id, "ticker": ticker, "action": "close",
                "reason": "Assignment risk",
                "urgency": "high",
                "details": f"Price (${current_price:.2f}) is within {proximity:.1f}% of strike (${strike:.2f}).",
            })

    # 4. Earnings conflict
    if earnings_date:
        try:
            expiry = date.fromisoformat(trade["expiry_date"])
            earnings = date.fromisoformat(earnings_date)
            days_to_earnings = (earnings - date.today()).days
            if 0 <= days_to_earnings <= EARNINGS_ALERT_DAYS and earnings <= expiry:
                suggestions.append({
                    "tradeId": trade_id, "ticker": ticker, "action": "alert",
                    "reason": "Earnings within expiry window",
                    "urgency": "high",
                    "details": f"Earnings on {earnings_date} — {days_to_earnings} days away, before expiry {trade['expiry_date']}.",
                })
        except Exception:
            pass

    return suggestions


def evaluate_all(trades: list[dict], prices: dict[str, float], earnings: dict[str, str] = {}) -> list[dict]:
    all_suggestions = []
    for trade in trades:
        if trade["status"] != "open":
            continue
        price = prices.get(trade["ticker"])
        earnings_date = earnings.get(trade["ticker"])
        all_suggestions.extend(evaluate_trade(trade, price, earnings_date))

    order = {"high": 0, "medium": 1, "low": 2}
    all_suggestions.sort(key=lambda s: order.get(s["urgency"], 3))
    return all_suggestions
