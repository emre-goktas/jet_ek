"""
PDF source endpoint — GET /pdf-source/{pdf_id}
Serves the raw PDF bytes so the browser can render pages itself (pdf.js)
instead of the server rendering per-page PNGs.
"""
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from backend.services import pdf_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/pdf-source/{pdf_id}")
def get_pdf_source(pdf_id: str):
    """Returns the raw PDF file for pdf_id (original upload or batch output)."""
    try:
        path, _, _ = pdf_service.get_pdf_info(pdf_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="PDF not found.")
    except Exception:
        logger.exception(f"Failed to resolve PDF source for pdf_id={pdf_id}")
        raise HTTPException(status_code=500, detail="Could not load PDF.")

    # Batch Mode Update can rewrite this same pdf_id's bytes in place — no-cache
    # forces revalidation instead of the browser/pdf.js silently reusing stale content.
    return FileResponse(path=str(path), media_type="application/pdf", headers={"Cache-Control": "no-cache"})
