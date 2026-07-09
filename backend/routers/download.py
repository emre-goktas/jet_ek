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
from fastapi import APIRouter, HTTPException
# pyrefly: ignore [missing-import]
from fastapi.responses import FileResponse
# pyrefly: ignore [missing-import]
from pydantic import BaseModel

from backend.services import pdf_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/download/{file_id}")
def download_pdf(file_id: str, ek_no: int = None):
    """Downloads the PDF file belonging to the specified file_id."""
    try:
        path = pdf_service.get_output_path(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found.")

    filename = path.name.split("_", 1)[1] if "_" in path.name else path.name

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
def cleanup_files(req: CleanupRequest):
    """Deletes output files right after their content has been delivered to
    the client — the ZIP/Word index are now built client-side, so the
    backend no longer sees "download finished" on its own. Only ever
    touches the specific file_ids the caller says it already has; never
    reaches for a source upload on its own. Best-effort: missing/invalid/
    locked ids are silently skipped, nothing here needs a retry."""
    for file_id in req.file_ids:
        pdf_service.delete_output(file_id)
    return {"status": "ok"}
