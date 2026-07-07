import json
import os
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pymupdf
from google import genai
from dotenv import load_dotenv

load_dotenv()

from backend.services.pdf_service import get_pdf_info, rename_output

DATA_DIR = Path(__file__).parent.parent / "data"
LOG_FILE_PATH = DATA_DIR / "ai_logs.jsonl"

_client = None

def get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Gemini API key is missing. Please set GEMINI_API_KEY in .env file.")

        _client = genai.Client(api_key=api_key)
    return _client

def _append_log(entry: dict):
    """Appends one JSON object per line (JSONL) so a partial/failed write only
    corrupts the last entry instead of the entire log history."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def log_ai_rename(file_id: str, original_name: str, new_name: str):
    """Appends the AI renaming result to the log."""
    _append_log({
        "file_id": file_id,
        "original_name": original_name,
        "new_name": new_name,
    })

def log_ai_error(file_id: str, error_msg: str):
    """Appends an AI error to the log."""
    _append_log({
        "file_id": file_id,
        "error": error_msg,
    })

def _extract_first_page(path) -> tuple[str, bool]:
    """Extracts the first page of the PDF at path into a new temporary PDF file.
    Returns (temp_path, is_landscape) — is_landscape reflects the page's current
    /Rotate (page.rect is PyMuPDF's post-rotation, visual size), so the caller can
    warn the AI about orientation via the prompt instead of us guessing a rotation
    direction: a landscape page is geometrically ambiguous (genuinely landscape
    content vs. a portrait page scanned sideways in either direction) with no
    reliable signal to pick a correction automatically — a wrong guess would
    silently make a fine page worse. Caller is responsible for deleting the temp
    file."""
    fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    src_doc = pymupdf.open(str(path))
    try:
        temp_doc = pymupdf.open()
        temp_doc.insert_pdf(src_doc, from_page=0, to_page=0)
        rect = temp_doc[0].rect
        is_landscape = rect.width > rect.height
        temp_doc.save(temp_pdf_path)
        temp_doc.close()
    finally:
        src_doc.close()
    return temp_pdf_path, is_landscape

LANDSCAPE_HINT = (
    " NOT: Bu belgenin ilk sayfası yatay (yan) taranmış olabilir. Sayfanın "
    "yönüne veya metnin yatay/dikey görünmesine takılmadan içeriği dikkatlice "
    "incele ve ona göre isim üret."
)

RENAME_PROMPT = (
    "Bu belge resmi bir kurum evrakı, bir şirkete ait doküman veya şahsi bir belgedir. "
    "Lütfen belgeyi incele ve aşağıdaki kurallara göre çok kısa ve öz bir dosya adı üret:\n"
    "1. Eğer belgede Kurum Adı, Tarih, Sayı ve Konu gibi bilgiler netse: "
    "'[Kurum Adı] nın,nün(gibi sonekler) [Tarih] tarihli [Sayı] sayılı [Konu] konulu yazısı' formatında oluştur.\n"
    "2. Eğer resmi bilgiler yoksa belgenin ana başlığını ve varsa altındaki imzanın kime ait olduğunu tespit et. Belge bir "
    "kişiye veya firmaya aitse: '[Kişi/Firma/Unvan Adı] [Belge Başlığı/Türü]' formatında belirt.\n"
    "DİKKAT: SADECE oluşturduğun dosya adını döndür. Hiçbir açıklama yapma ve "
    ".pdf uzantısı ekleme. (Örn: 'SGK 12.05.2023 Tarihli 1234 Sayılı İşe Giriş Bildirgesi' veya 'Ahmet Yılmaz İfade Tutanağı')."
)

RENAME_BATCH_PROMPT = (
    "Burada birden fazla belgenin ilk sayfası var. Her belgeden önce o belgenin 'Document ID'si verilmiştir.\n"
    "Lütfen her bir belgeyi incele ve aşağıdaki kurallara göre çok kısa ve öz bir dosya adı üret:\n"
    "1. Eğer belgede Kurum Adı, Tarih, Sayı ve Konu gibi bilgiler netse: "
    "'[Kurum Adı] nın,nün(gibi sonekler) [Tarih] tarihli [Sayı] sayılı [Konu] konulu yazısı' formatında oluştur.\n"
    "2. Eğer resmi bilgiler yoksa belgenin ana başlığını ve varsa altındaki imzanın kime ait olduğunu tespit et. Belge bir "
    "kişiye veya firmaya aitse: '[Kişi/Firma/Unvan Adı] [Belge Başlığı/Türü]' formatında belirt.\n"
    "DİKKAT: Yalnızca geçerli bir JSON objesi döndür. JSON anahtarları (keys) verdiğim 'Document ID' olmalı, "
    "değerler (values) ise senin ürettiğin dosya adı olmalıdır. Hiçbir açıklama yapma ve json tagı kullanmadan sadece json objesini döndür."
)

def _clean_ai_name(new_name: str) -> str:
    new_name = str(new_name).replace('"', '').replace("'", '').replace('\n', ' ').strip()
    if new_name.lower().endswith('.pdf'):
        new_name = new_name[:-4].strip()
    return new_name

def jet_rename_pdf(file_id: str) -> str:
    """
    Extracts the first page of the given PDF, sends it to Gemini 2.5 Flash,
    gets a concise filename, renames the file on disk, logs it, and returns the new name.
    """
    gemini_file = None
    temp_pdf_path = None
    client = None
    try:
        client = get_client()

        # 1. Get the target PDF path
        path, original_filename, _ = get_pdf_info(file_id)

        # 2. Extract only the first page into a temporary PDF to save tokens/time
        temp_pdf_path, is_landscape = _extract_first_page(path)

        # 3. Upload the temporary PDF to Gemini
        gemini_file = client.files.upload(file=temp_pdf_path, config={"mime_type": "application/pdf"})

        # 4. Generate content
        prompt = RENAME_PROMPT + LANDSCAPE_HINT if is_landscape else RENAME_PROMPT
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[gemini_file, prompt]
        )

        new_name = _clean_ai_name(response.text.strip())

        # 5. Rename the physical file and metadata
        new_path, new_filename, metadata = rename_output(file_id, new_name)
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
    finally:
        if temp_pdf_path and os.path.exists(temp_pdf_path):
            try:
                os.remove(temp_pdf_path)
            except Exception:
                pass
        # Always attempt cloud cleanup, regardless of whether generate_content succeeded.
        if gemini_file is not None:
            try:
                client.files.delete(name=gemini_file.name)
            except Exception:
                pass

def jet_rename_pdf_batch(file_ids: list[str]) -> dict:
    """
    Extracts the first page of multiple PDFs, uploads them to Gemini (in parallel),
    requests structured JSON for all renames at once.
    Returns a dict mapping file_id to { "filename": ..., "label": ..., "page_count": ... }
    """
    if not file_ids:
        return {}

    uploaded_files = []
    temp_files = []

    try:
        try:
            client = get_client()
        except Exception as e:
            for file_id in file_ids:
                log_ai_error(file_id, f"Failed to initialize Gemini client: {e}")
            raise

        def _prepare_one(file_id: str):
            path, original_filename, _ = get_pdf_info(file_id)
            temp_pdf_path, is_landscape = _extract_first_page(path)
            temp_files.append(temp_pdf_path)

            gemini_file = client.files.upload(file=temp_pdf_path, config={"mime_type": "application/pdf"})
            uploaded_files.append(gemini_file)
            return original_filename, gemini_file, is_landscape

        # 1. Prepare all files (first-page extraction + Gemini upload) in parallel
        contents = []
        file_info_map = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_id = {executor.submit(_prepare_one, fid): fid for fid in file_ids}
            for future, file_id in future_to_id.items():
                try:
                    original_filename, gemini_file, is_landscape = future.result()
                    file_info_map[file_id] = {"original_filename": original_filename}
                    marker = f"Document ID: {file_id}"
                    if is_landscape:
                        marker += LANDSCAPE_HINT
                    contents.append(marker)
                    contents.append(gemini_file)
                except Exception as e:
                    log_ai_error(file_id, f"Failed to prepare batch file: {e}")

        if not contents:
            return {}

        # 2. Generate content
        contents.append(RENAME_BATCH_PROMPT)

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
        except json.JSONDecodeError:
            raise ValueError(f"Failed to parse JSON from AI response: {text}")

        results = {}
        # 4. Apply renames
        for file_id, new_name in renames.items():
            if file_id not in file_info_map:
                continue

            try:
                new_name = _clean_ai_name(new_name)
                new_path, new_filename, metadata = rename_output(file_id, new_name)
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
                except Exception:
                    pass
        for gfile in uploaded_files:
            try:
                client.files.delete(name=gfile.name)
            except Exception:
                pass
