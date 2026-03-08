"""Pydantic request/response schemas."""

from datetime import datetime
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Portfolios
# ---------------------------------------------------------------------------

class PortfolioCreate(BaseModel):
    name: str
    description: str | None = None


class PortfolioUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class PortfolioOut(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class PortfolioWithStats(PortfolioOut):
    total_value: float = 0.0
    total_cost: float = 0.0
    total_gain_loss: float = 0.0
    total_gain_loss_percent: float = 0.0
    holdings_count: int = 0


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------

class HoldingCreate(BaseModel):
    ticker: str
    shares: float
    avg_cost: float


class HoldingOut(BaseModel):
    id: str
    portfolio_id: str
    ticker: str
    shares: float
    avg_cost: float
    added_at: datetime
    current_price: float | None = None
    current_value: float | None = None
    gain_loss: float | None = None
    gain_loss_percent: float | None = None


# ---------------------------------------------------------------------------
# Option Trades
# ---------------------------------------------------------------------------

class OptionTradeCreate(BaseModel):
    ticker: str
    option_type: str
    direction: str
    strike_price: float
    expiry_date: str
    premium: float
    quantity: int
    brokerage: str | None = None
    notes: str | None = None
    source: str = "manual"


class OptionTradeUpdate(BaseModel):
    status: str | None = None
    close_premium: float | None = None
    close_date: str | None = None
    notes: str | None = None
    brokerage: str | None = None


class OptionTradeOut(BaseModel):
    id: str
    ticker: str
    option_type: str
    direction: str
    strike_price: float
    expiry_date: str
    premium: float
    quantity: int
    brokerage: str | None
    status: str
    close_premium: float | None
    close_date: str | None
    notes: str | None
    source: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class SettingUpdate(BaseModel):
    key: str
    value: str


# ---------------------------------------------------------------------------
# Agent query
# ---------------------------------------------------------------------------

class AgentQueryRequest(BaseModel):
    message: str
    session_id: str = "default"


class AgentQueryResponse(BaseModel):
    response: str
    session_id: str
