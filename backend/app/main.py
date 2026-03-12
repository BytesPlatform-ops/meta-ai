import asyncio
import logging
from contextlib import asynccontextmanager

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .core.config import get_settings
from .api.routes import oauth, campaigns, products, preferences, drafts, generate, audits, uploads, rules, pixels, strategy, audiences, manual_connect, optimize

logger = logging.getLogger(__name__)
settings = get_settings()

# ── 24-Hour Scheduler ─────────────────────────────────────────────────────────

OPTIMIZATION_INTERVAL_HOURS = 24
CONTENT_CHECK_INTERVAL_HOURS = 1

async def _optimization_loop():
    """Background loop that runs the HITL optimization engine every 24 hours."""
    from .services.optimization_engine import run_all_users_optimization
    # Wait 60s after startup before first run
    await asyncio.sleep(60)
    while True:
        try:
            logger.info("Scheduled HITL optimization starting...")
            result = await run_all_users_optimization()
            logger.info("Scheduled HITL optimization done: %s", result)
        except Exception:
            logger.exception("Scheduled HITL optimization failed")
        await asyncio.sleep(OPTIMIZATION_INTERVAL_HOURS * 3600)


async def _content_scheduler_loop():
    """Background loop that auto-generates drafts based on user posting_frequency."""
    from .services.content_scheduler import run_scheduled_generation
    # Wait 120s after startup before first run
    await asyncio.sleep(120)
    while True:
        try:
            logger.info("Content scheduler check starting...")
            result = await run_scheduled_generation()
            logger.info("Content scheduler done: %s", result)
        except Exception:
            logger.exception("Content scheduler failed")
        await asyncio.sleep(CONTENT_CHECK_INTERVAL_HOURS * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background schedulers on app startup, cancel on shutdown."""
    optimization_task = asyncio.create_task(_optimization_loop())
    content_task = asyncio.create_task(_content_scheduler_loop())
    logger.info("HITL optimization scheduler started (every %dh)", OPTIMIZATION_INTERVAL_HOURS)
    logger.info("Content scheduler started (checks every %dh)", CONTENT_CHECK_INTERVAL_HOURS)
    yield
    optimization_task.cancel()
    content_task.cancel()
    for t in (optimization_task, content_task):
        try:
            await t
        except asyncio.CancelledError:
            pass
    logger.info("Background schedulers stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.API_VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# CORS — allow Next.js dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file serving for uploaded images
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads/files", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# Routers
API_PREFIX = f"/api/{settings.API_VERSION}"
app.include_router(oauth.router, prefix=API_PREFIX)
app.include_router(campaigns.router, prefix=API_PREFIX)
app.include_router(products.router, prefix=API_PREFIX)
app.include_router(preferences.router, prefix=API_PREFIX)
app.include_router(drafts.router, prefix=API_PREFIX)
app.include_router(generate.router, prefix=API_PREFIX)
app.include_router(audits.router, prefix=API_PREFIX)
app.include_router(uploads.router, prefix=API_PREFIX)
app.include_router(rules.router, prefix=API_PREFIX)
app.include_router(pixels.router, prefix=API_PREFIX)
app.include_router(strategy.router, prefix=API_PREFIX)
app.include_router(audiences.router, prefix=API_PREFIX)
app.include_router(manual_connect.router, prefix=API_PREFIX)
app.include_router(optimize.router, prefix=API_PREFIX)


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.APP_NAME}
