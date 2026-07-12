import fitz
import logging
import os
import tempfile
from pathlib import Path

def preprocess_to_pdf(filepath: Path, original_filename: str) -> tuple[Path, str]:
    """
    Detects the file type via magic bytes.
    If it is a PDF, verifies its integrity and returns it unchanged.
    If it is a TIFF, converts it to PDF via fitz.
    JPEG/PNG are no longer accepted here: the browser converts those to PDF
    client-side before upload (see frontend/static/js/document-builder.js),
    so any image reaching this point client-side would already be a PDF.

    Raises ValueError if unsupported or corrupted.

    Returns:
        (pdf_path, final_filename)
    """
    with open(filepath, "rb") as f:
        content = f.read(2048)

    if len(content) < 4:
        raise ValueError("Unsupported or corrupted file format. Please upload .pdf or .tiff.")

    # Magic Bytes Check
    if content.startswith(b"%PDF-"):
        filetype = "pdf"
    elif content.startswith(b"II*\x00") or content.startswith(b"MM\x00*"):
        filetype = "tiff"
    else:
        raise ValueError(
            "Unsupported or corrupted file format. Please upload .pdf or .tiff "
            "(JPEG/PNG are converted to PDF in the browser before upload)."
        )

    base_name = os.path.splitext(original_filename)[0]
    final_filename = f"{base_name}.pdf"

    if filetype == "pdf":
        try:
            # Parse only to check if it is corrupted
            with fitz.open(str(filepath)) as doc:
                pass
            return filepath, final_filename
        except Exception:
            raise ValueError("Corrupted PDF file. Please upload a valid document.")

    # TIFF file, convert to pdf
    try:
        with fitz.open(str(filepath)) as doc:
            pdf_bytes = doc.convert_to_pdf()

        fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, 'wb') as f:
            f.write(pdf_bytes)

        return Path(temp_pdf_path), final_filename
    except Exception:
        logging.exception("TIFF to PDF conversion failed")
        raise ValueError("Could not convert TIFF to PDF. The file may be corrupted.")
