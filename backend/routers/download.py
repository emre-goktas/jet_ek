"""
Download endpoint — GET /download/{file_id}
Serves the generated PDF file as a download.

ZIP packaging and the Word index list used to be built here too, but that
generation now happens client-side (frontend/static/js/document-builder.js),
using /pdf-source/{id} for the PDF bytes and /api/templates/* for the
template config + file. This router only serves single files.
"""
import logging
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException, Request, Depends
# pyrefly: ignore [missing-import]
from fastapi.responses import FileResponse
# pyrefly: ignore [missing-import]
from pydantic import BaseModel

from backend.services import pdf_service, auth_service
from backend.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/download/{file_id}")
@limiter.limit("60/minute")
def download_pdf(file_id: str, request: Request, ek_no: int = None, current_user: dict = Depends(auth_service.get_current_user)):
    """Downloads the PDF file belonging to the specified file_id."""
    user_dir = pdf_service.user_storage_dir(current_user["email"])
    try:
        path, filename, _ = pdf_service.get_pdf_info(file_id, user_dir)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="File not found.")

    if ek_no is not None:
        filename = f"{ek_no:02d}_{filename}"

    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=filename,
    )


class CleanupRequest(BaseModel):
    file_ids: list[str]


@router.post("/cleanup")
@limiter.limit("60/minute")
def cleanup_files(req: CleanupRequest, request: Request, current_user: dict = Depends(auth_service.get_current_user)):
    """Signals that these output files have been handed to the browser to
    save — the ZIP/Word index are now built client-side, so the backend has
    no other way to learn "download triggered." Does NOT delete anything
    itself: a client only knows it told the browser to save the file, never
    that the save actually finished (slow connection, a stalled tab — there's
    no completion event for this), so an immediate delete here would have no
    safety margin for that gap. Instead this just marks the files as freshly
    touched (see pdf_service.mark_delivered) so the regular 15-minute sweep
    is what actually removes them, on its own schedule — a real recovery
    window instead of an instant, irreversible delete. Only ever touches the
    specific file_ids the caller says it already has, and only within that
    caller's own storage directory — a file_id belonging to another user
    simply won't resolve, so it's silently skipped exactly like a missing/
    invalid id. Best-effort: nothing here needs a retry."""
    user_dir = pdf_service.user_storage_dir(current_user["email"])
    for file_id in req.file_ids:
        pdf_service.mark_delivered(file_id, user_dir)
    return {"status": "ok"}
