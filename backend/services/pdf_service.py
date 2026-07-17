"""
PDF processing service — using PyMuPDF (pymupdf):
- PDF upload & save
- Render page as PNG (memory cache)
- Extract page range
- Rotate page
"""
import os
import re
import io
import uuid
import json
import time
import zipfile
import hashlib
import tempfile
import threading
from pathlib import Path

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


def user_storage_dir(email: str) -> Path:
    """Per-user storage root: storage/user_{sha256(email)}/. Hashed rather than
    the raw address so directory listings/backups never expose a PII string,
    and so odd email characters never have to be filesystem-escaped. Every
    file/path lookup in this module is scoped to one such directory — a
    request for another user's file_id simply never matches anything here,
    which is what makes this both the storage layout AND the ownership check."""
    digest = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
    d = STORAGE_DIR / f"user_{digest}"
    d.mkdir(parents=True, exist_ok=True)
    return d

_PATH_CACHE: dict[str, Path] = {}

def _touch(path: Path) -> None:
    """Bumps mtime to now — every successful resolve of a file counts as
    "still in use" for the 15-minute idle sweep (_sweep_storage in main.py),
    not just the writes (extract/rename/update) that already do this as a
    side effect of rewriting the file. Without this, an original upload that
    a user is still actively extracting batches FROM (pure reads — opening it
    doesn't write anything) would sit at its upload-time mtime the whole
    session and could get swept out from under them mid-workflow, even
    though the tab's been open and busy the entire time. Best-effort: a
    failed touch shouldn't break the read that triggered it."""
    try:
        os.utime(path, None)
    except OSError:
        pass


def _resolve_path(id_: str, user_dir: Path) -> Path:
    """Resolves the on-disk path for a given id (source or output PDF) within
    user_dir, using an in-memory cache to avoid re-scanning on every lookup.
    The cached entry is only trusted if it actually lives in user_dir — this
    is what stops the cache from becoming a cross-user shortcut around the
    directory scoping (a bare "cached.exists()" check would let a valid path
    resolved for one user get handed straight back to a different user who
    supplies the same file_id, before the glob below ever gets a chance to
    correctly find nothing)."""
    cached = _PATH_CACHE.get(id_)
    if cached is not None and cached.parent == user_dir and cached.exists():
        _touch(cached)
        return cached

    matches = list(user_dir.glob(f"{id_}_*.pdf"))
    if not matches:
        raise FileNotFoundError(id_)
    path = matches[0]
    _PATH_CACHE[id_] = path
    _touch(path)
    return path


def get_metadata(file_id: str, user_dir: Path) -> dict:
    """Returns the metadata dict for the given file_id. Returns empty dict if not found."""
    json_path = user_dir / f"{file_id}.json"
    if json_path.exists():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_metadata(file_id: str, metadata: dict, user_dir: Path):
    """Saves the metadata dict for the given file_id."""
    json_path = user_dir / f"{file_id}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False)

def save_upload(file_path: Path, original_name: str, user_dir: Path) -> tuple[str, int]:
    """Saves the uploaded PDF file to storage with a unique pdf_id.

    Re-saved (garbage-collected + cleaned) through PyMuPDF rather than moved
    in as-is: some source PDFs (scanners, older/third-party tools) carry a
    malformed xref/page-tree that MuPDF silently repairs on open but pdf.js
    does not — pdf.js instead falls back to indexing every object in the
    file one HTTP range request at a time, turning ordinary page-scrolling
    into dozens of slow (or, over a flaky tunnel, outright failing) fetches
    for a large document. Normalizing every upload here means /pdf-source
    always serves a structure pdf.js can jump straight into.

    Falls back to storing the raw bytes unchanged if the resave itself fails
    (e.g. an encrypted PDF) — better to serve a file pdf.js might struggle
    with than to reject an upload MuPDF was able to open at all.

    Returns:
        (pdf_id, page_count)
    """
    import shutil
    pdf_id = uuid.uuid4().hex
    dest = user_dir / f"{pdf_id}_src.pdf"

    doc = pymupdf.open(str(file_path))
    page_count = len(doc)
    tmp_name = None
    try:
        with lock_file(dest):
            fd, tmp_name = tempfile.mkstemp(dir=user_dir, suffix=".pdf")
            os.close(fd)
            try:
                doc.save(tmp_name, garbage=4, clean=True, deflate=True)
            finally:
                doc.close()
            os.chmod(tmp_name, 0o644)  # match the permissions files normally get, not mkstemp's 0600
            os.replace(tmp_name, dest)
    except Exception:
        logging.warning(f"Clean resave failed for upload {original_name!r}; storing raw bytes instead.", exc_info=True)
        if not doc.is_closed:
            doc.close()
        if tmp_name and os.path.exists(tmp_name):
            os.remove(tmp_name)
        shutil.move(str(file_path), str(dest))

    _PATH_CACHE[pdf_id] = dest
    save_metadata(pdf_id, {"original_filename": original_name}, user_dir)

    return pdf_id, page_count


def _src_path(pdf_id: str, user_dir: Path) -> Path:
    """Returns the path of the source PDF file."""
    if not is_valid_uuid(pdf_id):
        raise ValueError(f"Invalid PDF ID: {pdf_id}")

    try:
        return _resolve_path(pdf_id, user_dir)
    except FileNotFoundError:
        raise FileNotFoundError(f"PDF not found: {pdf_id}")


def _build_pdf_from_pages(
    pages: list[dict],
    user_dir: Path,
    open_docs: dict | None = None,
    stack: contextlib.ExitStack | None = None,
) -> "pymupdf.Document":
    """Assembles a new in-memory document from an ordered page list, each dict
    shaped {"pdf_id": "id", "page_idx": 0, "rotation": 90}. Every pdf_id is
    resolved within user_dir (see _src_path/_resolve_path) — a page list that
    names a file_id belonging to a different user simply fails to resolve,
    which is what stops /extract and /update from being usable to pull pages
    out of someone else's document. Opens each unique source pdf_id once
    (locked for the duration via lock_file), applies the requested rotation
    delta on top of whatever rotation the source page already carries, and
    skips out-of-range page_idx values with a warning instead of raising.
    Caller validates the pages list (non-empty / size ceiling) and is
    responsible for closing the returned document.

    open_docs/stack: optional shared source-doc cache + its owning ExitStack.
    Pass these when building MANY documents back-to-back that can share
    sources (build_finalize_zip, batch_split in extract.py) — a source
    referenced by several items in the same batch is then opened/parsed only
    once for the whole batch instead of once per item, since the caller keeps
    the cache (and the stack that owns closing it) alive across every call.
    Left as None (the default, single-extraction case — /extract, /update),
    a private stack scoped to just this one call is used, exactly as before.
    """
    new_doc = pymupdf.open()

    owns_stack = stack is None
    if open_docs is None:
        open_docs = {}
    if owns_stack:
        stack = contextlib.ExitStack()

    try:
        for p in pages:
            pid = p.get("pdf_id")
            idx = p.get("page_idx")
            rot = p.get("rotation", 0)

            if pid not in open_docs:
                src_path = _src_path(pid, user_dir)
                stack.enter_context(lock_file(src_path))
                open_docs[pid] = stack.enter_context(pymupdf.open(str(src_path)))

            src_doc = open_docs[pid]
            if 0 <= idx < len(src_doc):
                new_doc.insert_pdf(src_doc, from_page=idx, to_page=idx)
                if rot != 0:
                    page = new_doc[-1]
                    page.set_rotation((page.rotation + rot) % 360)
            else:
                logging.warning(f"_build_pdf_from_pages: skipping out-of-range page_idx={idx} for pdf_id={pid}")
    finally:
        if owns_stack:
            stack.close()

    return new_doc


def extract_pages(
    pages: list[dict],
    user_dir: Path,
    custom_name: str | None = None,
    open_docs: dict | None = None,
    stack: contextlib.ExitStack | None = None,
) -> tuple[str, str, int]:
    """Extracts the specified list of pages from potentially multiple PDFs
    and rotates them according to the specified angles.

    Args:
        pages: List of dicts e.g. [{"pdf_id": "id", "page_idx": 0, "rotation": 90}]
        user_dir: the calling user's storage directory (see user_storage_dir) —
            every pdf_id in pages must resolve within it.
        custom_name: Optional custom filename prefix.
        open_docs/stack: optional shared source-doc cache, passed straight
            through to _build_pdf_from_pages — see its docstring. Used by
            batch_split (extract.py) so a source shared by several groups in
            one batch-split request is opened once for the whole request
            instead of once per group.

    Returns:
        (file_id, filename, actual_page_count)
    """
    if not pages:
        raise ValueError("No valid pages selected.")

    if len(pages) > 5000:
        raise ValueError("To protect system performance, a maximum of 5000 pages can be extracted at once.")

    new_doc = _build_pdf_from_pages(pages, user_dir, open_docs=open_docs, stack=stack)

    actual_count = len(new_doc)
    file_id = uuid.uuid4().hex

    if custom_name:
        save_metadata(file_id, {"custom_name": custom_name}, user_dir)
        clean_name = security.sanitize_filename(custom_name)
        filename = f"{clean_name}.pdf"
    else:
        filename = "evrak.pdf"

    out_path = user_dir / f"{file_id}_{filename}"
    # garbage=4/clean/deflate: same convention save_upload() already uses.
    # insert_pdf (in _build_pdf_from_pages) can leave a copied page still
    # holding a reference to its *source* document's full inherited
    # Resources/font/xref structure rather than just what that page actually
    # uses — garbage collection (reachability-based pruning) + clean (resolves
    # inherited attributes down to concrete per-page values) is what strips
    # that dead weight back out; without it an extracted page or two can come
    # out far larger than its actual content, especially from source PDFs
    # that share resources across pages at the Pages-tree level (common in
    # office-suite-generated documents) rather than per-page.
    new_doc.save(str(out_path), garbage=4, clean=True, deflate=True)
    new_doc.close()
    _PATH_CACHE[file_id] = out_path

    return file_id, filename, actual_count


def build_finalize_zip(items: list[dict], user_dir: Path) -> bytes:
    """Bulk, disk-free counterpart to extract_pages(): cuts every item's pages
    into an in-memory PDF (via _build_pdf_from_pages, which never touches disk)
    and packs every successfully-cut item into one ZIP, entirely in memory —
    no per-item file is ever written to user_dir, unlike extract_pages/batch_split.
    Lets a whole "select N ranges, then Download" workflow finish in one
    request instead of one /extract call per pending row.

    items: [{"pages": [...], "custom_name": "..."|None}, ...], in caller's order.

    Each zip entry is named "{i}_{filename}", i being the item's 0-based
    position in `items` and filename computed with extract_pages' exact same
    convention (sanitize_filename(custom_name)+'.pdf', or 'evrak.pdf') — so the
    caller recovers both "which request item" and its real, sanitized filename
    just by parsing entry names, no separate manifest needed.

    A single item's source vanishing (or exceeding the same 5000-page ceiling
    extract_pages enforces) only drops that item from the zip — same
    best-effort semantics as batch_split, never aborts the whole request.

    A single shared open_docs cache + ExitStack is used for the WHOLE batch
    (passed into every _build_pdf_from_pages call below) — items commonly
    share a source (e.g. 30 single-page pending rows all cut from the same
    one upload), and without this each item would reopen/reparse that same
    source PDF from scratch instead of reusing the handle already opened for
    an earlier item in this same request.

    Stored, not deflated: this zip is never saved by the user directly — the
    browser unzips it immediately as one step of assembling the real download
    (see document-builder.js's finalizePendingItems) — and PDF page content
    is typically already internally Flate-compressed, so re-compressing the
    outer zip mostly just burns CPU on both ends for little size benefit.
    """
    buf = io.BytesIO()
    with contextlib.ExitStack() as stack, zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        open_docs: dict = {}
        for i, item in enumerate(items):
            pages = item.get("pages") or []
            if not pages or len(pages) > 5000:
                logging.warning(f"build_finalize_zip: skipping item {i} (empty or over the page limit)")
                continue
            try:
                new_doc = _build_pdf_from_pages(pages, user_dir, open_docs=open_docs, stack=stack)
                try:
                    # Same garbage=4/clean/deflate reasoning as extract_pages — see
                    # its comment. Matters even more here: with deflate off, a
                    # bloated item isn't even masked by outer zip compression
                    # anymore now that the zip itself is ZIP_STORED.
                    pdf_bytes = new_doc.tobytes(garbage=4, clean=True, deflate=True)
                finally:
                    new_doc.close()
            except Exception:
                logging.warning(f"build_finalize_zip: skipping item {i}", exc_info=True)
                continue

            custom_name = item.get("custom_name")
            if custom_name:
                filename = f"{security.sanitize_filename(custom_name)}.pdf"
            else:
                filename = "evrak.pdf"

            zf.writestr(f"{i}_{filename}", pdf_bytes)

    return buf.getvalue()


def update_pages(file_id: str, pages: list[dict], user_dir: Path) -> int:
    """Rebuilds file_id's PDF content IN PLACE from the given ordered page list
    (reorder/rotate persisted from Batch Mode), keeping the same file_id.

    Since the pages typically self-reference file_id (a batch saving its own
    edited grid), the destination must not be truncated while still being read
    as a source: build the whole new document first, close every source handle,
    then atomically swap it in via a temp file + os.replace.

    Args:
        file_id: existing output's id
        pages: List of dicts e.g. [{"pdf_id": "id", "page_idx": 0, "rotation": 90}],
               in the final desired order.
        user_dir: the calling user's storage directory — file_id and every
            pdf_id in pages must resolve within it.

    Returns:
        actual_page_count after the rebuild.
    """
    if not pages:
        raise ValueError("Cannot update to an empty PDF.")

    if len(pages) > 5000:
        raise ValueError("To protect system performance, a maximum of 5000 pages can be updated at once.")

    dest_path = get_output_path(file_id, user_dir)

    with lock_file(dest_path):
        new_doc = _build_pdf_from_pages(pages, user_dir)
        actual_count = len(new_doc)

        tmp_name = None
        try:
            fd, tmp_name = tempfile.mkstemp(dir=user_dir, suffix=".pdf")
            os.close(fd)
            try:
                # Same garbage=4/clean/deflate reasoning as extract_pages.
                new_doc.save(tmp_name, garbage=4, clean=True, deflate=True)
            finally:
                new_doc.close()
            os.chmod(tmp_name, 0o644)  # match the permissions files normally get, not mkstemp's 0600
            os.replace(tmp_name, dest_path)  # atomic same-directory swap
        except Exception:
            if tmp_name:
                Path(tmp_name).unlink(missing_ok=True)
            raise

    return actual_count


def get_output_path(file_id: str, user_dir: Path) -> Path:
    """Returns the output PDF file path according to file_id."""
    if not is_valid_uuid(file_id):
        raise ValueError(f"Invalid File ID: {file_id}")

    try:
        return _resolve_path(file_id, user_dir)
    except FileNotFoundError:
        raise FileNotFoundError(f"Output file not found: {file_id}")

def get_pdf_info(file_id: str, user_dir: Path):
    """Returns (path, filename, page_count) for a given file_id."""
    if not is_valid_uuid(file_id):
        raise ValueError(f"Invalid File ID: {file_id}")

    # Check if original upload
    orig_path = user_dir / f"{file_id}_src.pdf"
    if orig_path.exists():
        _PATH_CACHE[file_id] = orig_path
        _touch(orig_path)
        metadata = get_metadata(file_id, user_dir)
        filename = metadata.get("original_filename", f"{file_id}.pdf")
        doc = pymupdf.open(str(orig_path))
        count = len(doc)
        doc.close()
        return orig_path, filename, count

    # Check if extracted batch
    try:
        path = _resolve_path(file_id, user_dir)
    except FileNotFoundError:
        raise FileNotFoundError(f"PDF not found for id: {file_id}")

    filename = path.name.split('_', 1)[1]
    doc = pymupdf.open(str(path))
    count = len(doc)
    doc.close()
    return path, filename, count


def rename_output(file_id: str, new_display_name: str, user_dir: Path) -> tuple[Path, str, dict]:
    """Renames the output file for file_id to a sanitized version of new_display_name,
    persists the display name in metadata, and updates the path cache.

    Returns:
        (new_path, new_filename, metadata)
    """
    path = get_output_path(file_id, user_dir)
    metadata = get_metadata(file_id, user_dir)
    metadata["custom_name"] = new_display_name
    save_metadata(file_id, metadata, user_dir)

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


def forget_cached_path(path: Path) -> None:
    """Drops any _PATH_CACHE entry pointing at path. Called by the cleanup sweep
    (main.py's _sweep_storage) right after secure_delete, so the cache doesn't
    accumulate one dead Path entry per file for the life of the process — a
    stale entry is otherwise harmless (_resolve_path already re-checks
    cached.exists() before trusting it) but never gets evicted on its own."""
    stale_ids = [k for k, v in _PATH_CACHE.items() if v == path]
    for k in stale_ids:
        _PATH_CACHE.pop(k, None)


def mark_delivered(file_id: str, user_dir: Path) -> None:
    """Called once a download has actually been triggered client-side (the
    browser was handed the bytes to save) — rather than deleting the file
    right then, this just resets its mtime to now, so the ordinary 15-minute
    sweep (_sweep_storage in main.py) is what actually removes it, on its own
    schedule. The gap is deliberate: a client only ever gets to say "I told
    the browser to save this," never "the browser definitely finished saving
    it" (there's no such completion event for a download triggered this way),
    so treating that signal as a countdown-start instead of an instant-delete
    trigger leaves a real margin for a slow connection or a stalled tab to
    still recover by re-fetching before the file is actually gone. Silently
    no-ops for a missing/invalid/other-user's file_id — best-effort,
    non-authoritative, same as the rest of this module's cleanup helpers.
    """
    try:
        path = get_output_path(file_id, user_dir)
    except (FileNotFoundError, ValueError):
        return

    now = time.time()
    os.utime(path, (now, now))

    json_path = user_dir / f"{file_id}.json"
    if json_path.exists():
        os.utime(json_path, (now, now))


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
