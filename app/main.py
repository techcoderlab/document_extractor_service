# ─────────────────────────────────────────────────────
# Module   : app/main.py (UPDATED)
# Layer    : Infrastructure / Bootstrap
# Pillar   : P0 (Bootstrap), P6 (Resilience)
# ─────────────────────────────────────────────────────

import asyncio
import sys
import structlog
from fastapi import FastAPI

from app.core.config import settings
from app.core.middleware import setup_middlewares
from app.core.http import close_client

# This import "plugs in" the Sheets implementation
import app.infrastructure.sheets_client
from app.infrastructure.discord_bot import bot
# Import the newly created API Router
from app.presentation.api import api_router

logger = structlog.get_logger("app")

app = FastAPI(
    title="Discord Document Extraction API",
    version="1.0.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
)

setup_middlewares(app)

# Register the batch processing routes
app.include_router(api_router)

@app.on_event("startup")
async def startup_event() -> None:
    """
    Bootstraps the Discord bot alongside the FastAPI worker.
    """
    if not settings.DISCORD_BOT_TOKEN:
        logger.error("DISCORD_BOT_TOKEN is missing. Bot will not start.")
        sys.exit(1)
        
    logger.info("Starting Discord Bot task...")
    asyncio.create_task(bot.start(settings.DISCORD_BOT_TOKEN))

@app.on_event("shutdown")
async def shutdown_event() -> None:
    """
    P6 Resilience: Ensures the custom HTTP client closes its connection 
    pools gracefully during application shutdown.
    """
    logger.info("Closing HTTP client connection pools...")
    await close_client()

@app.get("/health")
async def health_check() -> dict[str, str]:
    """Basic health probe for container orchestration."""
    return {"status": "healthy", "bot_connected": str(bot.is_ready())}