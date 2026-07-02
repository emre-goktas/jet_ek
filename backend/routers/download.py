"""
Download endpoint — GET /download/{file_id}
Serves the generated PDF file as a download.
"""
import zipfile
import io
import copy
import re
from pathlib import Path
# pyrefly: ignore [missing-import]
import docx
# pyrefly: ignore [missing-import]
from docx.shared import Pt
# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException
# pyrefly: ignore [missing-import]
from fastapi.responses import FileResponse, StreamingResponse

from backend.services import pdf_service

router = APIRouter()


from backend.services.docx_service import generate_docx_from_template


@router.get("/download/{file_id}")
def download_pdf(file_id: str, ek_no: int = None):
    """Downloads the PDF file belonging to the specified file_id."""
    try:
        path = pdf_service.get_output_path(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found.")

    filename = path.name.split("_", 1)[1] if "_" in path.name else path.name
    
    if ek_no is not None:
        filename = f"{ek_no:02d}_{filename}"

    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=filename,
    )


@router.get("/download-zip")
def download_zip(file_ids: str):
    """Downloads a ZIP containing the PDFs specified by comma-separated file_ids along with an index list Word file."""
    if not file_ids:
        raise HTTPException(status_code=400, detail="No files specified.")

    ids = [fid.strip() for fid in file_ids.split(",") if fid.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="No valid file IDs specified.")

    # 1. Parse and extract metadata for each PDF file
    import pymupdf
    files_data = []
    
    for file_id in ids:
        try:
            path = pdf_service.get_output_path(file_id)
            filename = path.name.split("_", 1)[1] if "_" in path.name else path.name
            
            # Count the pages of the PDF file
            doc = pymupdf.open(str(path))
            page_count = len(doc)
            doc.close()
            
            # Parse the filename
            metadata = pdf_service.get_metadata(file_id)
            if "custom_name" in metadata:
                mahiyet = metadata["custom_name"].strip()
                ek_no = None
            else:
                m = re.match(r"^(\d+)_(.+)\.pdf$", filename, re.IGNORECASE)
                if m:
                    ek_no = int(m.group(1))
                    mahiyet = m.group(2)
                else:
                    mahiyet = filename.rsplit(".", 1)[0]
                    ek_no = None
                
            files_data.append({
                "file_id": file_id,
                "path": path,
                "filename": filename,
                "ek_no": ek_no,
                "mahiyet": mahiyet,
                "page_count": page_count
            })
        except Exception:
            # If a file doesn't exist or is not valid, skip it
            continue

    if not files_data:
        raise HTTPException(status_code=400, detail="No valid files found to package.")

    # Sort files_data by ek_no (assign sequential numbers for missing ones first)
    assigned_num = 1
    for f in files_data:
        if f["ek_no"] is None:
            f["ek_no"] = assigned_num
        assigned_num = max(assigned_num, f["ek_no"] + 1)
        
    files_data.sort(key=lambda x: x["ek_no"])

    # 2. Package into a ZIP file
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        # Add PDF files
        for f in files_data:
            zip_filename = f"{f['ek_no']:02d}_{f['filename']}"
            zip_file.write(f["path"], arcname=zip_filename)
            
        try:
            docx_bytes = generate_docx_from_template(files_data)
            zip_file.writestr("Ek Belgeler Listesi.docx", docx_bytes)
        except Exception as e:
            # If DOCX generation fails, log it but don't break the ZIP download
            import logging
            logging.error(f"Failed to generate Word index: {e}")

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": "attachment; filename=pdf_regulator_files.zip"}
    )


@router.get("/download-zip-numbered")
def download_zip_numbered(file_ids: str):
    """Downloads a ZIP containing the PDFs with EK numbers stamped on each page."""
    if not file_ids:
        raise HTTPException(status_code=400, detail="No files specified.")

    ids = [fid.strip() for fid in file_ids.split(",") if fid.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="No valid file IDs specified.")

    import pymupdf
    files_data = []
    
    for file_id in ids:
        try:
            path = pdf_service.get_output_path(file_id)
            filename = path.name.split("_", 1)[1] if "_" in path.name else path.name
            
            doc = pymupdf.open(str(path))
            page_count = len(doc)
            doc.close()
            
            metadata = pdf_service.get_metadata(file_id)
            if "custom_name" in metadata:
                mahiyet = metadata["custom_name"].strip()
                ek_no = None
            else:
                m = re.match(r"^(\d+)_(.+)\.pdf$", filename, re.IGNORECASE)
                if m:
                    ek_no = int(m.group(1))
                    mahiyet = m.group(2)
                else:
                    mahiyet = filename.rsplit(".", 1)[0]
                    ek_no = None
                
            files_data.append({
                "file_id": file_id,
                "path": path,
                "filename": filename,
                "ek_no": ek_no,
                "mahiyet": mahiyet,
                "page_count": page_count
            })
        except Exception:
            continue

    if not files_data:
        raise HTTPException(status_code=400, detail="No valid files found to package.")

    assigned_num = 1
    for f in files_data:
        if f["ek_no"] is None:
            f["ek_no"] = assigned_num
        assigned_num = max(assigned_num, f["ek_no"] + 1)
        
    files_data.sort(key=lambda x: x["ek_no"])

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for f in files_data:
            try:
                doc = pymupdf.open(str(f["path"]))
                for i in range(len(doc)):
                    page = doc[i]
                    text = f"EK: {f['ek_no']}/{i+1}"
                    # Add to top right corner (x=width-100, y=30)
                    x = max(10, page.rect.width - 90)
                    y = 30
                    point = pymupdf.Point(x, y)
                    page.insert_text(point, text, fontsize=12, color=(1, 0, 0), fontname="hebo")
                pdf_bytes = doc.tobytes()
                doc.close()
                zip_filename = f"{f['ek_no']:02d}_{f['filename']}"
                zip_file.writestr(zip_filename, pdf_bytes)
            except Exception as e:
                import logging
                logging.error(f"Failed to stamp PDF {f['filename']}: {e}")
                # Fallback to writing unmodified if stamping fails
                zip_filename = f"{f['ek_no']:02d}_{f['filename']}"
                zip_file.write(f["path"], arcname=zip_filename)
            
        try:
            docx_bytes = generate_docx_from_template(files_data)
            zip_file.writestr("Ek Belgeler Listesi.docx", docx_bytes)
        except Exception as e:
            import logging
            logging.error(f"Failed to generate Word index: {e}")

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": "attachment; filename=pdf_regulator_files.zip"}
    )
