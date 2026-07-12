"""
Extract endpoint — POST /extract
Extracts the selected page range as a new PDF.
Response: HTML fragment added to the left panel via HTMX.
"""
import logging
# pyrefly: ignore [missing-import]
import pymupdf
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException, Request, Depends
# pyrefly: ignore [missing-import]
from pydantic import BaseModel

from backend.services import pdf_service, auth_service
from backend.templating import templates
from backend.rate_limit import limiter

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
@limiter.limit("30/minute")
def extract_pages(req: ExtractRequest, request: Request, current_user: dict = Depends(auth_service.get_current_user)):
    """Extracts selected pages, returns the left panel HTML fragment."""
    if not req.pages:
        raise HTTPException(status_code=400, detail="No pages selected.")

    user_dir = pdf_service.user_storage_dir(current_user["email"])
    try:
        pages_dicts = [p.model_dump() for p in req.pages]
        file_id, filename, actual_count = pdf_service.extract_pages(pages_dicts, user_dir, custom_name=req.custom_name)
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
            "custom_name": req.custom_name or "",
        },
    )

class RenameRequest(BaseModel):
    custom_name: str

@router.post("/rename/{file_id}")
@limiter.limit("30/minute")
def rename_pdf(file_id: str, req: RenameRequest, request: Request, current_user: dict = Depends(auth_service.get_current_user)):
    """Renames an extracted PDF metadata and returns the updated HTML fragment."""
    user_dir = pdf_service.user_storage_dir(current_user["email"])
    try:
        new_path, new_filename, metadata = pdf_service.rename_output(file_id, req.custom_name, user_dir)
        label = metadata.get("label", "PDF")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found.")
    except Exception as e:
        logger.exception(f"Rename failed for file_id={file_id}")
        raise HTTPException(status_code=500, detail="Rename failed.")

    doc = pymupdf.open(str(new_path))
    page_count = len(doc)
    doc.close()

    return templates.TemplateResponse(
        request=request,
        name="partials/pdf_item.html",
        context={
            "request": request,
            "file_id": file_id,
            "filename": new_filename,
            "label": label,
            "page_count": page_count,
            "custom_name": metadata.get("custom_name", ""),
        },
    )

class UpdateRequest(BaseModel):
    pages: list[PageExtract]

@router.post("/update/{file_id}")
@limiter.limit("30/minute")
def update_pdf(file_id: str, req: UpdateRequest, request: Request, current_user: dict = Depends(auth_service.get_current_user)):
    """Persists Batch Mode grid edits (rotate/reorder) to file_id in place."""
    if not req.pages:
        raise HTTPException(status_code=400, detail="No pages to update.")

    user_dir = pdf_service.user_storage_dir(current_user["email"])
    try:
        pages_dicts = [p.model_dump() for p in req.pages]
        pdf_service.update_pages(file_id, pages_dicts, user_dir)
        _, filename, page_count = pdf_service.get_pdf_info(file_id, user_dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception(f"Update failed for file_id={file_id}")
        raise HTTPException(status_code=500, detail="Update failed.")

    label = f"{page_count} Pages" if page_count > 1 else "Page 1"
    custom_name = pdf_service.get_metadata(file_id, user_dir).get("custom_name", "")

    return templates.TemplateResponse(
        request=request,
        name="partials/pdf_item.html",
        context={
            "request": request,
            "file_id": file_id,
            "filename": filename,
            "label": label,
            "page_count": page_count,
            "custom_name": custom_name,
        },
    )
