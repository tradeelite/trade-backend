"""Financial Modeling Prep (FMP) API service — fundamental financial data.

Free tier: 250 requests/day.
Covers: income statements, balance sheets, cash flows, key metrics,
        earnings surprises, dividends, DCF valuation, company profile.
"""

import asyncio
import httpx

from app.core.config import settings

FMP_BASE = "https://financialmodelingprep.com/api/v3"


async def _get(path: str, params: dict | None = None) -> dict | list:
    url = f"{FMP_BASE}{path}"
    p = {"apikey": settings.fmp_api_key}
    if params:
        p.update(params)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=p)
        r.raise_for_status()
        return r.json()


async def get_income_statement(ticker: str, period: str = "annual", limit: int = 5) -> list[dict]:
    """Income statement: revenue, gross profit, operating income, net income, EPS, margins."""
    data = await _get(f"/income-statement/{ticker}", {"period": period, "limit": limit})
    return data if isinstance(data, list) else []


async def get_balance_sheet(ticker: str, period: str = "annual", limit: int = 5) -> list[dict]:
    """Balance sheet: total assets, liabilities, equity, debt, cash, working capital."""
    data = await _get(f"/balance-sheet-statement/{ticker}", {"period": period, "limit": limit})
    return data if isinstance(data, list) else []


async def get_cash_flow(ticker: str, period: str = "annual", limit: int = 5) -> list[dict]:
    """Cash flow: operating CF, investing CF, FCF, CapEx, dividends paid, buybacks."""
    data = await _get(f"/cash-flow-statement/{ticker}", {"period": period, "limit": limit})
    return data if isinstance(data, list) else []


async def get_key_metrics(ticker: str, period: str = "annual", limit: int = 5) -> list[dict]:
    """Key metrics: FCF yield, EV/EBITDA, ROIC, revenue per share, net debt/FCF, etc."""
    data = await _get(f"/key-metrics/{ticker}", {"period": period, "limit": limit})
    return data if isinstance(data, list) else []


async def get_financial_ratios(ticker: str, period: str = "annual", limit: int = 5) -> list[dict]:
    """Financial ratios: P/E, P/S, P/B, EV/EBITDA, gross/operating/net/FCF margins."""
    data = await _get(f"/ratios/{ticker}", {"period": period, "limit": limit})
    return data if isinstance(data, list) else []


async def get_earnings_surprises(ticker: str) -> list[dict]:
    """Last 8 quarters: date, estimated EPS, actual EPS, surprise %."""
    data = await _get(f"/earnings-surprises/{ticker}")
    items = data if isinstance(data, list) else []
    # FMP returns oldest-first; reverse so newest quarter is first
    return list(reversed(items))[:8]


async def get_dividends(ticker: str) -> dict:
    """Full dividend payment history: amount, date, yield, frequency."""
    data = await _get(f"/historical-price-full/stock_dividend/{ticker}")
    if isinstance(data, list) and data:
        return data[0]
    return data if isinstance(data, dict) else {}


async def get_dcf(ticker: str) -> dict:
    """DCF fair value estimate: stock price vs intrinsic value."""
    data = await _get(f"/discounted-cash-flow/{ticker}")
    if isinstance(data, list) and data:
        return data[0]
    return data if isinstance(data, dict) else {}


async def get_company_profile(ticker: str) -> dict:
    """Company profile: description, sector, industry, market cap, beta, IPO date, exchange."""
    data = await _get(f"/profile/{ticker}")
    if isinstance(data, list) and data:
        return data[0]
    return data if isinstance(data, dict) else {}


async def get_financials(ticker: str) -> dict:
    """
    Fetch all financial statements in parallel: income (annual + quarterly),
    balance sheet (annual), and cash flow (annual).
    """
    annual_income, quarterly_income, annual_balance, annual_cashflow = await asyncio.gather(
        get_income_statement(ticker, "annual", 5),
        get_income_statement(ticker, "quarter", 8),
        get_balance_sheet(ticker, "annual", 5),
        get_cash_flow(ticker, "annual", 5),
    )
    return {
        "ticker": ticker,
        "incomeStatement": {
            "annual": annual_income,
            "quarterly": quarterly_income,
        },
        "balanceSheet": {
            "annual": annual_balance,
        },
        "cashFlow": {
            "annual": annual_cashflow,
        },
    }
