"""
Extract endpoint — POST /extract
Extracts the selected page range as a new PDF.
Response: HTML fragment added to the left panel via HTMX.
"""
import gzip
import logging
import contextlib
from pathlib import Path
# pyrefly: ignore [missing-import]
import pymupdf
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, Response
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

    label = f"{actual_count} sayfa"

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


# ─── Batch split (Kurallı Böl / Hızlı Ayıkla) ─────────────────────────────
# Both frontend modes pre-compute an ordered list of page-groups (never
# crossing a source document's boundary — enforced client-side) and post them
# all here in one request. A bulk endpoint exists specifically so that
# splitting e.g. 500 pages into 100 tiny PDFs doesn't mean 100 round trips
# against /extract's 30/minute limit — one call does all of it server-side.
MAX_SPLIT_GROUPS = 300

class SplitGroup(BaseModel):
    pages: list[PageExtract]
    # Set by the frontend's bulk materializeRows() (output-panel.js) when it
    # already knows the row's name (a pending row picked up its name at
    # creation time or via an in-session rename) — the caller's name wins
    # over the auto-generated one below. Left unset, this endpoint's original
    # split-mode caller gets the exact same '{kaynak}_{ilk}-{son}' auto-name
    # it always has.
    custom_name: str | None = None

class BatchSplitRequest(BaseModel):
    groups: list[SplitGroup]


@router.post("/extract/batch-split", response_class=JSONResponse)
@limiter.limit("10/minute")
def batch_split(req: BatchSplitRequest, request: Request, current_user: dict = Depends(auth_service.get_current_user)):
    """Extracts each group as its own PDF. Returns {"group-<i>": html} for
    whichever groups succeeded — a source file vanishing mid-batch (e.g.
    swept by the idle cleanup) only drops that one group instead of failing
    the whole request. Also doubles as the bulk "materialize many still-pending
    rows in one request" endpoint — see materializeRows() in output-panel.js —
    since it already does exactly that; only the naming logic below is what
    lets both callers share it (a caller-supplied custom_name wins, else the
    original '{kaynak}_{ilk}-{son}' auto-name).

    A single shared open_docs cache + ExitStack spans every group in this
    request (passed into every extract_pages call below) — groups very
    commonly share a source (e.g. materializeRows cutting 30 single-page rows
    out of the same one upload), and without this each group would reopen/
    reparse that same source PDF from scratch instead of reusing the handle
    an earlier group in this same request already opened.
    """
    if not req.groups:
        raise HTTPException(status_code=400, detail="No groups to split.")
    if len(req.groups) > MAX_SPLIT_GROUPS:
        raise HTTPException(status_code=400, detail=f"Tek seferde en fazla {MAX_SPLIT_GROUPS} parça oluşturulabilir.")

    user_dir = pdf_service.user_storage_dir(current_user["email"])
    response_htmls = {}

    with contextlib.ExitStack() as stack:
        open_docs: dict = {}
        for i, group in enumerate(req.groups):
            if not group.pages:
                continue
            try:
                if group.custom_name:
                    custom_name = group.custom_name
                else:
                    source_pdf_id = group.pages[0].pdf_id
                    _, source_filename, _ = pdf_service.get_pdf_info(source_pdf_id, user_dir)
                    source_stem = Path(source_filename).stem
                    page_numbers = sorted(p.page_idx + 1 for p in group.pages)
                    page_range = str(page_numbers[0]) if page_numbers[0] == page_numbers[-1] else f"{page_numbers[0]}-{page_numbers[-1]}"
                    custom_name = f"{source_stem}_{page_range}"

                pages_dicts = [p.model_dump() for p in group.pages]
                file_id, filename, actual_count = pdf_service.extract_pages(
                    pages_dicts, user_dir, custom_name=custom_name, open_docs=open_docs, stack=stack
                )
            except Exception:
                logger.exception(f"Batch split failed for group {i}")
                continue

            label = f"{actual_count} sayfa"
            context = {
                "request": request,
                "file_id": file_id,
                "filename": filename,
                "label": label,
                "page_count": actual_count,
                "custom_name": custom_name,
            }
            template_response = templates.TemplateResponse(request=request, name="partials/pdf_item.html", context=context)
            response_htmls[f"group-{i}"] = template_response.body.decode("utf-8")

    return JSONResponse(content=response_htmls)


# ─── Finalize (lazy extraction — "download" pass) ─────────────────────────
# The output list only ever tracks pending rows client-side (source pdf_id +
# page ranges + custom name, no backend call) until "İndir" is clicked — see
# frontend/static/js/viewer-state.js's pendingOutputs. This endpoint is what
# that final click hits: one request that cuts every still-pending row AND
# zips them, instead of one /extract call per row. A row that was already
# materialized on demand (opened in Grup Düzenleyici, singly downloaded, or
# AI-renamed before the bulk download) skips this path entirely — the
# frontend fetches it via the existing /pdf-source/{id}.

class FinalizeItem(BaseModel):
    pages: list[PageExtract]
    custom_name: str | None = None

class FinalizeRequest(BaseModel):
    items: list[FinalizeItem]


@router.post("/extract/finalize")
@limiter.limit("5/minute")
def finalize_pending(req: FinalizeRequest, request: Request, current_user: dict = Depends(auth_service.get_current_user)):
    """One-shot bulk cut for output rows that were only ever tracked
    client-side — see the module note above. Unlike /extract and
    /extract/batch-split, nothing is written to user_dir; the response is a
    ZIP of the cut PDFs (entries named "{i}_{filename}", i = the item's
    position in the request) that the browser unzips immediately as part of
    assembling the real download, never something a user saves directly. A
    source file that's vanished for one item only drops that item's entry
    from the zip — same best-effort semantics as batch_split.
    """
    if not req.items:
        raise HTTPException(status_code=400, detail="No items to finalize.")
    if len(req.items) > MAX_SPLIT_GROUPS:
        raise HTTPException(status_code=400, detail=f"Tek seferde en fazla {MAX_SPLIT_GROUPS} parça sonlandırılabilir.")

    user_dir = pdf_service.user_storage_dir(current_user["email"])
    items_dicts = [{"pages": [p.model_dump() for p in it.pages], "custom_name": it.custom_name} for it in req.items]
    try:
        zip_bytes = pdf_service.build_finalize_zip(items_dicts, user_dir)
    except Exception:
        logger.exception(f"Finalize failed for request with {len(req.items)} items")
        raise HTTPException(status_code=500, detail="Finalize failed.")

    # Deliberately NOT a global GZipMiddleware: Starlette's GZipMiddleware
    # doesn't special-case 206 Partial Content, so applying it app-wide would
    # risk corrupting /pdf-source's Range-request responses (the mechanism
    # pdf.js's progressive loading depends on — see that route's own
    # docstring). Gzip is applied here only, by hand, scoped to this one
    # route. Measured benefit is modest (~9% smaller on a text-heavy
    # synthetic book — the PDFs inside are already deflate-compressed by
    # pdf_service, so there's limited further headroom) but free: this
    # response is never itself Range-requested, and fetch() decompresses
    # Content-Encoding: gzip transparently, no frontend change needed.
    if "gzip" in request.headers.get("accept-encoding", ""):
        zip_bytes = gzip.compress(zip_bytes, compresslevel=6)
        return Response(content=zip_bytes, media_type="application/zip", headers={"Content-Encoding": "gzip"})

    return Response(content=zip_bytes, media_type="application/zip")


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

    label = f"{page_count} sayfa"
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
