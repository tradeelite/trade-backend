"""TradeElite backend — FastAPI app with MCP server mounted at /mcp."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.database import engine
from app.db.models import Base
from app.mcp_server import mcp
from app.routers import agent, options, portfolios, settings as settings_router, stocks


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (use Alembic for production migrations)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="TradeElite Backend",
    description="REST API + MCP server for TradeView web app and trading agents",
    version="0.1.0",
    lifespan=lifespan,
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

# MCP server — trade-agents connects to /mcp/sse
app.mount("/mcp", mcp.sse_app())


@app.get("/health")
async def health():
    return {"status": "ok", "service": "trade-backend"}
