"""TradeElite backend — FastAPI app with MCP server mounted at /mcp."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.mcp_server import mcp
from app.routers import agent, options, portfolios, settings as settings_router, stocks, users

app = FastAPI(
    title="TradeElite Backend",
    description="REST API + MCP server for TradeView web app and trading agents",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API routes
app.include_router(stocks.router)
app.include_router(portfolios.router)
app.include_router(options.router)
app.include_router(settings_router.router)
app.include_router(agent.router)
app.include_router(users.router)

# MCP server — trade-agents connects to /mcp/sse
app.mount("/mcp", mcp.sse_app())


@app.get("/health")
async def health():
    return {"status": "ok", "service": "trade-backend"}
