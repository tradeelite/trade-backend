"""FastMCP server — exposes TradeElite tools to trade-agents via MCP over SSE."""

from mcp.server.fastmcp import FastMCP

from app.services import fundamentals as fund_svc
from app.services import indicators as ind_svc
from app.services import stocktwits, yahoo_finance as yf_svc
from app.services import suggestions as sug_svc
from app.services import technical_signals as ts_svc

mcp = FastMCP("trade-backend")


# ---------------------------------------------------------------------------
# Stock tools
# ---------------------------------------------------------------------------

@mcp.tool()
def search_stocks(query: str) -> list[dict]:
    """Search for stocks and ETFs by ticker or company name.

    Args:
        query: Ticker symbol or company name to search for.
    """
    return yf_svc.search_stocks(query)


@mcp.tool()
def get_stock_quote(ticker: str) -> dict:
    """Get the current real-time price quote for a stock or ETF.

    Args:
        ticker: Stock ticker symbol (e.g. AAPL, MSFT, SPY).
    """
    return yf_svc.get_quote(ticker.upper())


@mcp.tool()
def get_stock_chart(ticker: str, range: str = "3M") -> list[dict]:
    """Get historical OHLCV chart data for a stock.

    Args:
        ticker: Stock ticker symbol.
        range: Time range — one of 1D, 1W, 1M, 3M, 1Y, 5Y. Defaults to 3M.
    """
    return yf_svc.get_chart(ticker.upper(), range)


@mcp.tool()
def get_company_info(ticker: str) -> dict:
    """Get company background: sector, industry, description, employees, website.

    Args:
        ticker: Stock ticker symbol.
    """
    return yf_svc.get_company_summary(ticker.upper())


@mcp.tool()
def get_technical_indicators(ticker: str, range: str = "3M") -> dict:
    """Get technical indicators: SMA(20/50/200), EMA(12/26), RSI, MACD, Bollinger Bands.

    Args:
        ticker: Stock ticker symbol.
        range: Time range — one of 1D, 1W, 1M, 3M, 1Y, 5Y. Defaults to 3M.
    """
    chart_data = yf_svc.get_chart(ticker.upper(), range)
    return ind_svc.compute_all(chart_data)


@mcp.tool()
def get_technical_signals(ticker: str) -> dict:
    """Get all Tier 1 technical indicator signals computed from 400 days of daily OHLCV data.

    Returns a composite score (0-10), per-indicator Buy/Sell/Neutral signals, and a full
    breakdown of: SMA 20/50/200, EMA 9/21/50, RSI(14), MACD(12,26,9), Stochastic(14,3,3),
    Williams %R(14), Bollinger Bands(20,2), ATR(14), ADX(14), OBV, Relative Volume.
    Also includes golden/death cross status and distance from 52-week range and 200 SMA.

    Args:
        ticker: Stock ticker symbol (e.g. AAPL, MSFT, NVDA).
    """
    return ts_svc.compute_technical_signals(ticker.upper())


@mcp.tool()
def get_stock_news(ticker: str) -> list[dict]:
    """Get latest news articles for a stock (title, publisher, URL, published time).

    Args:
        ticker: Stock ticker symbol.
    """
    return yf_svc.get_news(ticker.upper())


@mcp.tool()
async def get_stock_sentiment(ticker: str) -> dict:
    """Get StockTwits social media sentiment: bullish/bearish %, watchlist count, recent messages.

    Args:
        ticker: Stock ticker symbol.
    """
    return await stocktwits.get_sentiment(ticker.upper())


# ---------------------------------------------------------------------------
# Fundamental tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_fundamentals(ticker: str) -> dict:
    """Get fundamental financial metrics: P/E, forward P/E, PEG, margins, ROE, debt ratios.

    Args:
        ticker: Stock ticker symbol (e.g. AAPL, MSFT).
    """
    return fund_svc.get_fundamentals(ticker.upper())


@mcp.tool()
def get_analyst_ratings(ticker: str) -> dict:
    """Get analyst consensus ratings: buy/hold/sell counts, target price, recommendation.

    Args:
        ticker: Stock ticker symbol.
    """
    return fund_svc.get_analyst_ratings(ticker.upper())


@mcp.tool()
def get_earnings_history(ticker: str) -> list[dict]:
    """Get last 4 quarters of earnings history: estimated EPS, actual EPS, surprise %.

    Args:
        ticker: Stock ticker symbol.
    """
    return fund_svc.get_earnings_history(ticker.upper())


@mcp.tool()
def get_volume_analysis(ticker: str) -> dict:
    """Get volume analysis: avg 20/50-day volume, current volume, relative volume, trend.

    Args:
        ticker: Stock ticker symbol.
    """
    return fund_svc.get_volume_analysis(ticker.upper())


# ---------------------------------------------------------------------------
# Portfolio tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_portfolios() -> list[dict]:
    """Get all portfolios with holdings count."""
    from app.db.firestore import get_firestore
    from app.db.repositories.holdings import HoldingRepository
    from app.db.repositories.portfolios import PortfolioRepository

    db = get_firestore()
    portfolio_repo = PortfolioRepository(db)
    holding_repo = HoldingRepository(db)

    portfolios = await portfolio_repo.get_all()
    out = []
    for p in portfolios:
        holdings = await holding_repo.get_by_portfolio(p["id"])
        out.append({
            "id": p["id"], "name": p["name"], "description": p.get("description"),
            "holdingsCount": len(holdings),
        })
    return out


@mcp.tool()
async def get_portfolio_holdings(portfolio_id: str) -> list[dict]:
    """Get all holdings for a portfolio with live price valuations.

    Args:
        portfolio_id: Portfolio document ID.
    """
    import asyncio
    from app.db.firestore import get_firestore
    from app.db.repositories.holdings import HoldingRepository

    holding_repo = HoldingRepository(get_firestore())
    holdings = await holding_repo.get_by_portfolio(portfolio_id)

    async def _enrich(h: dict) -> dict:
        base = {"ticker": h["ticker"], "shares": h["shares"], "avgCost": h["avg_cost"]}
        try:
            price = yf_svc.get_quote(h["ticker"])["price"]
            value = h["shares"] * price
            cost = h["shares"] * h["avg_cost"]
            base.update({
                "currentPrice": price,
                "currentValue": round(value, 2),
                "gainLoss": round(value - cost, 2),
            })
        except Exception:
            pass
        return base

    return await asyncio.gather(*[_enrich(h) for h in holdings])


# ---------------------------------------------------------------------------
# Options tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_options_trades(status: str = "open") -> list[dict]:
    """Get options trades tracked in TradeElite.

    Args:
        status: Filter — "open", "closed", or "all". Defaults to "open".
    """
    from app.db.firestore import get_firestore
    from app.db.repositories.options import OptionRepository

    repo = OptionRepository(get_firestore())
    trades = await repo.get_all(status=status)
    return [
        {
            "id": t["id"], "ticker": t["ticker"], "optionType": t["option_type"],
            "direction": t["direction"], "strikePrice": t["strike_price"],
            "expiryDate": t["expiry_date"], "premium": t["premium"],
            "quantity": t["quantity"], "status": t["status"],
            "closePremium": t.get("close_premium"), "closeDate": t.get("close_date"),
        }
        for t in trades
    ]


@mcp.tool()
async def get_options_suggestions() -> list[dict]:
    """Get rule-based suggestions for open options positions (profit targets, DTE, assignment risk, earnings)."""
    import asyncio
    from app.db.firestore import get_firestore
    from app.db.repositories.options import OptionRepository

    repo = OptionRepository(get_firestore())
    trades = await repo.get_all(status="open")
    tickers = list({t["ticker"] for t in trades})

    async def _price(ticker: str) -> tuple[str, float | None]:
        try:
            return ticker, yf_svc.get_quote(ticker)["price"]
        except Exception:
            return ticker, None

    price_results = await asyncio.gather(*[_price(t) for t in tickers])
    prices = {t: p for t, p in price_results if p is not None}
    return sug_svc.evaluate_all(trades, prices)
