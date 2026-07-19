def save_upload(file_path: Path, original_name: str, user_dir: Path) -> tuple[str, int]:
    """Saves the uploaded PDF file to storage with a unique pdf_id."""
    import shutil
    pdf_id = uuid.uuid4().hex
    dest = user_dir / f"{pdf_id}_src.pdf"

    try:
        doc = pymupdf.open(str(file_path))
    except Exception:
        raise ValueError("Corrupted PDF file. Please upload a valid document.")
    page_count = len(doc)
    tmp_name = None
    try:
        with lock_file(dest):
            fd, tmp_name = tempfile.mkstemp(dir=user_dir, suffix=".pdf")
            os.close(fd)
            try:
                # OPTİMİZASYON: garbage=4 yerine garbage=3 + linear=True kullanıldı.
                # pdf.js için gereken sayfa ağacı düzeltmesi ve doğrusallaştırma korunurken 
                # işlemci yükü kısıtlı donanımlar için dramatik ölçüde düşürüldü.
                doc.save(tmp_name, garbage=3, clean=True, deflate=True, linear=True)
            finally:
                doc.close()
            os.chmod(tmp_name, 0o644)
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


def extract_pages(
    pages: list[dict],
    user_dir: Path,
    custom_name: str | None = None,
    open_docs: dict | None = None,
    stack: contextlib.ExitStack | None = None,
) -> tuple[str, str, int]:
    """Extracts the specified list of pages from potentially multiple PDFs."""
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
    
    # OPTİMİZASYON: "24 MB yükleyip 900 MB alma" sorununu çözmek için garbage=4 yerine 
    # subset_fonts() + garbage=3 kombinasyonu getirildi. Fontlar güvenle budanır, 
    # işlemci kilitlenmez, dosya boyutu şişmez.
    if actual_count > 0:
        new_doc.init_doc()
        with contextlib.suppress(Exception):
            new_doc.subset_fonts()

    new_doc.save(str(out_path), garbage=3, deflate=True, linear=True)
    new_doc.close()
    _PATH_CACHE[file_id] = out_path

    return file_id, filename, actual_count


def build_finalize_zip(items: list[dict], user_dir: Path) -> bytes:
    """Bulk, disk-free counterpart to extract_pages()."""
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
                    # OPTİMİZASYON: ZIP_STORED olduğu için in-memory şişmeyi önleyen font budama 
                    # ve garbage=3 ayarları buraya da entegre edildi.
                    if len(new_doc) > 0:
                        new_doc.init_doc()
                        with contextlib.suppress(Exception):
                            new_doc.subset_fonts()
                    pdf_bytes = new_doc.tobytes(garbage=3, deflate=True, linear=True)
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
    """Rebuilds file_id's PDF content IN PLACE from the given ordered page list."""
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
                # OPTİMİZASYON: In-place güncellemelerde batch grid kaydederken hız ve boyut dengesi.
                if actual_count > 0:
                    new_doc.init_doc()
                    with contextlib.suppress(Exception):
                        new_doc.subset_fonts()
                new_doc.save(tmp_name, garbage=3, deflate=True, linear=True)
            finally:
                new_doc.close()
            os.chmod(tmp_name, 0o644)
            os.replace(tmp_name, dest_path)
        except Exception:
            if tmp_name:
                Path(tmp_name).unlink(missing_ok=True)
            raise

    return actual_count