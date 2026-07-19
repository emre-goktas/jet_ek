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


def _int_or_none(v) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


@router.post("/api/perf-log")
@limiter.limit("120/minute")
async def log_performance(request: Request):
    """Body: {operation, page_count?, batch_count?, file_size_bytes?,
    duration_ms?, success?}. Same fire-and-forget contract as /api/events —
    see frontend/static/js/document-builder.js's logPerformance()."""
    user = auth_service.get_current_user(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    operation = str(body.get("operation", "")).strip()[:100]
    if operation:
        db_service.log_performance_safe(
            user["email"],
            operation,
            page_count=_int_or_none(body.get("page_count")),
            batch_count=_int_or_none(body.get("batch_count")),
            file_size_bytes=_int_or_none(body.get("file_size_bytes")),
            duration_ms=_int_or_none(body.get("duration_ms")),
            success=bool(body.get("success", True)),
        )
    return {"status": "ok"}
