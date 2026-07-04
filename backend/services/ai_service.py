import json
import os
import pymupdf
import tempfile
from pathlib import Path
from google import genai

from backend.services.pdf_service import get_pdf_info, get_output_path, get_metadata, save_metadata, STORAGE_DIR

DATA_DIR = Path(__file__).parent.parent / "data"
API_KEY_PATH = DATA_DIR / "gemini_api_key"
LOG_FILE_PATH = DATA_DIR / "ai_logs.json"

_client = None

def get_client():
    global _client
    if _client is None:
        if not API_KEY_PATH.exists():
            raise FileNotFoundError("Gemini API key file not found at backend/data/gemini_api_key")
        with open(API_KEY_PATH, "r", encoding="utf-8") as f:
            api_key = f.read().strip()
        if not api_key:
            raise ValueError("Gemini API key is empty")
        _client = genai.Client(api_key=api_key)
    return _client

def log_ai_rename(file_id: str, original_name: str, new_name: str):
    """Appends the AI renaming result to a JSON log file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logs = []
    if LOG_FILE_PATH.exists():
        try:
            with open(LOG_FILE_PATH, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except json.JSONDecodeError:
            logs = []
            
    logs.append({
        "file_id": file_id,
        "original_name": original_name,
        "new_name": new_name
    })
    
    with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)

def log_ai_error(file_id: str, error_msg: str):
    """Appends an AI error to a JSON log file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logs = []
    if LOG_FILE_PATH.exists():
        try:
            with open(LOG_FILE_PATH, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except json.JSONDecodeError:
            logs = []
            
    logs.append({
        "file_id": file_id,
        "error": error_msg
    })
    
    with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)

def jet_rename_pdf(file_id: str) -> str:
    """
    Extracts the first page of the given PDF, sends it to Gemini 1.5 Flash,
    gets a concise filename, renames the file on disk, logs it, and returns the new name.
    """
    try:
        client = get_client()
        
        # 1. Get the target PDF path
        path, original_filename, _ = get_pdf_info(file_id)
        
        # 2. Extract only the first page into a temporary PDF to save tokens/time
        fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf")
        try:
            os.close(fd)
            src_doc = pymupdf.open(str(path))
            temp_doc = pymupdf.open()
            temp_doc.insert_pdf(src_doc, from_page=0, to_page=0)
            temp_doc.save(temp_pdf_path)
            temp_doc.close()
            src_doc.close()
            
            # 3. Upload the temporary PDF to Gemini
            gemini_file = client.files.upload(file=temp_pdf_path, config={"mime_type": "application/pdf"})
            
            # 4. Generate content
            prompt = (
                "Bu belge resmi bir kurum evrakı, bir şirkete ait doküman veya şahsi bir belgedir. "
                "Lütfen belgeyi incele ve aşağıdaki kurallara göre çok kısa ve öz bir dosya adı üret:\n"
                "1. Eğer belgede Kurum Adı, Tarih, Sayı ve Konu gibi bilgiler netse: "
                "'[Kurum Adı] nın,nün(gibi sonekler) [Tarih] tarihli [Sayı] sayılı [Konu] konulu yazısı' formatında oluştur.\n"
                "2. Eğer resmi bilgiler yoksa belgenin ana başlığını ve varsa altındaki imzanın kime ait olduğunu tespit et. Belge bir "
                "kişiye veya firmaya aitse: '[Kişi/Firma/Unvan Adı] [Belge Başlığı/Türü]' formatında belirt.\n"
                "DİKKAT: SADECE oluşturduğun dosya adını döndür. Hiçbir açıklama yapma ve "
                ".pdf uzantısı ekleme. (Örn: 'SGK 12.05.2023 Tarihli 1234 Sayılı İşe Giriş Bildirgesi' veya 'Ahmet Yılmaz İfade Tutanağı')."
            )
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[gemini_file, prompt]
            )
            
            # Parse response
            new_name = response.text.strip()
            # Clean up the name (remove quotes, newlines, extension if any)
            new_name = new_name.replace('"', '').replace("'", '').replace('\n', ' ').strip()
            if new_name.lower().endswith('.pdf'):
                new_name = new_name[:-4].strip()
                
            # Optional: delete file from Gemini to save space (since it's a one-off)
            try:
                client.files.delete(name=gemini_file.name)
            except Exception:
                pass
                
        finally:
            if os.path.exists(temp_pdf_path):
                try:
                    os.remove(temp_pdf_path)
                except Exception:
                    pass
                    
        # 5. Rename the physical file and metadata
        path = get_output_path(file_id)
        metadata = get_metadata(file_id)
        metadata["custom_name"] = new_name
        save_metadata(file_id, metadata)
        
        clean_name = new_name.replace('\n', ' ').replace('\r', '').replace('/', '-').replace('\\', '-').replace(':', '-').strip()
        if len(clean_name) > 150:
            clean_name = clean_name[:150].strip()
        
        encoded = clean_name.encode('utf-8')
        if len(encoded) > 210:
            clean_name = encoded[:210].decode('utf-8', 'ignore').strip()
            
        new_filename = f"{clean_name}.pdf"
        new_path = path.parent / f"{file_id}_{new_filename}"
        if new_path != path:
            path.rename(new_path)
            
        label = metadata.get("label", "PDF")
        
        # Get page count
        doc = pymupdf.open(str(new_path))
        page_count = len(doc)
        doc.close()
        
        # 6. Log the change
        log_ai_rename(file_id, original_filename, new_name)
        
        return new_filename, label, page_count
        
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        log_ai_error(file_id, err)
        raise ValueError(f"Failed to rename file: {e}")

def jet_rename_pdf_batch(file_ids: list[str]) -> dict:
    """
    Extracts the first page of multiple PDFs, uploads them to Gemini,
    requests structured JSON for all renames at once.
    Returns a dict mapping file_id to { "filename": ..., "label": ..., "page_count": ... }
    """
    if not file_ids:
        return {}
        
    client = get_client()
    uploaded_files = []
    temp_files = []
    
    try:
        # 1. Prepare all files
        contents = []
        file_info_map = {}
        for file_id in file_ids:
            try:
                path, original_filename, _ = get_pdf_info(file_id)
                file_info_map[file_id] = {
                    "path": path,
                    "original_filename": original_filename
                }
                
                # Extract first page
                fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf")
                os.close(fd)
                temp_files.append(temp_pdf_path)
                
                src_doc = pymupdf.open(str(path))
                temp_doc = pymupdf.open()
                temp_doc.insert_pdf(src_doc, from_page=0, to_page=0)
                temp_doc.save(temp_pdf_path)
                temp_doc.close()
                src_doc.close()
                
                # Upload to Gemini
                gemini_file = client.files.upload(file=temp_pdf_path, config={"mime_type": "application/pdf"})
                uploaded_files.append(gemini_file)
                
                contents.append(f"Document ID: {file_id}")
                contents.append(gemini_file)
            except Exception as e:
                log_ai_error(file_id, f"Failed to prepare batch file: {e}")
                continue
                
        if not contents:
            return {}
            
        # 2. Generate content
        prompt = (
            "Burada birden fazla belgenin ilk sayfası var. Her belgeden önce o belgenin 'Document ID'si verilmiştir.\n"
            "Lütfen her bir belgeyi incele ve aşağıdaki kurallara göre çok kısa ve öz bir dosya adı üret:\n"
            "1. Eğer belgede Kurum Adı, Tarih, Sayı ve Konu gibi bilgiler netse: "
            "'[Kurum Adı] nın,nün(gibi sonekler) [Tarih] tarihli [Sayı] sayılı [Konu] konulu yazısı' formatında oluştur.\n"
            "2. Eğer resmi bilgiler yoksa belgenin ana başlığını ve varsa altındaki imzanın kime ait olduğunu tespit et. Belge bir "
            "kişiye veya firmaya aitse: '[Kişi/Firma/Unvan Adı] [Belge Başlığı/Türü]' formatında belirt.\n"
            "DİKKAT: Yalnızca geçerli bir JSON objesi döndür. JSON anahtarları (keys) verdiğim 'Document ID' olmalı, "
            "değerler (values) ise senin ürettiğin dosya adı olmalıdır. Hiçbir açıklama yapma ve json tagı kullanmadan sadece json objesini döndür."
        )
        contents.append(prompt)
        
        # Note: We can enforce JSON output via generation_config but standard prompt works fine for simple dicts
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents
        )
        
        # 3. Parse JSON response
        text = response.text.strip()
        if text.startswith('```json'):
            text = text[7:]
        if text.endswith('```'):
            text = text[:-3]
        text = text.strip()
        
        try:
            renames = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON from AI response: {text}")
            
        results = {}
        # 4. Apply renames
        for file_id, new_name in renames.items():
            if file_id not in file_info_map:
                continue
                
            try:
                # Clean up the name
                new_name = str(new_name).replace('"', '').replace("'", '').replace('\n', ' ').strip()
                if new_name.lower().endswith('.pdf'):
                    new_name = new_name[:-4].strip()
                    
                path = get_output_path(file_id)
                metadata = get_metadata(file_id)
                metadata["custom_name"] = new_name
                save_metadata(file_id, metadata)
                
                clean_name = new_name.replace('\n', ' ').replace('\r', '').replace('/', '-').replace('\\', '-').replace(':', '-').strip()
                if len(clean_name) > 150:
                    clean_name = clean_name[:150].strip()
                
                encoded = clean_name.encode('utf-8')
                if len(encoded) > 210:
                    clean_name = encoded[:210].decode('utf-8', 'ignore').strip()
                    
                new_filename = f"{clean_name}.pdf"
                new_path = path.parent / f"{file_id}_{new_filename}"
                if new_path != path:
                    path.rename(new_path)
                    
                label = metadata.get("label", "PDF")
                doc = pymupdf.open(str(new_path))
                page_count = len(doc)
                doc.close()
                
                original_filename = file_info_map[file_id]["original_filename"]
                log_ai_rename(file_id, original_filename, new_name)
                
                results[file_id] = {
                    "filename": new_filename,
                    "label": label,
                    "page_count": page_count
                }
            except Exception as inner_e:
                log_ai_error(file_id, f"Failed applying rename: {inner_e}")
                
        return results
        
    finally:
        for tmp in temp_files:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except:
                    pass
        for gfile in uploaded_files:
            try:
                client.files.delete(name=gfile.name)
            except:
                pass
