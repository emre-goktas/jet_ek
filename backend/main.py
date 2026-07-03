"""
FastAPI application — PDF Regulator
"""
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
import asyncio
import time
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import logging

from backend.routers import upload, pages, extract, download, templates as templates_router, ai
from backend.services.pdf_service import STORAGE_DIR, is_file_locked

BASE_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"
STATIC_DIR = BASE_DIR / "frontend" / "static"


async def cleanup_old_files():
    """Cleans up storage files older than 1 hour, running every hour."""
    import itertools
    while True:
        try:
            now = time.time()
            for p in itertools.chain(STORAGE_DIR.glob("*.pdf"), STORAGE_DIR.glob("*.png"), STORAGE_DIR.glob("*.json")):
                try:
                    if now - p.stat().st_mtime > 3600:
                        if not is_file_locked(p):
                            p.unlink(missing_ok=True)
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

# Static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Register routers
app.include_router(upload.router)
app.include_router(pages.router)
app.include_router(extract.router)
app.include_router(download.router)
app.include_router(templates_router.router)
app.include_router(ai.router, prefix="/ai")

# Jinja2 template engine
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/")
async def index(request: Request):
    """Home page."""
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request})
