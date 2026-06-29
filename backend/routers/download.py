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


import base64

TEMPLATE_BASE64 = "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"


def create_ek_belgeler_docx(files_data: list[dict]) -> bytes:
    """Generates the DOCX list from the embedded template docx."""
    template_bytes = base64.b64decode(TEMPLATE_BASE64)
    doc = docx.Document(io.BytesIO(template_bytes))
    
    # Table 0 is the ek belgeler table
    tbl = doc.tables[0]
    
    # Keep copies of the blueprint row XML elements before changing the table
    # Index 1 is the first data row.
    # Index -1 (which is 17 in the template) is the total row.
    row_blueprint = copy.deepcopy(tbl.rows[1]._tr)
    total_blueprint = copy.deepcopy(tbl.rows[-1]._tr)
    
    # Delete all rows except the header row (index 0)
    while len(tbl.rows) > 1:
        tbl._tbl.remove(tbl.rows[-1]._tr)
        
    # Helper to set text in a cell with Times New Roman 12pt and preserve alignment
    def set_cell_text(cell, text, bold=False):
        p = cell.paragraphs[0]
        # Clear existing runs
        for run in list(p.runs):
            p._p.remove(run._r)
        # Add new run
        run = p.add_run(text)
        run.font.name = 'Times New Roman'
        run.font.size = Pt(12)
        run.bold = bold
        
    # Write data rows
    total_pages = 0
    for f in files_data:
        tr_copy = copy.deepcopy(row_blueprint)
        tbl._tbl.append(tr_copy)
        new_row = docx.table._Row(tr_copy, tbl)
        
        # Populate cells
        set_cell_text(new_row.cells[0], str(f["ek_no"]), bold=True)
        set_cell_text(new_row.cells[1], f["mahiyet"])
        set_cell_text(new_row.cells[2], str(f["page_count"]))
        set_cell_text(new_row.cells[3], "")
        set_cell_text(new_row.cells[4], "F")
        
        total_pages += f["page_count"]
        
    # Append total row
    tr_total = copy.deepcopy(total_blueprint)
    tbl._tbl.append(tr_total)
    new_total_row = docx.table._Row(tr_total, tbl)
    
    set_cell_text(new_total_row.cells[0], "")
    set_cell_text(new_total_row.cells[1], "TOPLAM", bold=True)
    set_cell_text(new_total_row.cells[2], str(total_pages), bold=True)
    set_cell_text(new_total_row.cells[3], "")
    set_cell_text(new_total_row.cells[4], "")
    
    # Calculate start and end numbers for the paragraph
    if files_data:
        start_num = files_data[0]["ek_no"]
        end_num = files_data[-1]["ek_no"]
    else:
        start_num = 1
        end_num = 1
        
    # Update paragraph containing summary statement
    p_target = None
    for p in doc.paragraphs:
        if "ek belgeler listesinde" in p.text:
            p_target = p
            break
            
    if p_target:
        # Re-set paragraph text keeping the tab prefix
        p_target.text = f"\t15/12/2025-414144/13/İR/13 tarih ve sayılı raporun birinci nüshasındaki belgelere göre düzenlenen bu ek belgeler listesinde, ({start_num}-{end_num}) numaraları altında toplam ({total_pages}) sayfadan ibaret belgeler belirtilmiştir."
        for run in p_target.runs:
            run.font.name = 'Times New Roman'
            run.font.size = Pt(12)
            
    doc_io = io.BytesIO()
    doc.save(doc_io)
    return doc_io.getvalue()


@router.get("/download/{file_id}")
def download_pdf(file_id: str):
    """Downloads the PDF file belonging to the specified file_id."""
    try:
        path = pdf_service.get_output_path(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=path.name.split("_", 1)[1] if "_" in path.name else path.name,
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
            # Match digits followed by an underscore
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
            zip_file.write(f["path"], arcname=f["filename"])
            
        # 3. Generate and add Ek Belgeler Listesi.docx
        try:
            docx_bytes = create_ek_belgeler_docx(files_data)
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
                zip_file.writestr(f["filename"], pdf_bytes)
            except Exception as e:
                import logging
                logging.error(f"Failed to stamp PDF {f['filename']}: {e}")
                # Fallback to writing unmodified if stamping fails
                zip_file.write(f["path"], arcname=f["filename"])
            
        try:
            docx_bytes = create_ek_belgeler_docx(files_data)
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
