# CLAUDE.md — trade-backend

## Summary
Python FastAPI backend for TradeElite. Provides a REST API for `trade-web` and an MCP server (`/mcp/sse`) for `trade-agents` (Google ADK). Replaces all Next.js API routes from the original monolith.

## Stack
- **FastAPI** + **uvicorn** — REST API + ASGI server
- **FastMCP** (`mcp` SDK) — MCP server at `/mcp/sse`
- **SQLAlchemy async** + **asyncpg** — Cloud SQL (PostgreSQL)
- **yfinance** — Yahoo Finance data
- **httpx** — StockTwits + Twelve Data REST
- **anthropic** — Claude Vision OCR
- **alembic** — DB migrations
- **uv** — Package manager

## Key Files
| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app, mounts MCP, includes all routers |
| `app/mcp_server.py` | 11 MCP tools for trade-agents |
| `app/routers/stocks.py` | Stock search, quote, chart, indicators, news, sentiment |
| `app/routers/portfolios.py` | Portfolio + holdings CRUD |
| `app/routers/options.py` | Options CRUD + OCR + suggestions |
| `app/routers/settings.py` | App settings key-value store |
| `app/routers/agent.py` | Proxy to Vertex AI Agent Engine |
| `app/services/yahoo_finance.py` | yfinance wrapper |
| `app/services/indicators.py` | SMA, EMA, RSI, MACD, Bollinger Bands |
| `app/services/suggestions.py` | Options suggestion rules |
| `app/services/ocr.py` | Claude Vision trade extraction |
| `app/db/models.py` | SQLAlchemy ORM models |
| `app/db/schemas.py` | Pydantic request/response schemas |
| `app/core/config.py` | Settings from env vars |

## Commands
```bash
uv sync                          # Install dependencies
uv run uvicorn app.main:app --reload --port 8000   # Dev server
uv run pytest tests/             # Tests
uv run alembic upgrade head      # Run DB migrations
```

## Environment Variables
See `.env.example`. Required: `DATABASE_URL`, `ANTHROPIC_API_KEY`. Optional: `TWELVE_DATA_API_KEY`, `TRADEVIEW_AGENT_RESOURCE_ID`.

## MCP Endpoint
`GET/SSE http://localhost:8000/mcp/sse` — trade-agents connects here via MCPToolset.

## Deployment
Cloud Run + Cloud SQL (PostgreSQL). Set `DATABASE_URL` to Cloud SQL connection string.
