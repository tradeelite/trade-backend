"""FastMCP server — exposes TradeElite tools to trade-agents via MCP over SSE."""

from mcp.server.fastmcp import FastMCP

from app.services import indicators as ind_svc
from app.services import stocktwits, yahoo_finance as yf_svc
from app.services import suggestions as sug_svc

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
# Portfolio tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def get_portfolios() -> list[dict]:
    """Get all portfolios with total value, cost basis, and gain/loss summary."""
    from app.db.database import AsyncSessionLocal
    from app.db.models import Holding, Portfolio
    from sqlalchemy import select
    import asyncio

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Portfolio))
        portfolios = result.scalars().all()
        out = []
        for p in portfolios:
            hr = await db.execute(select(Holding).where(Holding.portfolio_id == p.id))
            holdings = hr.scalars().all()
            out.append({
                "id": p.id, "name": p.name, "description": p.description,
                "holdingsCount": len(holdings),
            })
        return out


@mcp.tool()
async def get_portfolio_holdings(portfolio_id: int) -> list[dict]:
    """Get all holdings for a portfolio with live price valuations.

    Args:
        portfolio_id: Numeric portfolio ID.
    """
    from app.db.database import AsyncSessionLocal
    from app.db.models import Holding
    from sqlalchemy import select
    import asyncio

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Holding).where(Holding.portfolio_id == portfolio_id))
        holdings = result.scalars().all()

    async def _enrich(h):
        base = {"ticker": h.ticker, "shares": h.shares, "avgCost": h.avg_cost}
        try:
            price = yf_svc.get_quote(h.ticker)["price"]
            value = h.shares * price
            cost = h.shares * h.avg_cost
            base.update({"currentPrice": price, "currentValue": round(value, 2),
                          "gainLoss": round(value - cost, 2)})
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
    from app.db.database import AsyncSessionLocal
    from app.db.models import OptionTrade
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        q = select(OptionTrade)
        if status in ("open", "closed"):
            q = q.where(OptionTrade.status == status)
        result = await db.execute(q)
        trades = result.scalars().all()
        return [
            {
                "id": t.id, "ticker": t.ticker, "optionType": t.option_type,
                "direction": t.direction, "strikePrice": t.strike_price,
                "expiryDate": t.expiry_date, "premium": t.premium,
                "quantity": t.quantity, "status": t.status,
                "closePremium": t.close_premium, "closeDate": t.close_date,
            }
            for t in trades
        ]


@mcp.tool()
async def get_options_suggestions() -> list[dict]:
    """Get rule-based suggestions for open options positions (profit targets, DTE, assignment risk, earnings)."""
    from app.db.database import AsyncSessionLocal
    from app.db.models import OptionTrade
    from sqlalchemy import select
    import asyncio

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(OptionTrade).where(OptionTrade.status == "open"))
        trades = result.scalars().all()

    tickers = list({t.ticker for t in trades})

    async def _price(ticker):
        try:
            return ticker, yf_svc.get_quote(ticker)["price"]
        except Exception:
            return ticker, None

    price_results = await asyncio.gather(*[_price(t) for t in tickers])
    prices = {t: p for t, p in price_results if p is not None}
    trade_dicts = [
        {"id": t.id, "ticker": t.ticker, "option_type": t.option_type,
         "direction": t.direction, "strike_price": t.strike_price,
         "expiry_date": t.expiry_date, "premium": t.premium,
         "quantity": t.quantity, "status": t.status}
        for t in trades
    ]
    return sug_svc.evaluate_all(trade_dicts, prices)
