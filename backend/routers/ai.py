from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import logging

from backend.services.ai_service import jet_rename_pdf, jet_rename_pdf_batch
from backend.templating import templates
from backend.rate_limit import limiter

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/jet-rename/{file_id}", response_class=HTMLResponse)
@limiter.limit("10/minute")
def jet_rename(file_id: str, request: Request):
    """
    Renames the given PDF file_id using Gemini AI based on its first page.
    Returns the updated HTML for the left panel item.
    """
    try:
        new_filename, label, page_count, custom_name = jet_rename_pdf(file_id)
        context = {
            "request": request,
            "file_id": file_id,
            "filename": new_filename,
            "label": label,
            "page_count": page_count,
            "custom_name": custom_name,
        }
        return templates.TemplateResponse(request=request, name="partials/pdf_item.html", context=context)
    except Exception as e:
        logger.exception(f"Error in jet_rename for {file_id}")
        # Return a 400 error so frontend can handle it
        raise HTTPException(status_code=400, detail="AI rename failed.")

class BatchRenameRequest(BaseModel):
    file_ids: list[str]

@router.post("/jet-rename-batch", response_class=JSONResponse)
@limiter.limit("5/minute")
def jet_rename_batch(data: BatchRenameRequest, request: Request):
    """
    Renames multiple PDF files using Gemini AI in a single batch.
    Returns a JSON mapping of file_id -> rendered HTML snippet.
    """
    try:
        results = jet_rename_pdf_batch(data.file_ids)
        response_htmls = {}
        for file_id, info in results.items():
            context = {
                "request": request,
                "file_id": file_id,
                "filename": info["filename"],
                "label": info["label"],
                "page_count": info["page_count"],
                "custom_name": info.get("custom_name", ""),
            }
            # Render template to string using Starlette's TemplateResponse body
            template_response = templates.TemplateResponse(request=request, name="partials/pdf_item.html", context=context)
            response_htmls[file_id] = template_response.body.decode('utf-8')

        return JSONResponse(content=response_htmls)
    except Exception as e:
        logger.exception("Error in jet_rename_batch")
        raise HTTPException(status_code=400, detail="AI batch rename failed.")
