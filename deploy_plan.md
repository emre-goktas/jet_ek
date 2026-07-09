Projemin kullanım kurgusunu şöyle tasarlamak istiyorum;

1- Kullanıcı domaini tarayıcıya girer.(örnek www.jetek.com)
2- Kullanıcı gmail hesapıyla şifresiz giriş yapar. Jetek açılınca kullanıcının ilk göreceği şey, google gmail ile giriş yap ekranı olur. Kullanıcı gmail ile hemen girer.
3- Kayıt ekranımız(henüz tasarlamadık) açılır ve kullanıcı bilgilerini kaydederiz. Bu bilgiler; isim soyisim, unvan ve şablon seçimi(word şablonu) gibi bilgiler olur ve bu bilgileri sqlite a kaydederiz. Kayıt ekranımız için arayüzde bir kullanıcı profili oluşturacağız. Bu profil, kullanıcının şablonu ve diğer bilgilerini tutar. İstediği zaman değiştirebilir. Değişiklik durumdan veritabanımız güncellenmeli. Kullanıcının boş bırakamayacağı tek alan şablon seçimi olacak. şuan temel olarak 3 adet şablonumuz var. 
1- sgk_template(bunun isimi sgk müfettiş şablonu yapcam)
2- henüz proje dizininde yok ama sgk_template ile %100 uyumlu oan bir sgk denetmen şablonu docx dosyası ekleyeğim. bu şablon seçilirse ekstra İL bilgisi sormamız gerekecek. bu bilgiyi bu şablonun header kısmına basmamız gerekecek. (örnek istanbul sgk il müdürlüğü, ankara sgk il müdürlüğü vs gibi)
3- sb_template bu da hazır dizinde var zaten. doc servisimiz hangi bilgili bu şablonun neresine basacak onu ayarlamamız gerek sadece galiba. (belkide hazırdır kodlar kontrol gerek)
4- şablonsuz devam et seçeneği. Şablonsuz seçenekte zip içinde .docx tablo vereceğiz. sayfa üst bilgisi isim bilgisi vs birşey olamayacak. ek no-belgenin mahiyeti-sayfa adedi sutunları olacak sadece.

4- Kullanıcı ana sayfaya yönlendirilir.Yani upload ekranımız açılır. PDF lerini düzenler ve işlemlerini yapar.
5- Akıllı isimlendirme(şimşek ikonuna) tıklandığında APİ anahtarını getirmesini isteriz. Kullanıcı api anahtarını alır ekrana vereceğimiz bir metin kutusuna yapıştırır. Bu api anahtarını şifreli bir şekilde database e alırız. (email ile eşleşecek şekilde). ve hatta mümkün ise aldığı api anahtarı kullanıcının tarayıcısında kalsın biz hiç veritabanına yazmayalım. bu durumda backendimiz user in tarayıcısından api anahtarını okuyabilir mi ?
6- Download butonu tetiklenince kullanıcı zipi teslim aldığında storagedeki tüm dosyalar kalıcı olarak silinecek. ve hergün gece saat 3-4 rutin temizlik olacak. Backendde kullanıcılardan gelen hiç bir dosya kalmayacak.

Deploy olarak yeni fikrim şu;

1- Backend kendi leptopum.(fazladan kullanmadığım leptopum var. linux)
2- Frontend cloudflare. Domain köprüsü
3- Database sqllite ve kendi lokal leptobum
4- login gmail ile şifresiz.
5- AI API BYOK (kullanıcının kendi api key'i db'de saklanacak mümkün ise kendi tarayıcısında saklansın)
6- bu aşamada ödeme alt yapısı vs yok. tamamen ücretsiz olacak projem.
7- localde calışan backedn ve veritabanı ile frontent entegrasyonu için gerekirse bir otomasyon yapmamız gerek. (bu konuda fikirlerine açığım)
kullanıcı sayısı 20 yi aşmaya başladığında uygun bir vps e taşıyacağız backendi. kullanıcı sayısı artmaya devam ederse daha profosyonel bir serverles(aws gibi) platforma taşıyacağız.

-----
# JETEK MVP Roadmap — Auth, Profil, Şablon Seçimi, BYOK, Deploy

## Context

`deploy_plan.md` artık projenin hedef kullanım kurgusunu tarifliyor: Gmail ile şifresiz giriş → kullanıcı profili (isim/unvan/şablon, SQLite'da) → upload/düzenleme ekranı (zaten var) → AI isimlendirme için BYOK Gemini anahtarı → indirme sonrası backend'de hiçbir kullanıcı dosyası kalmaması → backend kendi laptopunda, Cloudflare ile domain köprüsü, ödeme altyapısı yok (ücretsiz).

Bu oturumda daha önce ZIP/DOCX üretimi ve görsel→PDF dönüşümü backend'den frontend'e taşındı (bkz. `frontend/static/js/document-builder.js`) — bu, `claude_mimari_değişiklik_raporu.md`'deki "maksimal client-side" hedefinin (hukuki risk azaltma) bir parçasıydı. Şu an planlanan iş, aynı felsefenin devamı: kimlik doğrulama + kişiselleştirme + temiz bir deploy.

**Doğrulanmış mevcut durum** (iki Explore ajanıyla bugün teyit edildi):
- Sıfır auth/session/DB — hiçbir yerde `User`/session/JWT/cookie yok, tek kalıcı veri `backend/storage/{file_id}.json` (bkz. `pdf_service.py:78-93`).
- `templates.json`'daki `"saglik_bakanligi"` girdisi **`sb_template.docx` dosyasını hiç kullanmıyor** — o dosya (ve `sb_ifade_promt*.docx`) kod tabanında referanssız/yetim. `sb_template.docx`'i bugün inceledim: tek tablo, ~24 satır, "Toplam / 000" ve "00.00.2025 tarihinde düzenlenmiştir." gibi `sgk_template.docx`'ten **farklı** placeholder biçimleri kullanıyor.
- `document-builder.js:544-547` her zaman `list[0]` (yani `"sgk"`) kullanıyor — hiçbir şablon seçim arayüzü yok.
- `ai_service.py:22-27` tek, paylaşılan `GEMINI_API_KEY` env var'ını global bir `_client`'a yüklüyor — per-user/per-request anahtar kavramı yok.
- `README.md` sadece `cloudflared tunnel --url ...` (geçici/anonim tünel) komutunu içeriyor — kalıcı/isimlendirilmiş tünel, DNS route, systemd servisi yok. Backend hiç CORS middleware'i içermiyor; frontend zaten backend'in kendisi tarafından (Jinja2 + `/static` mount) sunuluyor — tek origin.

**Kullanıcıyla netleştirilen iki mimari karar:**
1. **Deploy topolojisi: tek origin.** Cloudflare sadece domain+TLS+Tunnel sağlayacak; frontend ayrı bir Cloudflare Pages deploy'u olmayacak, bugünkü gibi FastAPI tek süreçte hem `index.html`'i hem `/api`'yi sunmaya devam edecek. CORS'a hiç gerek yok, session cookie basitçe çalışır.
2. **BYOK: header-passthrough.** Anahtar tarayıcıda (`localStorage`) tutulur, her AI-rename isteğinde bir header ile backend'e geçer, backend hiç diske/DB'ye yazmaz. (Daha yüksek-effort "client-direct Gemini" alternatifi bilinçli olarak ertelendi — gelecekte tekrar gündeme gelebilir.)

---

## Faz 1 — İndirme sonrası temizlik + gece rutini (bağımsız, önce yapılabilir)

Bugünden itibaren ZIP tarayıcıda kuruluyor, yani backend artık "indirme ne zaman bitti" bilmiyor — `cleanup_old_files()`'ın 1 saatlik bekleme penceresi tek güvence. Kullanıcı hedefi daha agresif: indirme anında sil + gece 03:00-04:00 rutin.

- **`backend/routers/download.py`**: yeni `POST /cleanup` endpoint'i, `{"file_ids": [...]}` alır, her biri için `pdf_service.get_output_path` + `pdf_service.secure_delete` (zaten var, `pdf_service.py:320-335`) çağırır, metadata JSON'unu da siler. Kilitliyse (`is_file_locked`) atla (aynı dosya başka bir istek tarafından kullanılıyor olabilir).
- **`frontend/static/js/document-builder.js`**: `buildAndDownloadZip()` içinde `triggerBlobDownload()`'dan hemen sonra `fetch('/cleanup', {method:'POST', body: JSON.stringify({file_ids: filesData.map(f=>f.file_id)})})` çağrısı eklenir. Not: bu sadece bu ZIP'e giren *output* dosyalarını siler; kullanıcı aynı upload'tan başka bir ayıklama daha yapmak isterse orijinal kaynak PDF hâlâ dursun mu yoksa "indirince her şey gitsin" mi istiyorsun — bu bir ürün kararı, birlikte netleştirelim (öneri: sadece indirilen output'ları sil, orijinal upload'lar zaten 1 saatlik/gece sweep'ine tabi kalsın).
- **`backend/main.py`**: `cleanup_old_files()`'daki `await asyncio.sleep(3600)` yerine, gece 03:00'e kadar bekleyip tam bir sweep yapan bir zamanlama (basit `datetime` farkı ile "bir sonraki 03:00'e kadar uyu" hesaplanır). Saatlik stale-lock sweep'i de güvenlik ağı olarak kalabilir.

## Faz 2 — Google Sign-In (şifresiz) + oturum

- Yeni bağımlılıklar: `google-auth` (ID token doğrulama), `itsdangerous` (imzalı session cookie — JWT kütüphanesi kadar ağır değil, tek ihtiyacımız kurcalanamaz bir cookie).
- **`frontend/templates/login.html`** (yeni): Google Identity Services butonu (`<script src="https://accounts.google.com/gsi/client">`), client secret gerekmez (ID-token akışı). Buton, ID token'ı `POST /auth/google`'a gönderir.
- **`backend/routers/auth.py`** (yeni): `POST /auth/google` → `google.oauth2.id_token.verify_oauth2_token` ile doğrula → email/isim çıkar → `itsdangerous.URLSafeTimedSerializer` ile imzalı, `httpOnly`+`Secure`+`SameSite=Lax` bir session cookie'si bas → varsa profili var mı kontrol et, yoksa `/onboarding`'e yönlendir.
- **`backend/main.py`**: `get_current_user` FastAPI dependency'si (cookie'yi çöz, süresi geçmişse/yoksa 401/redirect). Hangi route'ların login gerektireceğine karar vermemiz gerek — öneri: upload/extract/download/ai hepsi login ister (zaten per-user şablon ve BYOK anahtarı bu kimliğe bağlı olacak).
- Yeni env var: `GOOGLE_CLIENT_ID`, `SESSION_SECRET_KEY`.

## Faz 3 — SQLite profil + şablon seçimi kablolaması

- **`backend/services/user_service.py`** (yeni): stdlib `sqlite3` (SQLAlchemy gibi bir ORM'e gerek yok, tek tablo) — `backend/data/jetek.db` (`.gitignore`'a eklenir). Şema: `email PK, name, title, template_id, il (nullable), created_at, updated_at`.
- **`frontend/templates/onboarding.html`** (yeni): isim/unvan formu + şablon radio grubu — sgk müfettiş / sağlık bakanlığı / şablonsuz (dördüncü seçenek, aşağıda) / *sgk denetmen (henüz dosya yok, sen eklediğinde aktifleşecek şekilde gri/disabled bırakılabilir)*.
- **`document-builder.js`**: `buildDocxIndex()`'teki sabit `list[0]` yerine giriş yapmış kullanıcının kayıtlı `template_id`'sini kullan (örn. `index.html`'e context olarak gömülen bir `window.CURRENT_USER` ya da hafif bir `GET /api/me` çağrısı).
- **`sb_template.docx`'i gerçek bir `file_path` şablonu olarak bağlama**: `buildDocxFromExistingTemplate` zaten template-agnostik yazıldı (hardcoded olan tek şey "( ) numaraları altında...( ) sayfadan" arama deseni) — bunu templates.json'dan okunan yapılandırılabilir bir placeholder deseni haline getirip (`total_pages_placeholder`, vb.) `sb_template.docx`'in "000"/"00.00.2025" biçimine uyarlamak gerekiyor. Önce satır yapısını (TOPLAM-eşdeğeri satırın gerçekten son satır olup olmadığını) doğrulamak lazım — bugün sadece düz metin sırasını kontrol ettim, satır indexleri değil.
- **"Şablonsuz devam et" (4. mod)**: `buildDocxFromScratch`'ı templates.json'da yeni bir girdi olmadan, üç kolonlu (ek no/mahiyet/sayfa adedi) minimal bir config ile çağıran bir dal — frontend'de sabit kodlanmış bir obje yeterli, header/logo/footer yok.

## Faz 4 — BYOK header-passthrough

- **`frontend/`**: "Jetle isimlendir" dropdown'ına (zaten `index.html`'de var) bir "API anahtarımı ayarla" seçeneği — küçük bir modal, `localStorage`'a yazar. `runJetRenameAll()` ve tekil `/ai/jet-rename/{id}` çağrıları `X-Gemini-Api-Key` header'ı ekler.
- **`backend/services/ai_service.py`**: `get_client()` artık bir `api_key` parametresi alır (env var fallback'i kaldırılıyor — paylaşılan anahtar zaten CLAUDE.md'nin SEC-05 maddesinde maliyet-istismar riski olarak işaretliydi). Modül-seviyeli `_client` singleton'ı da per-request hale gelmeli (artık kullanıcı başına farklı anahtar var).
- **`backend/routers/ai.py`**: iki endpoint de `X-Gemini-Api-Key` header'ını okur, yoksa 400 + "anahtarınızı ayarlayın" mesajı döner.

## Faz 5 — Deploy

- **Kalıcı Cloudflare Tunnel**: `cloudflared tunnel create jetek`, `cloudflared tunnel route dns jetek <domain>`, bir `config.yml` (`localhost:7860`'a işaret eder) — `README.md`'deki geçici `cloudflared tunnel --url` komutunun yerini alır.
- **systemd servisleri** (laptop reboot/crash sonrası otomatik ayağa kalksın): `uvicorn backend.main:app --host 127.0.0.1 --port 7860` (dikkat: `--reload` olmadan, prod'da kapalı olmalı) ve `cloudflared tunnel run jetek` — ikisi de `Restart=on-failure` ile.
- **`backend/rate_limit.py`**: `get_remote_address` yerine Cloudflare'in `CF-Connecting-IP` header'ını okuyan bir `key_func` — tünel arkasında her istek aksi halde localhost'tan geliyormuş gibi görünür, rate limit anlamsızlaşır.
- Ödeme altyapısı bilinçli olarak kapsam dışı. 20 kullanıcı eşiği (VPS'e taşıma) bu MVP'nin parçası değil, ileride ayrı bir konu.

---

## Sıralama ve bağımlılıklar

Faz 1 tamamen bağımsız, hemen yapılabilir. Faz 2 (auth), Faz 3-4'ün önkoşulu (kime ait profil/anahtar sorusu kimlik gerektirir). Faz 5 (deploy) teknik olarak herhangi bir noktada yapılabilir ama gerçek Google OAuth redirect URI'sinin çalışması için gerçek bir domain/HTTPS gerekiyor — yani Faz 2'yi lokal test etmek için `localhost`'u Google Cloud Console'da yetkili origin olarak eklemek gerekecek, tünel Faz 2'den önce de kurulabilir.

## Doğrulama

- Faz 1: gerçek bir upload→extract→ZIP indirme akışı çalıştırıp `backend/storage/`'da o dosyaların indirmeden hemen sonra silindiğini doğrula.
- Faz 2: Google hesabıyla giriş yap, cookie'nin `httpOnly`/`Secure` bayraklarını tarayıcı devtools'tan kontrol et, cookie olmadan korumalı bir route'a istek atıp 401 aldığını doğrula.
- Faz 3: iki farklı hesapla giriş yapıp farklı şablon seçip, ZIP indirip her ikisinin de doğru Word şablonunu ürettiğini doğrula (LibreOffice headless convert + metin karşılaştırması, bu oturumda kullandığım yöntemle).
- Faz 4: geçersiz/eksik anahtarla 400 aldığını, geçerli anahtarla AI isimlendirmenin çalıştığını ve `backend/data/`veya `backend/storage/` içinde anahtarın hiçbir yerde diske yazılmadığını (`grep -r` ile) doğrula.
- Faz 5: laptopu yeniden başlatıp iki systemd servisinin de otomatik ayağa kalktığını, dış bir ağdan domain üzerinden siteye erişilebildiğini doğrula.
