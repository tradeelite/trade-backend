# CLAUDE.md — trade-backend

## Summary
FastAPI backend for TradeElite. Serves REST endpoints for web and MCP tools for agents.

## Key Endpoints

### User-Scoped Data Endpoints

- Portfolio and options routes are user-owned and isolated by request user email:
  - `GET/POST /api/portfolios`
  - `GET/PUT/DELETE /api/portfolios/{id}`
  - `GET/POST/DELETE /api/portfolios/{id}/holdings`
  - `GET/POST /api/options`
  - `GET/PUT/DELETE /api/options/{trade_id}`
  - `GET /api/options/suggestions`
- User context is read from header `x-user-email` (or query `userEmail` fallback).
- Legacy docs with missing `user_email` remain visible only to admin for backward compatibility.
- Admin resolution:
  - Primary: `ALLOWED_EMAIL` env
  - Fallback: earliest allowlisted user record
- Admin-only controls:
  - `/api/users` list/add/remove
  - `/api/settings` write (`PUT`)
  - `/api/users/me` returns current user role (`is_admin`)

### AI / Analysis

| Endpoint | Cache | Description |
|----------|-------|-------------|
| `GET /api/stocks/{ticker}/ai-analysis` | 10 min | Full orchestrated report via Vertex AI Agent Engine |
| `GET /api/stocks/{ticker}/fundamental-analysis` | 10 min | Rich fundamental dashboard (direct build, agent as fallback) |
| `GET /api/stocks/{ticker}/news-analysis` | 5 min | News synthesis — Yahoo Finance + Finnhub + StockTwits + Gemini Flash |
| `GET /api/stocks/{ticker}/technical-signals` | 10 min | Tier 1 indicator stack (see below) |
| `POST /api/agent/query` | none | TEARIA conversational chat — Gemini Flash direct, per-session history |

### Data Endpoints
- `GET /api/stocks/{ticker}/fundamentals`
- `GET /api/stocks/{ticker}/analyst-ratings`
- `GET /api/stocks/{ticker}/volume-analysis`
- `GET /api/stocks/{ticker}/quote`
- `GET /api/stocks/{ticker}/chart`
- `GET /api/stocks/{ticker}/news`

## Technical Signals — Tier 1 Indicators (`app/services/technical_signals.py`)

### Moving Averages / Trend
- SMA 20, 50, 200
- EMA 9, 21, 50
- **VWAP (20-day)** — volume-weighted average price over trailing 20 days

### Oscillators / Momentum
- RSI (14) — daily
- **RSI (14) — weekly** (resampled to weekly bars)
- MACD (12, 26, 9)
- Stochastic (14, 3, 3)
- Williams %R (14)
- **Ichimoku Cloud** (9, 26, 52) — manual rolling high/low; Tenkan/Kijun/Senkou A & B
- **ROC 10D** and **ROC 20D** — Rate of Change via `df.ta.roc`

### Volume
- OBV
- Relative Volume
- **Acc/Distribution** — via `df.ta.ad`

### Volatility
- Bollinger Bands (20, 2)
- ATR (14)

### Trend Strength
- ADX (14)
- **Relative Strength vs S&P 500** — 1M / 3M / 6M return differential vs SPY

### Composite Score
All above signals included in buy/sell/neutral counts for overall summary gauge.

## News Analysis — `_build_news_analysis()` (`app/routers/stocks.py`)

Parallel fetch via `asyncio.gather(return_exceptions=True)`:
1. **Yahoo Finance** — up to 20 articles (primary; thumbnails preserved)
2. **Finnhub** `/company-news` — 14-day window, sentiment score from `/news-sentiment`
3. **StockTwits** — bullish %, watchlist count (unreliable; gracefully falls back)

Merge/dedup on URL; Yahoo articles first (thumbnails), Finnhub fills summaries.
Synthesis: direct Vertex AI `GenerativeModel("gemini-2.0-flash-001")` call (~2-5s) for catalysts / risks / keyEvents / recommendation / summary from top 15 headlines.

Response shape:
```json
{
  "ticker", "overallSentiment", "socialSentiment", "newsSentiment",
  "catalysts", "risks", "keyEvents", "articles", "recommendation",
  "summary", "asOf", "finnhubScore"
}
```

## Rich Fundamental Analysis — `_build_rich_fundamental()` (`app/routers/stocks.py`)

Direct build (no agent, ~5s) from:
- `get_fundamentals()` → valuation, profitability, health
- `get_analyst_ratings()` → analyst consensus
- `get_earnings_history()` → earnings rows
- `get_dividends()` → dividend rows
- `yfinance` → growth metrics

Sections: valuation · profitability · health · growth · earnings · dividends · verdict
Agent path kept as fallback when direct build fails.

## TEARIA Chat — `app/routers/agent.py`

- Model: `gemini-2.0-flash-001` (direct Vertex AI call, NOT agent engine)
- `_SYSTEM_PROMPT`: TEARIA persona — conversational trading assistant
- Per-session history: `_sessions: defaultdict(list)`, max 40 messages (`_SESSION_MAX_MESSAGES`)
- Session key: `session_id` from request body (UUID, per widget mount)
- **Do NOT route TEARIA through ADK agent engine** — it returns structured JSON, not conversational text

## Key Files

- `app/routers/stocks.py` — analysis orchestration, normalization, all caches
- `app/routers/agent.py` — TEARIA Gemini Flash chat endpoint
- `app/services/technical_signals.py` — Tier 1 indicator computation
- `app/services/fundamentals.py` — fundamentals, analyst ratings, earnings, volume
- `app/mcp_server.py` — MCP tools for trade-agent

## Deployment
Cloud Run service: `trade-backend`.
`TRADEVIEW_AGENT_RESOURCE_ID` controls which Vertex agent revision is active.
Update in both `trade-backend/.env` AND `cloudbuild.yaml` after agent redeployment.
