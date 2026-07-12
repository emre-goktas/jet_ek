import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import pymupdf
from google import genai

from backend.services import db_service
from backend.services.pdf_service import get_pdf_info, rename_output, user_storage_dir

def get_client(api_key: str):
    """BYOK: each request brings its own Gemini key (header-passthrough from the
    browser's localStorage) — never persisted to disk/DB and never cached across
    requests, since a shared server-side key would let one user's usage exhaust
    another's quota/billing."""
    if not api_key:
        raise ValueError("Gemini API key is missing.")
    return genai.Client(api_key=api_key)

def log_ai_rename(user_email: str, file_id: str, original_name: str, new_name: str, duration_ms: int, batch_size: int = 1):
    """Records a successful AI rename in the ai_rename_logs table."""
    db_service.log_gemini_rename_safe(
        user_email, file_id, original_name, new_name,
        success=True, duration_ms=duration_ms, batch_size=batch_size,
    )

def log_ai_error(user_email: str, file_id: str, error_msg: str, duration_ms: int | None = None, batch_size: int = 1):
    """Records a failed AI rename attempt in the ai_rename_logs table."""
    db_service.log_gemini_rename_safe(
        user_email, file_id, None, None,
        success=False, error_message=error_msg, duration_ms=duration_ms, batch_size=batch_size,
    )

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
    "Bu belge resmi bir kurum evrakı, bir şirkete ait doküman, dilekçe, kayıt ibraz yazısı veya şahsi bir belgedir. "
    "Belgenin header bölümünde Belgeyi hangi kurumun yazdığını, hitap kısmında(tarih sayıdan sonra sayfaya ortalanmış başlık gibi) kime yazıldığını tespit eedebilirsin"
    "Lütfen belgeyi incele ve aşağıdaki kurallara göre resmi ve hukuki yazışma diline uygun olarak dosya adı(evrakın mahiyeti) üret:\n"
    "1. Eğer belgede Kurum Adı, Tarih, Sayı ve Konu gibi bilgiler netse: "
    "'[Kurum Adı] nın,nün(gibi sonekler) [Kurum adı] ne, na(gibi ekler) [Tarih] tarihli [Sayı] sayılı [Konu] konulu yazısı' formatında oluştur.\n"
    "Örneğin [X] Başkanlığının [y] müdürlüğüne [tarih]li [sayı]lı [konulu] yazısı"
    "2. Eğer resmi bilgiler yoksa belgenin ana başlığını ve varsa altındaki imzanın kime ait olduğunu tespit et. Belge bir "
    "kişiye veya firmaya aitse: '[Kişi/Firma/Unvan Adı] [Belge Başlığı/Türü]' formatında belirt.\n"
    "DİKKAT: SADECE oluşturduğun dosya adını döndür. Hiçbir açıklama yapma ve "
    ".pdf uzantısı ekleme. (Örn: 'SGK 12.05.2023 Tarihli 1234 Sayılı İşe Giriş Bildirgesi' veya 'Ahmet Yılmaz İfade Tutanağı')."
)

RENAME_BATCH_PROMPT = (
    "Burada birden fazla belgenin ilk sayfası var. Her belgeden önce o belgenin 'Document ID'si verilmiştir.\n"
    "Lütfen her bir belgeyi incele ve aşağıdaki kurallara göre resmi ve hukuki yazışma diline uygun olarak dosya adı(evrakın mahiyeti) üret:\n"
    ""Belgenin header bölümünde Belgeyi hangi kurumun yazdığını, hitap kısmında(tarih sayıdan sonra sayfaya ortalanmış başlık gibi) kime yazıldığını tespit eedebilirsin"
    "1. Eğer belgede Kurum Adı, Tarih, Sayı ve Konu gibi bilgiler netse: "
     "'[Kurum Adı] nın,nün(gibi sonekler) [Kurum adı] ne, na(gibi ekler) [Tarih] tarihli [Sayı] sayılı [Konu] konulu yazısı' formatında oluştur.\n"
    "Örneğin [X] Başkanlığının [y] müdürlüğüne [tarih]li [sayı]lı [konu]lu yazısı"
    "2. Eğer resmi bilgiler yoksa belgenin ana başlığını ve varsa altındaki imzanın kime ait olduğunu tespit et. Belge bir "
    "kişiye veya firmaya aitse: '[Kişi/Firma/Unvan Adı] [Belge Başlığı/Türü]' formatında belirt.\n"
    "DİKKAT: Yalnızca geçerli bir JSON objesi döndür. JSON anahtarları (keys) verdiğim 'Document ID' olmalı, "
    "değerler (values) ise senin ürettiğin dosya adı olmalıdır. Hiçbir açıklama yapma ve json tagı kullanmadan sadece json objesini döndür."

def _clean_ai_name(new_name: str) -> str:
    new_name = str(new_name).replace('"', '').replace("'", '').replace('\n', ' ').strip()
    if new_name.lower().endswith('.pdf'):
        new_name = new_name[:-4].strip()
    return new_name

def jet_rename_pdf(file_id: str, api_key: str, user_email: str) -> str:
    """
    Extracts the first page of the given PDF, sends it to Gemini Flash,
    gets a concise filename, renames the file on disk, logs it, and returns the new name.
    """
    gemini_file = None
    temp_pdf_path = None
    client = None
    t0 = time.monotonic()
    try:
        client = get_client(api_key)
        user_dir = user_storage_dir(user_email)

        # 1. Get the target PDF path
        path, original_filename, _ = get_pdf_info(file_id, user_dir)

        # 2. Extract only the first page into a temporary PDF to save tokens/time
        temp_pdf_path, is_landscape = _extract_first_page(path)

        # 3. Upload the temporary PDF to Gemini
        gemini_file = client.files.upload(file=temp_pdf_path, config={"mime_type": "application/pdf"})

        # 4. Generate content
        prompt = RENAME_PROMPT + LANDSCAPE_HINT if is_landscape else RENAME_PROMPT
        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=[gemini_file, prompt]
        )
        duration_ms = round((time.monotonic() - t0) * 1000)

        new_name = _clean_ai_name(response.text.strip())

        # 5. Rename the physical file and metadata
        new_path, new_filename, metadata = rename_output(file_id, new_name, user_dir)
        label = metadata.get("label", "PDF")

        # Get page count
        doc = pymupdf.open(str(new_path))
        page_count = len(doc)
        doc.close()

        # 6. Log the change
        log_ai_rename(user_email, file_id, original_filename, new_name, duration_ms)

        return new_filename, label, page_count, metadata.get("custom_name", "")

    except Exception as e:
        import traceback
        err = traceback.format_exc()
        log_ai_error(user_email, file_id, err, duration_ms=round((time.monotonic() - t0) * 1000))
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

def jet_rename_pdf_batch(file_ids: list[str], api_key: str, user_email: str) -> dict:
    """
    Extracts the first page of multiple PDFs, uploads them to Gemini (in parallel),
    requests structured JSON for all renames at once.
    Returns a dict mapping file_id to { "filename": ..., "label": ..., "page_count": ... }
    """
    if not file_ids:
        return {}

    uploaded_files = []
    temp_files = []
    batch_size = len(file_ids)
    t0 = time.monotonic()
    user_dir = user_storage_dir(user_email)

    try:
        try:
            client = get_client(api_key)
        except Exception as e:
            for file_id in file_ids:
                log_ai_error(user_email, file_id, f"Failed to initialize Gemini client: {e}", batch_size=batch_size)
            raise

        def _prepare_one(file_id: str):
            path, original_filename, _ = get_pdf_info(file_id, user_dir)
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
                    log_ai_error(user_email, file_id, f"Failed to prepare batch file: {e}",
                                 duration_ms=round((time.monotonic() - t0) * 1000), batch_size=batch_size)

        if not contents:
            return {}

        # 2. Generate content
        contents.append(RENAME_BATCH_PROMPT)

        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents=contents
        )
        # Shared across every file in this batch — they all became available at the
        # same moment, when this one combined Gemini call returned.
        duration_ms = round((time.monotonic() - t0) * 1000)

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
                new_path, new_filename, metadata = rename_output(file_id, new_name, user_dir)
                label = metadata.get("label", "PDF")

                doc = pymupdf.open(str(new_path))
                page_count = len(doc)
                doc.close()

                original_filename = file_info_map[file_id]["original_filename"]
                log_ai_rename(user_email, file_id, original_filename, new_name, duration_ms, batch_size=batch_size)

                results[file_id] = {
                    "filename": new_filename,
                    "label": label,
                    "page_count": page_count,
                    "custom_name": metadata.get("custom_name", ""),
                }
            except Exception as inner_e:
                log_ai_error(user_email, file_id, f"Failed applying rename: {inner_e}",
                             duration_ms=duration_ms, batch_size=batch_size)

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
