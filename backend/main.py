"""
FastAPI application — PDF Regulator
"""
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import itertools
import time
import logging

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.routers import upload, pages, extract, download, templates as templates_router, ai
from backend.services.pdf_service import STORAGE_DIR, is_file_locked, secure_delete
from backend.templating import templates
from backend.rate_limit import limiter

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "frontend" / "static"

logger = logging.getLogger(__name__)


def _sweep_storage(max_age_seconds: float | None):
    """Deletes unlocked files from STORAGE_DIR. With max_age_seconds set, only
    files older than that are touched (the hourly safety net); with None,
    everything unlocked is wiped regardless of age (the nightly full sweep —
    most output files should already be gone via /cleanup by then, this is
    the backstop for abandoned/incomplete sessions)."""
    now = time.time()
    for p in itertools.chain(STORAGE_DIR.glob("*.pdf"), STORAGE_DIR.glob("*.json")):
        try:
            if max_age_seconds is None or now - p.stat().st_mtime > max_age_seconds:
                if not is_file_locked(p):
                    secure_delete(p)
        except Exception as e:
            logging.warning(f"Cleanup failed for {p}: {e}")


async def cleanup_old_files():
    """Safety net: every hour, deletes unlocked files older than 1 hour."""
    while True:
        try:
            _sweep_storage(max_age_seconds=3600)
        except Exception as e:
            logging.error(f"Hourly cleanup loop error: {e}")
        await asyncio.sleep(3600)


async def nightly_full_cleanup():
    """Once a day around 03:00 local time, wipes every unlocked file in
    storage regardless of age — the harder guarantee behind the hourly
    safety net above, so nothing from a finished session lingers overnight."""
    while True:
        now = datetime.now()
        next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
        try:
            _sweep_storage(max_age_seconds=None)
        except Exception as e:
            logging.error(f"Nightly cleanup loop error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_task = asyncio.create_task(cleanup_old_files())
    nightly_task = asyncio.create_task(nightly_full_cleanup())
    yield
    cleanup_task.cancel()
    nightly_task.cancel()

app = FastAPI(
    title="PDF Regulator",
    description="Professional PDF tool to extract, rotate, and optimize pages with advanced text recognition and cleanup.",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Backstop for anything that slips past route-level error handling: logs the
    real exception server-side and returns a generic message to the client. HTTPException
    (used throughout the routers) is handled by FastAPI's own more specific handler and
    never reaches this one."""
    logger.exception(f"Unhandled exception for {request.method} {request.url.path}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


# Static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Register routers
app.include_router(upload.router)
app.include_router(pages.router)
app.include_router(extract.router)
app.include_router(download.router)
app.include_router(templates_router.router)
app.include_router(ai.router, prefix="/ai")


@app.get("/")
async def index(request: Request):
    """Home page."""
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request})
