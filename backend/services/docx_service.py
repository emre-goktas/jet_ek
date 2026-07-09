import json
from pathlib import Path

TEMPLATES_FILE = Path(__file__).parent.parent / "data" / "templates.json"

_templates_cache: list[dict] | None = None
_templates_mtime: float | None = None

def get_templates() -> list[dict]:
    """Returns the parsed templates.json, cached in memory and refreshed
    automatically whenever the file's mtime changes (so manual edits are picked
    up without a server restart, but repeated calls skip the disk read)."""
    global _templates_cache, _templates_mtime

    if not TEMPLATES_FILE.exists():
        return []

    mtime = TEMPLATES_FILE.stat().st_mtime
    if _templates_cache is not None and mtime == _templates_mtime:
        return _templates_cache

    with open(TEMPLATES_FILE, "r", encoding="utf-8") as f:
        _templates_cache = json.load(f)
    _templates_mtime = mtime
    return _templates_cache
