"""
PDF processing service — using PyMuPDF (pymupdf):
- PDF upload & save
- Render page as PNG (memory cache)
- Extract page range
- Rotate page
"""
import uuid
import io
import asyncio
from pathlib import Path
from typing import Literal

# pyrefly: ignore [missing-import]
import pymupdf  # PyMuPDF
from functools import lru_cache
import contextlib
import logging

ACTIVE_FILE_LOCKS = set()

@contextlib.contextmanager
def lock_file(filepath: Path):
    filepath_str = str(filepath.resolve())
    ACTIVE_FILE_LOCKS.add(filepath_str)
    try:
        yield
    finally:
        ACTIVE_FILE_LOCKS.discard(filepath_str)

def is_file_locked(filepath: Path) -> bool:
    return str(filepath.resolve()) in ACTIVE_FILE_LOCKS

# Temporary file directory
STORAGE_DIR = Path(__file__).parent.parent / "storage"
STORAGE_DIR.mkdir(exist_ok=True)

def is_valid_uuid(val: str) -> bool:
    """Checks if the entered value is a 32-character hex (UUID)."""
    return bool(val and len(val) == 32 and val.isalnum())

import json

def get_metadata(file_id: str) -> dict:
    """Returns the metadata dict for the given file_id. Returns empty dict if not found."""
    json_path = STORAGE_DIR / f"{file_id}.json"
    if json_path.exists():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_metadata(file_id: str, metadata: dict):
    """Saves the metadata dict for the given file_id."""
    json_path = STORAGE_DIR / f"{file_id}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False)

def save_upload(file_path: Path, original_name: str) -> tuple[str, int]:
    """Saves the uploaded PDF file to storage with a unique pdf_id.

    Returns:
        (pdf_id, page_count)
    """
    import shutil
    pdf_id = uuid.uuid4().hex
    dest = STORAGE_DIR / f"{pdf_id}_src.pdf"
    
    STORAGE_DIR.mkdir(exist_ok=True)
    shutil.move(str(file_path), str(dest))

    # Get page count
    with lock_file(dest):
        doc = pymupdf.open(str(dest))
        page_count = len(doc)
        doc.close()

    return pdf_id, page_count





def _src_path(pdf_id: str) -> Path:
    """Returns the path of the source PDF file."""
    if not is_valid_uuid(pdf_id):
        raise ValueError(f"Invalid PDF ID: {pdf_id}")
        
    matches = list(STORAGE_DIR.glob(f"{pdf_id}_*.pdf"))
    if not matches:
        raise FileNotFoundError(f"PDF not found: {pdf_id}")
    return matches[0]


def render_page(pdf_id: str, page_num: int, dpi: int = 120) -> Path:
    """Renders the specified page as PNG, caches it on disk, and returns the file path.
    The result is stored in STORAGE_DIR.

    Args:
        pdf_id: Source PDF ID
        page_num: 0-based page number
        dpi: Render resolution (default 120)

    Returns:
        Path object of the created or existing PNG file
    """
    path = _src_path(pdf_id)
    out_path = STORAGE_DIR / f"{pdf_id}_page_{page_num}_{dpi}.png"

    if out_path.exists():
        return out_path

    with lock_file(path):
        doc = pymupdf.open(str(path))
        try:
            page = doc[page_num]
            mat = pymupdf.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            png_bytes = pix.tobytes("png")
            
            with open(out_path, "wb") as f:
                f.write(png_bytes)
        finally:
            doc.close()

    return out_path


def extract_pages(pages: list[dict], custom_name: str | None = None, file_counter: int | None = None) -> tuple[str, str]:
    """Extracts the specified list of pages from potentially multiple PDFs
    and rotates them according to the specified angles.

    Args:
        pages: List of dicts e.g. [{"pdf_id": "id", "page_idx": 0, "rotation": 90}]
        custom_name: Optional custom filename prefix.
        file_counter: Explicit counter sent from frontend session.

    Returns:
        (file_id, filename)
    """
    if not pages:
        raise ValueError("No valid pages selected.")

    if len(pages) > 5000:
        raise ValueError("To protect system performance, a maximum of 5000 pages can be extracted at once.")

    new_doc = pymupdf.open()
    has_rotation = False
    
    from contextlib import ExitStack
    open_docs = {}
    
    with ExitStack() as stack:
        for p in pages:
            pid = p.get("pdf_id")
            idx = p.get("page_idx")
            rot = p.get("rotation", 0)
            
            if pid not in open_docs:
                src_path = _src_path(pid)
                stack.enter_context(lock_file(src_path))
                src_doc = stack.enter_context(pymupdf.open(str(src_path)))
                open_docs[pid] = src_doc
                
            src_doc = open_docs[pid]
            if 0 <= idx < len(src_doc):
                new_doc.insert_pdf(src_doc, from_page=idx, to_page=idx)
                if rot != 0:
                    page = new_doc[-1]
                    page.set_rotation((page.rotation + rot) % 360)
                    has_rotation = True

    file_id = uuid.uuid4().hex
    
    if custom_name:
        save_metadata(file_id, {"custom_name": custom_name})
        
        # Sanitize filename: replace newlines with spaces
        clean_name = custom_name.replace('\n', ' ').replace('\r', '').strip()
        
        if len(clean_name) > 150:
            clean_name = clean_name[:150].strip()
            
        encoded = clean_name.encode('utf-8')
        if len(encoded) > 210:
            clean_name = encoded[:210].decode('utf-8', 'ignore').strip()
        filename = f"{clean_name}.pdf"
    else:
        # Append selected page count to filename
        count = len(pages)
        if count == 1:
            label = f"page_{pages[0]['page_idx'] + 1}"
        else:
            label = f"{count}_pages"

        if has_rotation:
            filename = f"rotated_{label}.pdf"
        else:
            filename = f"extracted_{label}.pdf"
        
    out_path = STORAGE_DIR / f"{file_id}_{filename}"
    new_doc.save(str(out_path))
    new_doc.close()

    return file_id, filename


def get_output_path(file_id: str) -> Path:
    """Returns the output PDF file path according to file_id."""
    if not is_valid_uuid(file_id):
        raise ValueError(f"Invalid File ID: {file_id}")
        
    matches = list(STORAGE_DIR.glob(f"{file_id}_*.pdf"))
    if not matches:
        raise FileNotFoundError(f"Output file not found: {file_id}")
    return matches[0]
