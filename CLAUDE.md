# CLAUDE.md — trade-backend

## Summary
FastAPI backend for TradeElite. Serves REST endpoints for web and MCP tools for agents.

## Key AI Endpoints

- `GET /api/stocks/{ticker}/ai-analysis`
  - Full orchestrated stock analysis.
  - 10-minute in-memory cache.
  - Session-state + streamed-text extraction fallback.

- `GET /api/stocks/{ticker}/fundamental-analysis`
  - Dedicated deep fundamental path.
  - 10-minute in-memory cache.
  - Normalizes to frontend `FundamentalAnalysis` schema.
  - Includes enhanced-schema backfill (`attributes`, `aiAnalysis`, `sources`) for legacy upstream outputs.

## Key File
- `app/routers/stocks.py` — analysis orchestration, normalization, caches, and fallback enrichment.

## Deployment
Cloud Run service: `trade-backend`.
`TRADEVIEW_AGENT_RESOURCE_ID` controls which Vertex agent revision is active.
