"""
PDF source endpoint — GET /pdf-source/{pdf_id}
Serves the raw PDF bytes so the browser can render pages itself (pdf.js)
instead of the server rendering per-page PNGs.
"""
import logging
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import FileResponse
from backend.services import pdf_service, auth_service
from backend.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/pdf-source/{pdf_id}")
@limiter.limit("60/minute")
def get_pdf_source(request: Request, pdf_id: str, current_user: dict = Depends(auth_service.get_current_user)):
    """Returns the raw PDF file for pdf_id (original upload or batch output)."""
    user_dir = pdf_service.user_storage_dir(current_user["email"])
    try:
        path, _, _ = pdf_service.get_pdf_info(pdf_id, user_dir)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="PDF not found.")
    except Exception:
        logger.exception(f"Failed to resolve PDF source for pdf_id={pdf_id}")
        raise HTTPException(status_code=500, detail="Could not load PDF.")

    # Batch Mode Update can rewrite this same pdf_id's bytes in place. We need
    # to prevent caching so the browser re-fetches updated versions.
    # However, `no-cache` tells Cloudflare to cache but revalidate. When Cloudflare
    # caches, it ignores `Range` requests from pdf.js and fetches the entire file
    # from the origin server, causing severe delays for large PDFs.
    # By using `no-store, max-age=0`, we completely bypass Cloudflare caching,
    # allowing native Range requests (which FastAPI's FileResponse supports out of the box)
    # to pass straight through to the backend, enabling fast chunked streaming.
    return FileResponse(path=str(path), media_type="application/pdf", headers={"Cache-Control": "no-store, max-age=0"})
