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
