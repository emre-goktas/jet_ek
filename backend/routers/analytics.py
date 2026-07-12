"""
Lightweight usage analytics — POST /api/events logs one row per action
(upload/extract/download/ai_rename/...) so we can see which features get
used and how often, without designing a bespoke table per question up front.
"""
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Request

from backend.services import auth_service, db_service
from backend.rate_limit import limiter

router = APIRouter()


@router.post("/api/events")
@limiter.limit("120/minute")
async def log_event(request: Request):
    """Body: {"event_type": str, "metadata": {...}}. Fire-and-forget from the
    client's perspective — always returns 200 even if logging itself fails,
    since a broken analytics call should never surface as a user-facing error."""
    user = auth_service.get_current_user(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    event_type = str(body.get("event_type", "")).strip()[:100]
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    if event_type:
        db_service.log_event_safe(user["email"], event_type, metadata)
    return {"status": "ok"}
