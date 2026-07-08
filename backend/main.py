"""
FastAPI application — PDF Regulator
"""
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import asyncio
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


async def cleanup_old_files():
    """Cleans up storage files older than 1 hour, running every hour."""
    import itertools
    while True:
        try:
            now = time.time()
            for p in itertools.chain(STORAGE_DIR.glob("*.pdf"), STORAGE_DIR.glob("*.json")):
                try:
                    if now - p.stat().st_mtime > 3600:
                        if not is_file_locked(p):
                            secure_delete(p)
                except Exception as e:
                    logging.warning(f"Cleanup failed for {p}: {e}")
        except Exception as e:
            logging.error(f"Global cleanup loop error: {e}")
        await asyncio.sleep(3600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_task = asyncio.create_task(cleanup_old_files())
    yield
    cleanup_task.cancel()

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
