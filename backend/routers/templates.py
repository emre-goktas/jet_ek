from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from backend.services.docx_service import get_templates

router = APIRouter()

BASE_DIR = Path(__file__).parent.parent.parent


@router.get("/api/templates")
def list_templates():
    """Returns the list of available document templates (institutions)."""
    templates = get_templates()
    # Don't send heavy base64 images to frontend unless needed
    # We can strip them to save bandwidth
    summary_list = []
    for t in templates:
        summary_list.append({
            "id": t["id"],
            "name": t["name"]
        })
    return summary_list


def _find_template(template_id: str) -> dict:
    for t in get_templates():
        if t["id"] == template_id:
            return t
    raise HTTPException(status_code=404, detail="Template not found.")


@router.get("/api/templates/{template_id}")
def get_template_config(template_id: str):
    """Returns the full template config (header/table/footer definitions, logo,
    etc.) so the browser can build the Word index document itself."""
    return _find_template(template_id)


@router.get("/api/templates/{template_id}/file")
def get_template_file(template_id: str):
    """Returns the raw .docx bytes for templates that fill in an existing
    Word file (the 'file_path' mode) instead of building one from scratch."""
    template = _find_template(template_id)
    file_path = template.get("file_path")
    if not file_path:
        raise HTTPException(status_code=404, detail="This template has no source file.")

    full_path = (BASE_DIR / file_path).resolve()
    if not full_path.is_relative_to(BASE_DIR) or not full_path.exists():
        raise HTTPException(status_code=404, detail="Template file not found.")

    return FileResponse(
        path=str(full_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=full_path.name,
    )
