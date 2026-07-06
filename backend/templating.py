"""
Shared Jinja2Templates instance for all routers and main.py.
"""
from pathlib import Path
# pyrefly: ignore [missing-import]
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR.parent / "frontend" / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
