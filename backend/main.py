"""
FastAPI application — PDF Regulator
"""
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import itertools
import time
import logging
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
load_dotenv()  # explicit here (not just relying on ai_service's import-time side effect)
# so every module — auth_service included — can trust os.environ regardless of import order.

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.routers import upload, pages, extract, download, templates as templates_router, ai, auth, profile, analytics
from backend.services.pdf_service import STORAGE_DIR, forget_cached_path, is_file_locked, secure_delete
from backend.services import auth_service, db_service
from backend.templating import templates
from backend.rate_limit import limiter

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "frontend" / "static"

# Auth is mandatory — refuse to start rather than silently running with every
# route open. Checked at import time, before the app or any router is built.
_missing_env = auth_service.missing_env_vars()
if _missing_env:
    raise RuntimeError(
        "JETEK cannot start: missing required environment variable(s) "
        f"{', '.join(_missing_env)}. Set GOOGLE_CLIENT_ID and SESSION_SECRET_KEY "
        "in .env — authentication is mandatory. See .env.example."
    )

LOG_DIR = BASE_DIR / "backend" / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(LOG_DIR / "app.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"),
    ],
    force=True,  # wins even if uvicorn or another import already touched the root logger
)

logger = logging.getLogger(__name__)


def _sweep_storage(max_age_seconds: float | None):
    """Deletes unlocked files from STORAGE_DIR. Covers both layouts: legacy
    flat-root files (pre-per-user-storage leftovers, glob at the root) and
    the current per-user user_*/ subdirectories. With max_age_seconds set,
    only files older than that are touched; with None, every unlocked file is
    wiped regardless of age. Age is judged by mtime, which pdf_service._touch
    refreshes on every successful read/write of a file — so a small
    max_age_seconds is not just "don't bother with young files," it is the
    only thing standing between an in-flight download/render/AI-rename
    (none of which hold lock_file for their full duration, e.g. download.py's
    FileResponse streams after the handler returns) and secure_delete
    overwriting that same file's bytes out from under the open read."""
    now = time.time()
    patterns = itertools.chain(
        STORAGE_DIR.glob("*.pdf"), STORAGE_DIR.glob("*.json"),
        STORAGE_DIR.glob("user_*/*.pdf"), STORAGE_DIR.glob("user_*/*.json"),
    )
    for p in patterns:
        try:
            if max_age_seconds is None or now - p.stat().st_mtime > max_age_seconds:
                if not is_file_locked(p):
                    secure_delete(p)
                    forget_cached_path(p)
        except Exception as e:
            logging.warning(f"Cleanup failed for {p}: {e}")


async def cleanup_old_files():
    """Safety net: every 15 minutes, deletes unlocked files older than 15 minutes."""
    while True:
        try:
            _sweep_storage(max_age_seconds=900)
        except Exception as e:
            logging.error(f"Cleanup sweep loop error: {e}")
        await asyncio.sleep(900)


NIGHTLY_SWEEP_MIN_IDLE_SECONDS = 180  # anything touched more recently than this survives
# even the nightly sweep — comfortably longer than a single download/view/AI-rename could
# plausibly take, so it never races a real in-flight request (see _sweep_storage docstring).


async def nightly_full_cleanup():
    """Once a day around 03:00 local time, wipes every file in storage that's
    been idle for at least NIGHTLY_SWEEP_MIN_IDLE_SECONDS — the harder
    guarantee behind the hourly safety net above, so nothing from a finished
    session lingers overnight, without corrupting a document someone happens
    to be downloading or AI-renaming at that exact moment."""
    while True:
        now = datetime.now()
        next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
        try:
            _sweep_storage(max_age_seconds=NIGHTLY_SWEEP_MIN_IDLE_SECONDS)
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

# Every route that touches a user's document requires a session — auth is
# mandatory (see the startup check above), so this is never empty.
_auth_dependency = [Depends(auth_service.get_current_user)]

# Register routers
app.include_router(auth.router)
app.include_router(profile.router)  # mixed: /onboarding redirects itself, /api/* enforce auth internally
app.include_router(analytics.router)  # enforces auth internally (see analytics.py)
app.include_router(upload.router, dependencies=_auth_dependency)
app.include_router(pages.router, dependencies=_auth_dependency)
app.include_router(extract.router, dependencies=_auth_dependency)
app.include_router(download.router, dependencies=_auth_dependency)
app.include_router(templates_router.router)  # public: template metadata only, no user documents
app.include_router(ai.router, prefix="/ai", dependencies=_auth_dependency)


@app.get("/")
async def index(request: Request):
    """Home page — redirects to /login if there's no valid session, or to
    /onboarding if logged in but the profile (name/title/template choice)
    hasn't been filled in yet."""
    user = auth_service.get_current_user_optional(request)
    if user is None:
        return RedirectResponse(url="/login")
    if db_service.get_profile(user["email"]) is None:
        return RedirectResponse(url="/onboarding")
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request, "user": user})
