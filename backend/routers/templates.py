from fastapi import APIRouter
from backend.services.docx_service import get_templates

router = APIRouter()

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
