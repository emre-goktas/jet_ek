"""
PDF processing service — using PyMuPDF (pymupdf):
- PDF upload & save
- Render page as PNG (memory cache)
- Extract page range
- Rotate page
"""
import os
import re
import uuid
import io
import json
import asyncio
import tempfile
import threading
from pathlib import Path
from typing import Literal

# pyrefly: ignore [missing-import]
import pymupdf  # PyMuPDF
import contextlib
import logging

from backend.services import security

_LOCK_COUNTS: dict[str, int] = {}
_LOCK_COUNTS_GUARD = threading.Lock()

@contextlib.contextmanager
def lock_file(filepath: Path):
    """Marks filepath as in-use for the duration of the block. Reference-counted so
    overlapping uses of the same path (e.g. a render and an extract touching the
    same source PDF) don't let one exit prematurely unmark it as free while the
    other is still using it."""
    filepath_str = str(filepath.resolve())
    with _LOCK_COUNTS_GUARD:
        _LOCK_COUNTS[filepath_str] = _LOCK_COUNTS.get(filepath_str, 0) + 1
    try:
        yield
    finally:
        with _LOCK_COUNTS_GUARD:
            count = _LOCK_COUNTS.get(filepath_str, 0) - 1
            if count <= 0:
                _LOCK_COUNTS.pop(filepath_str, None)
            else:
                _LOCK_COUNTS[filepath_str] = count

def is_file_locked(filepath: Path) -> bool:
    return str(filepath.resolve()) in _LOCK_COUNTS

# Temporary file directory
STORAGE_DIR = Path(__file__).parent.parent / "storage"
STORAGE_DIR.mkdir(exist_ok=True)

_HEX32_RE = re.compile(r"[0-9a-f]{32}")

def is_valid_uuid(val: str) -> bool:
    """Checks if the entered value is a 32-character hex (UUID)."""
    return bool(val and _HEX32_RE.fullmatch(val))

_PATH_CACHE: dict[str, Path] = {}

def _resolve_path(id_: str) -> Path:
    """Resolves the on-disk path for a given id (source or output PDF), using an
    in-memory cache to avoid re-scanning STORAGE_DIR on every lookup."""
    cached = _PATH_CACHE.get(id_)
    if cached is not None and cached.exists():
        return cached

    matches = list(STORAGE_DIR.glob(f"{id_}_*.pdf"))
    if not matches:
        raise FileNotFoundError(id_)
    path = matches[0]
    _PATH_CACHE[id_] = path
    return path


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
    _PATH_CACHE[pdf_id] = dest

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

    try:
        return _resolve_path(pdf_id)
    except FileNotFoundError:
        raise FileNotFoundError(f"PDF not found: {pdf_id}")


def _build_pdf_from_pages(pages: list[dict]) -> "pymupdf.Document":
    """Assembles a new in-memory document from an ordered page list, each dict
    shaped {"pdf_id": "id", "page_idx": 0, "rotation": 90}. Opens each unique
    source pdf_id once (locked for the duration via lock_file), applies the
    requested rotation delta on top of whatever rotation the source page already
    carries, and skips out-of-range page_idx values with a warning instead of
    raising. Caller validates the pages list (non-empty / size ceiling) and is
    responsible for closing the returned document.
    """
    new_doc = pymupdf.open()

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
            else:
                logging.warning(f"_build_pdf_from_pages: skipping out-of-range page_idx={idx} for pdf_id={pid}")

    return new_doc


def extract_pages(pages: list[dict], custom_name: str | None = None) -> tuple[str, str, int]:
    """Extracts the specified list of pages from potentially multiple PDFs
    and rotates them according to the specified angles.

    Args:
        pages: List of dicts e.g. [{"pdf_id": "id", "page_idx": 0, "rotation": 90}]
        custom_name: Optional custom filename prefix.

    Returns:
        (file_id, filename, actual_page_count)
    """
    if not pages:
        raise ValueError("No valid pages selected.")

    if len(pages) > 5000:
        raise ValueError("To protect system performance, a maximum of 5000 pages can be extracted at once.")

    has_rotation = any(p.get("rotation", 0) for p in pages)
    new_doc = _build_pdf_from_pages(pages)

    actual_count = len(new_doc)
    file_id = uuid.uuid4().hex

    if custom_name:
        save_metadata(file_id, {"custom_name": custom_name})
        clean_name = security.sanitize_filename(custom_name)
        filename = f"{clean_name}.pdf"
    else:
        if has_rotation:
            filename = f"rotated_extracted.pdf"
        else:
            filename = f"extracted.pdf"

    out_path = STORAGE_DIR / f"{file_id}_{filename}"
    new_doc.save(str(out_path))
    new_doc.close()
    _PATH_CACHE[file_id] = out_path

    return file_id, filename, actual_count


def update_pages(file_id: str, pages: list[dict]) -> int:
    """Rebuilds file_id's PDF content IN PLACE from the given ordered page list
    (reorder/delete/rotate persisted from Batch Mode), keeping the same file_id.

    Since the pages typically self-reference file_id (a batch saving its own
    edited grid), the destination must not be truncated while still being read
    as a source: build the whole new document first, close every source handle,
    then atomically swap it in via a temp file + os.replace.

    Args:
        file_id: existing output's id
        pages: List of dicts e.g. [{"pdf_id": "id", "page_idx": 0, "rotation": 90}],
               in the final desired order.

    Returns:
        actual_page_count after the rebuild.
    """
    if not pages:
        raise ValueError("Cannot update to an empty PDF.")

    if len(pages) > 5000:
        raise ValueError("To protect system performance, a maximum of 5000 pages can be updated at once.")

    dest_path = get_output_path(file_id)

    with lock_file(dest_path):
        new_doc = _build_pdf_from_pages(pages)
        actual_count = len(new_doc)

        tmp_name = None
        try:
            fd, tmp_name = tempfile.mkstemp(dir=STORAGE_DIR, suffix=".pdf")
            os.close(fd)
            try:
                new_doc.save(tmp_name)
            finally:
                new_doc.close()
            os.chmod(tmp_name, 0o644)  # match the permissions files normally get, not mkstemp's 0600
            os.replace(tmp_name, dest_path)  # atomic same-directory swap
        except Exception:
            if tmp_name:
                Path(tmp_name).unlink(missing_ok=True)
            raise

    return actual_count


def get_output_path(file_id: str) -> Path:
    """Returns the output PDF file path according to file_id."""
    if not is_valid_uuid(file_id):
        raise ValueError(f"Invalid File ID: {file_id}")

    try:
        return _resolve_path(file_id)
    except FileNotFoundError:
        raise FileNotFoundError(f"Output file not found: {file_id}")

def get_pdf_info(file_id: str):
    """Returns (path, filename, page_count) for a given file_id."""
    if not is_valid_uuid(file_id):
        raise ValueError(f"Invalid File ID: {file_id}")

    # Check if original upload
    orig_path = STORAGE_DIR / f"{file_id}_src.pdf"
    if orig_path.exists():
        _PATH_CACHE[file_id] = orig_path
        metadata = get_metadata(file_id)
        filename = metadata.get("original_filename", f"{file_id}.pdf")
        doc = pymupdf.open(str(orig_path))
        count = len(doc)
        doc.close()
        return orig_path, filename, count

    # Check if extracted batch
    try:
        path = _resolve_path(file_id)
    except FileNotFoundError:
        raise FileNotFoundError(f"PDF not found for id: {file_id}")

    filename = path.name.split('_', 1)[1]
    doc = pymupdf.open(str(path))
    count = len(doc)
    doc.close()
    return path, filename, count


def rename_output(file_id: str, new_display_name: str) -> tuple[Path, str, dict]:
    """Renames the output file for file_id to a sanitized version of new_display_name,
    persists the display name in metadata, and updates the path cache.

    Returns:
        (new_path, new_filename, metadata)
    """
    path = get_output_path(file_id)
    metadata = get_metadata(file_id)
    metadata["custom_name"] = new_display_name
    save_metadata(file_id, metadata)

    clean_name = security.sanitize_filename(new_display_name)
    new_filename = f"{clean_name}.pdf"
    new_path = path.parent / f"{file_id}_{new_filename}"

    if new_path != path:
        with lock_file(path), lock_file(new_path):
            path.rename(new_path)
        _PATH_CACHE[file_id] = new_path
    else:
        _PATH_CACHE[file_id] = path

    return new_path, new_filename, metadata


def delete_output(file_id: str) -> None:
    """Best-effort full removal of an output once its content has been
    delivered to the client (e.g. a ZIP built client-side, or a completed
    single-file download): shreds the PDF bytes, its metadata sidecar, and
    drops the cached path. Silently no-ops for a missing/invalid/locked
    file_id — this is opportunistic cleanup, not a source of truth the
    caller needs to retry on failure.
    """
    try:
        path = get_output_path(file_id)
    except (FileNotFoundError, ValueError):
        return

    if is_file_locked(path):
        return

    secure_delete(path)

    json_path = STORAGE_DIR / f"{file_id}.json"
    if json_path.exists():
        secure_delete(json_path)

    _PATH_CACHE.pop(file_id, None)


def secure_delete(path: Path) -> None:
    """Best-effort secure deletion: overwrites the file's bytes before unlinking.
    Not a guarantee on copy-on-write filesystems/SSDs with wear-leveling, but a
    meaningful improvement over a bare unlink for sensitive documents.
    """
    try:
        size = path.stat().st_size
        with open(path, "r+b") as f:
            f.write(os.urandom(size))
            f.flush()
            os.fsync(f.fileno())
    except FileNotFoundError:
        return
    except Exception as e:
        logging.warning(f"Secure overwrite failed for {path}, deleting without shredding: {e}")
    path.unlink(missing_ok=True)
