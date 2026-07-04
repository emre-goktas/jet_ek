from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
import logging
from fastapi.templating import Jinja2Templates
from pathlib import Path

from backend.services.ai_service import jet_rename_pdf

router = APIRouter()
logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "frontend" / "templates"))

@router.post("/jet-rename/{file_id}", response_class=HTMLResponse)
def jet_rename(file_id: str, request: Request):
    """
    Renames the given PDF file_id using Gemini AI based on its first page.
    Returns the updated HTML for the left panel item.
    """
    try:
        new_filename, label, page_count = jet_rename_pdf(file_id)
        context = {
            "request": request,
            "file_id": file_id,
            "filename": new_filename,
            "label": label,
            "page_count": page_count,
        }
        return templates.TemplateResponse(request=request, name="partials/pdf_item.html", context=context)
    except Exception as e:
        logger.error(f"Error in jet_rename for {file_id}: {e}")
        # Return a 400 error so frontend can handle it
        raise HTTPException(status_code=400, detail=str(e))
