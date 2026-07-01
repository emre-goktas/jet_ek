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
from backend import database

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
    ocr: bool = False
    ocr_lang: str = "tur+eng"  # Tesseract language(s): "tur", "eng", or "tur+eng"
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

    if req.ocr:
        lang = req.ocr_lang if req.ocr_lang in ALLOWED_OCR_LANGS else "tur+eng"
        task_id = "TASK_" + uuid.uuid4().hex
        input_path = pdf_service.get_output_path(file_id)
        
        database.create_task(task_id, filename, label)
        background_tasks.add_task(pdf_service.perform_ocr, task_id, input_path, filename, lang)
        
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(task_id)

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
    """Renames an extracted PDF and returns the updated HTML fragment."""
    try:
        path = pdf_service.get_output_path(file_id)
        # Parse the old filename to preserve its label if needed, but since it's just UUID_filename,
        # we can just construct the new name.
        new_filename = f"{req.custom_name}.pdf"
        new_path = path.parent / f"{file_id}_{new_filename}"
        
        if path != new_path:
            path.rename(new_path)
            
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rename error: {e}")

    # Estimate page count or label? For renaming, we might lose the page count label.
    # Let's try to get page count if we can, or just display "Renamed".
    import pymupdf
    try:
        doc = pymupdf.open(str(new_path))
        count = len(doc)
        doc.close()
        label = f"{count} Pages" if count > 1 else "Page 1"
    except Exception:
        label = "PDF"

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

@router.get("/extract-status/{task_id}")
async def get_extract_status(task_id: str, request: Request):
    """Returns the status of OCR performed during extraction."""
    task = database.get_task(task_id)
    if not task:
        return {"status": "error", "error": "Task not found."}
    
    status = task.get("status")
    if status in ["pending", "processing"]:
        return {"status": status}
    elif status == "failed":
        return {"status": "error", "error": task.get("error_message", "Unknown Error")}
    elif status == "done":
        pdf_id = task.get("pdf_id")
        filename = task.get("filename")
        label = task.get("label", "OCR Result")
        
        html_response = templates.TemplateResponse(
            request=request,
            name="partials/pdf_item.html",
            context={
                "request": request,
                "file_id": pdf_id,
                "filename": filename,
                "label": label,
            },
        )
        return {"status": "done", "html": html_response.body.decode('utf-8')}
