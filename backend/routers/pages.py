"""
PDF source endpoint — GET /pdf-source/{pdf_id}
Serves the raw PDF bytes so the browser can render pages itself (pdf.js)
instead of the server rendering per-page PNGs.
"""
import logging
import os
from fastapi import APIRouter, HTTPException, Request, Depends, Response
from fastapi.responses import FileResponse, StreamingResponse
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

    # Batch Mode Update can rewrite this same pdf_id's bytes in place — no-cache
    # forces revalidation instead of the browser/pdf.js silently reusing stale content.
    # We support HTTP Range requests (206 Partial Content) so pdf.js can fetch
    # large documents in chunks. This drastically reduces initial wait time for big PDFs.

    file_size = os.path.getsize(str(path))
    range_header = request.headers.get("range")

    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache",
    }

    if not range_header:
        # Standard FileResponse if no range requested.
        return FileResponse(path=str(path), media_type="application/pdf", headers=headers)

    try:
        # Parse "bytes=start-end"
        range_match = range_header.replace("bytes=", "").split("-")
        start = int(range_match[0])
        end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else file_size - 1
        end = min(end, file_size - 1)

        if start > end or start >= file_size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

        chunk_size = end - start + 1
        headers["Content-Length"] = str(chunk_size)
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Type"] = "application/pdf"

        def ranged_file_iterator(start_pos, size):
            with open(str(path), "rb") as f:
                f.seek(start_pos)
                remaining = size
                while remaining > 0:
                    chunk = f.read(min(1024 * 64, remaining))
                    if not chunk:
                        break
                    yield chunk
                    remaining -= len(chunk)

        return StreamingResponse(
            ranged_file_iterator(start, chunk_size),
            status_code=206,
            headers=headers
        )
    except Exception as e:
        logger.warning(f"Range request parsing failed for {pdf_id}: {e}")
        return FileResponse(path=str(path), media_type="application/pdf", headers=headers)
