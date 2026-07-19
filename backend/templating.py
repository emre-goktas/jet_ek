"""
Shared Jinja2Templates instance for all routers and main.py.
"""
import time
from pathlib import Path
# pyrefly: ignore [missing-import]
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR.parent / "frontend" / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Cache-busting token for static/js and static/css URLs (?v=...). Set once
# per process start rather than hand-bumped per file — this app is a single
# process per container (see Dockerfile) and gets a fresh one on every
# deploy, so every redeploy automatically invalidates any intermediary cache
# (browser, Cloudflare edge) without anyone needing to remember to edit a
# version number in index.html.
templates.env.globals["asset_v"] = str(int(time.time()))
