"""
Page render endpoint — GET /page/{pdf_id}/{page_number}
Returns page image as PNG.
"""
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException
# pyrefly: ignore [missing-import]
from fastapi.responses import FileResponse

from backend.services import pdf_service

router = APIRouter()


@router.get("/page/{pdf_id}/{page_number}")
def get_page_image(pdf_id: str, page_number: int):
    """Returns the specified page as PNG."""
    try:
        png_path = pdf_service.render_page(pdf_id, page_number)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="PDF not found.")
    except IndexError:
        raise HTTPException(status_code=404, detail="Page not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Page render error: {e}")

    return FileResponse(path=str(png_path), media_type="image/png")
