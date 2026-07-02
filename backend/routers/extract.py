"""
Extract endpoint — POST /extract
Extracts the selected page range as a new PDF.
Response: HTML fragment added to the left panel via HTMX.
"""
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
# pyrefly: ignore [missing-import]
from fastapi.templating import Jinja2Templates
# pyrefly: ignore [missing-import]
from pydantic import BaseModel
from pathlib import Path
import uuid

from backend.services import pdf_service

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent.parent / "frontend" / "templates")
)


ALLOWED_OCR_LANGS = {"tur", "eng", "tur+eng"}

class PageExtract(BaseModel):
    pdf_id: str
    page_idx: int
    rotation: int = 0

class ExtractRequest(BaseModel):
    pages: list[PageExtract]
    custom_name: str | None = None
    file_counter: int | None = None


@router.post("/extract")
def extract_pages(req: ExtractRequest, background_tasks: BackgroundTasks, request: Request):
    """Extracts selected pages, returns the left panel HTML fragment."""
    if not req.pages:
        raise HTTPException(status_code=400, detail="No pages selected.")

    try:
        pages_dicts = [p.model_dump() for p in req.pages]
        file_id, filename = pdf_service.extract_pages(pages_dicts, custom_name=req.custom_name, file_counter=req.file_counter)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Source PDF not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF extraction error: {e}")

    count = len(req.pages)
    label = f"{count} Pages" if count > 1 else f"Page {req.pages[0].page_idx + 1}"

    return templates.TemplateResponse(
        request=request,
        name="partials/pdf_item.html",
        context={
            "request": request,
            "file_id": file_id,
            "filename": filename,
            "label": label,
        },
    )

class RenameRequest(BaseModel):
    custom_name: str

@router.post("/rename/{file_id}")
def rename_pdf(file_id: str, req: RenameRequest, request: Request):
    """Renames an extracted PDF metadata and returns the updated HTML fragment."""
    try:
        # Check if the file exists
        path = pdf_service.get_output_path(file_id)
        
        # Load existing metadata
        metadata = pdf_service.get_metadata(file_id)
        metadata["custom_name"] = req.custom_name
        
        # Save metadata
        pdf_service.save_metadata(file_id, metadata)
        
        # Rename physical file
        clean_name = req.custom_name.replace('\n', ' ').replace('\r', '').strip()
        if len(clean_name) > 150:
            clean_name = clean_name[:150].strip()
        
        encoded = clean_name.encode('utf-8')
        if len(encoded) > 210:
            clean_name = encoded[:210].decode('utf-8', 'ignore').strip()
        
        new_filename = f"{clean_name}.pdf"
        new_path = path.parent / f"{file_id}_{new_filename}"
        if new_path != path:
            path.rename(new_path)
            
        label = metadata.get("label", "PDF")
        
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rename error: {e}")

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


