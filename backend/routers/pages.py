"""
Page render endpoint — GET /page/{pdf_id}/{page_number}
Returns page image as PNG.
"""
import asyncio
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from backend.services import pdf_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Limit concurrent PDF rendering tasks to prevent memory/IO exhaustion
# especially with huge files (1.5GB) and rapid scrolling.
RENDER_SEMAPHORE = asyncio.Semaphore(10)

@router.get("/page/{pdf_id}/{page_number}")
async def get_page_image(pdf_id: str, page_number: int):
    """Returns the specified page as PNG."""
    async with RENDER_SEMAPHORE:
        try:
            # Run the synchronous render_page in a threadpool
            png_path = await asyncio.to_thread(pdf_service.render_page, pdf_id, page_number)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="PDF not found.")
        except IndexError:
            raise HTTPException(status_code=404, detail="Page not found.")
        except Exception as e:
            logger.exception(f"Page render error for pdf_id={pdf_id} page={page_number}")
            raise HTTPException(status_code=500, detail="Page render error.")

    return FileResponse(path=str(png_path), media_type="image/png")
