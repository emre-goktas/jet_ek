"""
Extract endpoint — POST /extract
Extracts the selected page range as a new PDF.
Response: HTML fragment added to the left panel via HTMX.
"""
import logging
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException, Request
# pyrefly: ignore [missing-import]
from pydantic import BaseModel

from backend.services import pdf_service
from backend.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


ALLOWED_OCR_LANGS = {"tur", "eng", "tur+eng"}

class PageExtract(BaseModel):
    pdf_id: str
    page_idx: int
    rotation: int = 0

class ExtractRequest(BaseModel):
    pages: list[PageExtract]
    custom_name: str | None = None


@router.post("/extract")
def extract_pages(req: ExtractRequest, request: Request):
    """Extracts selected pages, returns the left panel HTML fragment."""
    if not req.pages:
        raise HTTPException(status_code=400, detail="No pages selected.")

    try:
        pages_dicts = [p.model_dump() for p in req.pages]
        file_id, filename, actual_count = pdf_service.extract_pages(pages_dicts, custom_name=req.custom_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Source PDF not found.")
    except Exception as e:
        logger.exception(f"PDF extraction failed for request with {len(req.pages)} pages")
        raise HTTPException(status_code=500, detail="PDF extraction failed.")

    label = f"{actual_count} Pages" if actual_count > 1 else f"Page {req.pages[0].page_idx + 1}"

    return templates.TemplateResponse(
        request=request,
        name="partials/pdf_item.html",
        context={
            "request": request,
            "file_id": file_id,
            "filename": filename,
            "label": label,
            "page_count": actual_count,
        },
    )

class RenameRequest(BaseModel):
    custom_name: str

@router.post("/rename/{file_id}")
def rename_pdf(file_id: str, req: RenameRequest, request: Request):
    """Renames an extracted PDF metadata and returns the updated HTML fragment."""
    try:
        new_path, new_filename, metadata = pdf_service.rename_output(file_id, req.custom_name)
        label = metadata.get("label", "PDF")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found.")
    except Exception as e:
        logger.exception(f"Rename failed for file_id={file_id}")
        raise HTTPException(status_code=500, detail="Rename failed.")

    return templates.TemplateResponse(
        request=request,
        name="partials/pdf_item.html",
        context={
            "request": request,
            "file_id": file_id,
            "filename": new_filename,
            "label": label,
        },
    )
