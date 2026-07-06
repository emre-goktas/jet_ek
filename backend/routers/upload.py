# pyrefly: ignore [missing-import]
from fastapi import APIRouter, File, UploadFile, HTTPException, Request
# pyrefly: ignore [missing-import]
from fastapi.responses import HTMLResponse
from pathlib import Path
import json
import os
import tempfile
import logging

from backend.services import pdf_service
from backend.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload")
async def upload_pdf(request: Request, file: UploadFile = File(...)):
    """Uploads a PDF or Image file, returns the viewer HTML fragment."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="File could not be uploaded.")

    fd, temp_path = tempfile.mkstemp()
    temp_pdf_path = None
    try:
        with os.fdopen(fd, 'wb') as out_file:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                out_file.write(chunk)

        # Still verify if it's completely empty
        if os.path.getsize(temp_path) < 4:
            raise HTTPException(status_code=400, detail="Empty file uploaded.")

        from backend.services.preprocessor import preprocess_to_pdf
        pdf_path, final_filename = preprocess_to_pdf(Path(temp_path), file.filename)
        temp_pdf_path = str(pdf_path)

        pdf_id, page_count = pdf_service.save_upload(pdf_path, final_filename)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Upload failed")
        raise HTTPException(status_code=500, detail="PDF could not be saved.")
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

        if temp_pdf_path and temp_pdf_path != temp_path and os.path.exists(temp_pdf_path):
            try:
                os.remove(temp_pdf_path)
            except Exception:
                pass

    response = templates.TemplateResponse(
        request=request,
        name="partials/viewer.html",
        context={
            "request": request,
            "pdf_id": pdf_id,
            "page_count": page_count,
            "filename": final_filename,
        },
    )
    # Trigger viewerReady event for HTMX
    response.headers["HX-Trigger"] = json.dumps({
        "viewerReady": {
            "pdfId": pdf_id,
            "pageCount": page_count
        }
    })
    return response

@router.get("/batch_viewer/{file_id}")
async def get_batch_viewer(request: Request, file_id: str):
    """Returns the viewer HTML fragment for an existing file_id (batch or original)."""
    try:
        _, filename, page_count = pdf_service.get_pdf_info(file_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail="File not found.")

    response = templates.TemplateResponse(
        request=request,
        name="partials/viewer.html",
        context={
            "request": request,
            "pdf_id": file_id,
            "page_count": page_count,
            "filename": filename,
        },
    )
    # The frontend manually handles HX-Trigger for this endpoint,
    # but we can send it anyway in case it's called via HTMX in the future.
    response.headers["HX-Trigger"] = json.dumps({
        "viewerReady": {
            "pdfId": file_id,
            "pageCount": page_count
        }
    })
    return response
