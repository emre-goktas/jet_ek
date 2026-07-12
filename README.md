# JETEK

Kurumsal ve resmi evrak yoğunluğu olan departmanlar (hukuk, teftiş, İK vb.) için PDF düzenleme, sayfa ayıklama/yeniden sıralama, AI destekli akıllı isimlendirme ve Word indeks üretimini otomatikleştiren bir araç.

## Özellikler

- PDF/TIFF yükleme; sayfa sıralama, döndürme, silme — tamamen tarayıcıda (pdf.js)
- Google ile şifresiz giriş, kurum şablonuna göre kullanıcı profili
- Gemini ile AI destekli otomatik dosya adlandırma — **BYOK**: her kullanıcı kendi Gemini API anahtarını kullanır, anahtar sunucuya hiç yazılmaz
- Word indeks pusulası (SGK Müfettiş / SGK Denetmen / şablonsuz vb.) ve ZIP paketleme tarayıcıda üretilir
- İndirme sonrası ve gece rutiniyle otomatik dosya temizliği — sunucuda kalıcı kullanıcı verisi tutulmaz

## Teknoloji

- **Backend:** FastAPI, Uvicorn (uvloop), PyMuPDF, SQLite
- **AI:** Google Gemini (`google-genai`)
- **Frontend:** Jinja2 + HTMX + Tailwind (CDN), pdf.js, pdf-lib, fflate, SortableJS — bundler yok
- **Kimlik doğrulama:** Google Sign-In (ID token) + imzalı oturum çerezi

## Kurulum

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` dosyasında doldurulması gerekenler:

| Değişken | Zorunlu mu | Açıklama |
|---|---|---|
| `GOOGLE_CLIENT_ID` | Evet | Google Cloud Console → APIs & Services → Credentials'tan alınan OAuth Client ID (Web application). İstemci sırrı gerekmez. |
| `SESSION_SECRET_KEY` | Evet | Oturum çerezini imzalamak için rastgele bir string: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `JETEK_ENV` | Hayır | `development` olarak ayarlanırsa oturum çerezi düz HTTP üzerinden de çalışır (yerel geliştirme için). Prod'da boş bırakılmalı. |

Uygulama, bu iki zorunlu değişken tanımlı değilse başlamayı reddeder (kimlik doğrulama isteğe bağlı değildir).

## Çalıştırma

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 7860 --reload
```

Tarayıcıda: `http://127.0.0.1:7860`

## Proje yapısı

```
backend/
  routers/     API rotaları (upload, pages, extract, download, ai, auth, profile, analytics)
  services/    İş mantığı: pdf_service, ai_service, auth_service, db_service, preprocessor, security
  data/        Word şablonları (.docx), templates.json, SQLite veritabanı
  storage/     Geçici kullanıcı dosyaları — kalıcı değil, otomatik temizlenir
frontend/
  templates/   Jinja2 sayfaları (index, login, onboarding)
  static/js/   İstemci tarafı mantık: sayfa render, seçim/döndürme, batch mode, ZIP/DOCX üretimi
```

## Notlar

- Gemini API anahtarı yalnızca kullanıcının tarayıcısında (`localStorage`) tutulur ve her istekte `X-Gemini-Api-Key` header'ı ile geçirilir — sunucu diske veya veritabanına hiçbir zaman yazmaz.
- `backend/storage/` tamamen geçicidir: bir çıktı indirilince backend'e haber verilir (`/cleanup`), kalan her şey 15 dakikalık boşta-kalma taramasıyla ve her gece 03:00'te silinir.

## Lisans

Bu proje [GNU AGPL v3.0](LICENSE) ile lisanslanmıştır.

Bu seçim doğrudan bir bağımlılık kısıtından kaynaklanıyor: PDF işleme motoru olan `PyMuPDF`, `AGPL-3.0` veya ücretli Artifex ticari lisansıyla çift lisanslıdır. Ücretsiz (AGPL) sürümü kullanıldığı sürece — ki şu an durum budur — AGPL'in ağ-üzerinden-kullanım şartı gereği JETEK'in tamamının da aynı şekilde açık kaynak kalması gerekir; bu yüzden proje kendi kodu için de AGPL'i benimsemiştir. İleride Artifex'ten ticari bir PyMuPDF lisansı alınırsa veya PDF motoru izin verici lisanslı bir alternatifle değiştirilirse, proje lisansı yeniden değerlendirilebilir.
