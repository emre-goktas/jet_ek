import fitz
import os
import tempfile
from pathlib import Path

def preprocess_to_pdf(filepath: Path, original_filename: str) -> tuple[Path, str]:
    """
    Detects the file type via magic bytes.
    If it is an image file, converts it to PDF via fitz.
    If it is already a PDF, verifies its integrity and returns bytes.
    
    Raises ValueError if unsupported or corrupted.
    
    Returns:
        (pdf_path, final_filename)
    """
    with open(filepath, "rb") as f:
        content = f.read(2048)
        
    if len(content) < 4:
        raise ValueError("Unsupported or corrupted file format. Please upload .pdf, .tiff, .jpeg, .jpg or .png.")
        
    # Magic Bytes Check
    if content.startswith(b"%PDF-"):
        filetype = "pdf"
    elif content.startswith(b"\xff\xd8"):
        filetype = "jpeg"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        filetype = "png"
    elif content.startswith(b"II*\x00") or content.startswith(b"MM\x00*"):
        filetype = "tiff"
    else:
        raise ValueError("Unsupported or corrupted file format. Please upload .pdf, .tiff, .jpeg, .jpg or .png.")
        
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
            
    # Image file, convert to pdf
    try:
        with fitz.open(str(filepath)) as doc:
            pdf_bytes = doc.convert_to_pdf()
        
        fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, 'wb') as f:
            f.write(pdf_bytes)
            
        return Path(temp_pdf_path), final_filename
    except Exception as e:
        raise ValueError(f"Could not convert image to pdf: {e}")
