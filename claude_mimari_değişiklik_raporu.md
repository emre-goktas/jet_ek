# JETEK — Backend Yükünü Frontend'e Taşıma & Serverless Mimari Analizi

## Bağlam

Kullanıcı `deploy_plan.md` içinde şu hedef mimariyi tanımladı: Backend AWS Lambda (serverless), Frontend Cloudflare, DB+auth (Gmail login) Supabase, AI API BYOK (kullanıcının kendi API key'i DB'de saklanacak). Bu değişikliğe geçmeden önce üç soru soruldu: (1) backend yükünü azaltmak için ne yapılmalı, (2) proje buna uygun mu, (3) hangi özellikler backend'de kalmalı vs tarayıcıya taşınabilir, (4) bu geçişin dezavantajları, arayüz/kod riskleri neler.

Bu, henüz uygulamaya geçilmeyecek bir **karar destek analizi**dir — kullanıcı "sadece analiz/rapor" istediğini belirtti. Aşağıdaki bulgular iki bağımsız kod keşfi (backend + frontend) ve bir mimari tasarım geçişi sonucunda derlendi.

---

## 1. Proje bu değişikliğe uygun mu? (Kısa cevap: Kısmen — arayüz tarafı şaşırtıcı derecede hazır, backend'in state/storage katmanı hiç hazır değil)

**İyi haber:** Frontend zaten büyük ölçüde "client-first" tasarlanmış. Sayfa seçimi, SortableJS ile sürükle-bırak sıralama, döndürme (CSS transform), silme/geri yükleme (class toggle), undo (Ctrl+Z), zoom/pan — bunların **hiçbiri** şu an backend'e istek atmıyor, sadece "Ayıkla"/"Güncelle" butonuna basılınca toplu gönderiliyor. Projenin "HTMX" kullandığı yazsa da (`index.html` içinde kütüphane yükleniyor), fiilen `hx-get/hx-post/hx-swap` deseni neredeyse hiç kullanılmamış — sadece bir `hx-swap-oob` var. Gerçek entegrasyon elle yazılmış `fetch()` + `innerHTML` enjeksiyonu (`sendFile`, `postAction`, `fetchAndRenderBatch` — `index.html`). Sunucu tarafında HTML üreten yalnızca 6 endpoint var ve bunların mantığı basit Jinja `{% for %}` döngüleri — bu da JSON API'ye çevirmeyi nispeten mekanik bir iş haline getiriyor.

**Kötü haber:** Backend'in üç temel varsayımı Lambda ile doğrudan çakışıyor:
- **Global in-memory state:** `pdf_service.py`'de `_LOCK_COUNTS` (ref-counted dosya kilidi) ve `_PATH_CACHE` (dosya yolu önbelleği) process-içi Python dict'leri. Lambda'da her invocation farklı (veya soğuk) container olabileceğinden bu state güvenilmez hale gelir.
- **Local disk storage:** `backend/storage/` düz dosya sistemi (UUID tabanlı `{id}_src.pdf`, `{id}_page_{n}_{dpi}.png`). Lambda'da kalıcı paylaşılan disk yok, sadece geçici `/tmp` var.
- **Sürekli çalışan background task:** `main.py` içindeki saatlik `asyncio` cleanup loop'u Lambda invocation modeliyle uyumsuz (invocation biter, süreç donar).

Yani: **arayüz tarafı neredeyse "ücretsiz" uyumlu**, ama backend'in depolama/kilit/temizlik katmanı ciddi bir yeniden yazım gerektiriyor. Bu, küçük bir refactor değil, orta-büyük ölçekli bir mimari geçiş.

---

## 2. Backend yükünü azaltmak için en yüksek etkili adım: Sayfa önizlemesini pdf.js'e taşımak

Şu an her sayfa önizlemesi (`GET /page/{pdf_id}/{page_number}`) sunucuda `pymupdf.open` + `get_pixmap` ile PNG üretip diske cache'liyor (`pdf_service.py` `render_page`), `Semaphore(10)` ile eşzamanlılık sınırlanmış. Bu, **en sık tetiklenen backend çağrısı** — kullanıcı hızlı scroll yaptıkça onlarca istek gidiyor.

**Öneri:** PDF dosyasını (veya ilgili sayfa aralığını) tarayıcıya bir kez gönder, render işini pdf.js (Mozilla'nın client-side PDF render kütüphanesi) ile tarayıcıda yap.

**Kazanç:** Bu backend çağrı trafiğinin büyük kısmını tamamen ortadan kaldırır — Lambda'ya geçmeden önce bile, mevcut sunucuda test edilip ölçülebilir. Şunlar tamamen kaldırılabilir hale gelir: `backend/routers/pages.py` (route'un tamamı), `pdf_service.py` içindeki `render_page()` ve stale-PNG temizlik mantığı, `main.py`'deki PNG temizlik dalı.

**Bu adım auth'tan ve Lambda geçişinden tamamen bağımsız** — istenirse mevcut mimaride bile bugün uygulanabilir ve hemen kazanç sağlar.

---

## 3. Hangi özellikler backend'de kesin kalmalı, hangileri tarayıcıda çalışabilir

| Backend'de kalmalı | Neden |
|---|---|
| Gemini AI çağrısı | API key (BYOK dahil) asla client JS'e sızmamalı |
| PDF birleştirme/ayıklama/döndürme (asıl dosya üretimi) | Tek doğruluk kaynağı, sunucu-taraflı limit (5000 sayfa), güvenlik |
| Word/docx üretimi | Tarayıcıda muadili yok, karmaşık şablon mantığı |
| Magic-bytes doğrulama, image→PDF dönüşümü | Güvenlik kontrolü — client beyanına güvenilmez |
| Dosya adı temizleme (path traversal savunması) | Sunucu-taraflı zorunlu |

| Tarayıcıya taşınabilir / zaten taşınmış |
|---|
| Sayfa seçimi, sürükle-bırak, silme/geri yükleme, undo, rotasyon önizleme, zoom/pan — **zaten %100 client-side** |
| **Sayfa önizleme render'ı (pdf.js)** — bu konuşmanın ana önerisi |
| ZIP paketleme (teorik olarak JSZip/pdf-lib ile mümkün ama zorunlu değil, düşük öncelik) |

---

## 4. Yükü frontend'e aktarmanın dezavantajları

- **Görsel sadakat (fidelity) farkı:** pdf.js ile PyMuPDF render sonuçları genelde yakın ama özellikle taranmış/TIFF'ten dönüştürülmüş belgelerde font/renk uzayı farkları çıkabilir. Gerçek üretim dosyalarıyla görsel karşılaştırma testi şart.
- **Mobil bellek riski:** 500+ sayfalık yüksek-DPI taranmış PDF'ler tamamen tarayıcıya inerse (özellikle iOS Safari) sekme çökme riski var. Çözüm: HTTP Range destekli sunum + pdf.js'in sayfa-sayfa lazy yükleme yapması, dosyanın tamamını tek seferde indirmemesi.
- **JS karmaşıklığı artışı:** Bugün ucuz bir `<img loading="lazy">`; pdf.js'e geçince her kart için `IntersectionObserver` + canvas render gerekiyor — sadece görünen kartların render edilmesi gerekiyor, yoksa kazanç tersine döner.
- **Client tarafına güven riski:** İş mantığının bir kısmı tarayıcıda çalıştığından, kullanıcı tarayıcı geliştirici araçlarıyla state'i manipüle edebilir — ama nihai PDF üretimi zaten backend'de doğrulandığından bu ciddi bir güvenlik açığı yaratmaz (backend zaten tek doğruluk kaynağı olarak kalıyor).

---

## 5. Arayüz bozulur mu? Kod ne kadar değişir?

- **Dokunulmadan kalır (düşük risk):** Seçim, SortableJS sürükle-bırak, silme/geri yükleme, undo, rotasyon önizleme, zoom/pan — `index.html`'in büyük kısmı bugünkü haliyle kalabilir.
- **Orta risk:** `viewer.html`'deki `<img>` → `<canvas>` dönüşümü, batch önizleme akışı (stale-cache invalidation mantığı yeniden tasarlanmalı).
- **Yüksek risk / en büyük yeni kod parçası:** pdf.js render pipeline'ının (`IntersectionObserver` + `getPage` + canvas draw) `index.html`'e eklenmesi — bu, mevcut ~1400 satırlık gömülü JS'e eklenecek en büyük tek parça yeni kod.
- Sonradan auth eklenince (Supabase), tüm `fetch()` çağrılarına JWT header eklenmesi gerekecek — geniş kapsamlı ama mekanik bir değişiklik.

**Sonuç:** Sadece pdf.js geçişi (Faz 1) yapılırsa arayüz büyük ölçüde bozulmadan kalır, orta büyüklükte bir değişiklik. Tam Lambda+Supabase+BYOK geçişi ise kod tabanının önemli bir kısmının (storage/state katmanı, AI servisi, tüm router'lara auth) yeniden yazılmasını gerektirir.

---

## 6. Önerilen Fazlı Yol Haritası (İLK SÜRÜM — bkz. §8-§13 için REVİZE edilmiş hali)

> **Not (güncelleme):** Aşağıdaki Faz 2/3 (S3/R2+Postgres+Lambda), kullanıcının sonradan eklediği "hukuki risklerden dolayı evrak almak istemiyorum" kısıtıyla büyük ölçüde **gereksiz hale geldi**. Bkz. §8 ve sonrası — "maksimal client-side" mimarisi bu ikisinin yerini alıyor. Bu tablo sadece tarihsel/karşılaştırma referansı için korunuyor.

| Faz | Kapsam | Bağımlılık | Risk |
|---|---|---|---|
| **0** | Ölçüm: gerçek üretim PDF'leriyle pdf.js fidelity testi, PyMuPDF Lambda layer/cold-start ölçümü, R2 vs S3 kararı | Yok | Düşük |
| **1** | Sayfa önizlemesini pdf.js'e taşıma — backend'den/Lambda'dan bağımsız, mevcut sunucuda uygulanabilir | Faz 0 | Orta |
| ~~2~~ | ~~Storage/state modelini Lambda-uyumlu hale getirme: local disk → S3/R2 + Postgres metadata, dağıtık kilit~~ | — | **Süperseded — §8** |
| ~~3~~ | ~~Fiili Lambda taşıma (Mangum/ASGI adapter) + Cloudflare frontend + domain~~ | — | **Süperseded — §8** |
| **4** | Supabase Auth (Gmail) + multi-tenant izolasyon + BYOK key storage (Supabase Vault ile şifreli) | Faz 2 ile paralel başlayabilir | Yüksek (güvenlik-kritik) — **hâlâ geçerli, bkz. §11 Faz 2a** |

---

## 7. Diğer riskler (özet, ilk sürüm — bkz. §8 sonrası için güncel risk listesi)

- BYOK mimarisi: `ai_service.py`'deki global tekil `_client`/API key modeli, kullanıcı bazlı key okuyan bir modele dönüşmeli — bu değişiklik doğası gereği auth'a bağımlı. **(Hâlâ geçerli.)**
- Maliyet modeli: Sabit sunucudan invocation-bazlı (Lambda) + obje depolama + Supabase tier + kullanıcının kendi AI faturasına geçiş. Faz 1 (pdf.js) bu değişkenliğin en büyük kaynağını (sayfa render trafiği) baştan keser. **(Hâlâ geçerli.)**
- ~~Lambda cold start / PyMuPDF layer boyutu, Lambda 15dk limiti, CORS S3/R2~~ — **§8 sonrası mimaride büyük ölçüde konu dışı kalıyor** (backend artık PDF işlemiyle hiç uğraşmıyor).

---

## 8. YENİ KISIT (İkinci Konsültasyon): Hukuki Risk Azaltma — Maksimal Client-Side Mimari

Faz 1 uygulanıp test edildikten sonra (1.5GB'lık bir PDF'in yükleme/render performansı gözle görülür şekilde iyileşti, donma yaşanmadı), kullanıcı motivasyonu netleştirdi: öncelik artık sadece performans/maliyet değil, **"hukuki risklerden dolayı evrak almak istemiyorum, backend sorumluluğunu minimize etmek istiyorum."** Bu, önceki §6'daki Faz 2/3'ü (S3+Lambda+dağıtık kilit) büyük ölçüde gereksiz kılan bir pivot: eğer backend hiçbir zaman belge içeriğini görmüyorsa, o içerik için sunucu-taraflı depolama/kilit/temizlik mimarisine hiç ihtiyaç kalmaz.

### 8.1. Doğrulanmış Lisans Bulgusu (kritik, kullanıcının kendi hukuki-risk endişesiyle doğrudan ilgili)

PyMuPDF/MuPDF (Artifex), **AGPL-3.0 / ticari lisans** olarak dual-license dağıtılıyor. AGPL'nin "network use" maddesi (md. 13), yazılımı ağ üzerinden sunan her SaaS'ın kaynak kodunu isteyen kullanıcılara açmasını şart koşuyor — Artifex'ten ticari lisans alınmadıysa. **Bu, backend'den frontend'e taşınarak çözülmez**: Artifex'in resmi `mupdf.js` (WASM) ürünü de aynı AGPL/ticari lisans rejimine tabi; üstelik WASM'ı tarayıcıya göndermek klasik "dağıtım" (distribution) tetikleyicisini de devreye sokar — server-side kullanımdan daha az değil, en az o kadar (muhtemelen daha) açık bir yükümlülük. **Sonuç:** İstemci tarafı PDF motoru olarak Artifex/MuPDF tabanlı bir ürün (mupdf.js) DEĞİL, bağımsız/MIT lisanslı **`pdf-lib`** seçilmeli — bu hem "belge backend'e uğramasın" hem de "AGPL riskini taşımayalım" hedeflerinin ikisini birden karşılıyor. (Not: Şu anki server-side PyMuPDF kullanımının kendisi de bu AGPL sorusuna tabi olabilir — bu ayrı, mevcut duruma ait bir konudur, gerçek bir lisans/fikri-mülkiyet avukatına danışılmalı.)

### 8.2. Soru 1 — SGK Word şablonu frontend'e taşınabilir mi?

**Evet.** `backend/data/sgk_template.docx` kullanıcı verisi içermez (SGK'nın boş, kişisel veri barındırmayan resmi format dosyası) — statik asset olarak frontend/CDN'e taşınması hukuken sorunsuz. Runtime dolgu mantığı için öneri: **`docxtemplater`** (çekirdek paket MIT lisanslı, tablo-satırı-döngüsü ücretsiz katmanda) + **`PizZip`** (MIT). Mevcut `docx_service.py`'deki python-docx "satır cerrahisi" (`_generate_from_docx_template`: son satırı bul, placeholder satırları sil, her dosya için `add_row()`, TOPLAM'ı sona taşı, paragraftaki `"( )"` yer tutucularını `str.replace` ile doldur) yerine, şablon Word'de **bir kere** düzenlenip veri satırına `{#files}...{/files}` döngü etiketleri, paragraflara `{baslangic_no}`/`{bitis_no}`/`{toplam_sayfa}` merge-tag'leri eklenir; runtime kod `new Docxtemplater(new PizZip(templateBytes)).render({files, toplam_sayfa, ...})` kadar basitleşir. `number_to_turkish_words()` (`docx_service.py:35-82`) saf aritmetik, JS'e birebir mekanik port — risk yok. UI'dan zaten erişilemeyen `_generate_legacy_docx` (sağlık_bakanlığı, ölü kod) taşınmaya değmez, kaldırılması önerilir.

### 8.3. Soru 2/3 — Download ve tüm upload→download akışı client-side olabilir mi?

**Büyük ölçüde evet, teknik olarak mümkün:**
- Tekil PDF indirme: pdf-lib ile bellekteki dokümanı `save()` → Blob → `<a download>`. Sunucu round-trip'i gerekmez.
- ZIP + Word paketleme: **`fflate`** (tam MIT, bağımlılıksız — `JSZip`'in GPL/MIT dual-license belirsizliğinden kaçınmak için tercih edilir) + yukarıdaki docxtemplater çıktısı birlikte ZIP'lenir.
- Numaralı damgalama (`download-zip-numbered`, bugün `pymupdf.insert_text`): pdf-lib `page.drawText()` + `StandardFonts` ile karşılanır.
- Upload da dahil tüm akış: Kullanıcının seçtiği `File` nesnesi hiç sunucuya gitmeden doğrudan `pdfjsLib.getDocument({data: arrayBuffer})`'a (render için, zaten Faz 1'de var) ve `PDFDocument.load(bytes)`'e (düzenleme için, pdf-lib) verilebilir.

**Ama tam bu noktada en büyük teknik risk devreye giriyor — bkz. §8.6.**

### 8.4. AI isimlendirme: client-direct Gemini + BYOK

Faz 1 sayesinde ilk sayfa zaten `<canvas>`'a render ediliyor (`renderPageCanvas`, `index.html`). Bu canvas'tan `toDataURL()` ile PNG/base64 alınıp, Google'ın resmi tarayıcı-uyumlu `@google/genai` SDK'sıyla `generateContent({contents:[{inlineData:{mimeType,data}}, prompt]})` **doğrudan tarayıcıdan**, kullanıcının BYOK key'iyle çağrılabilir. Bugünkü `client.files.upload()`/`client.files.delete()` (Gemini Files API) adımı tamamen kalkar — bu, CLAUDE.md'nin zaten flaglediği **EC-01 (hata durumunda bulut dosyası sızıntısı) riskini mimari olarak imkansız hale getirir** (silinecek bulut dosyası hiç oluşmaz).

**"Client-side'da API key ifşası" endişesi neden BYOK'ta farklıdır:** Bugün TEK bir paylaşılan `GEMINI_API_KEY` var (`ai_service.py:20-28`) — bunu client'a gömmek felaket olurdu (herkes başkasının faturasını patlatır). Ama gerçek BYOK'ta her kullanıcı KENDİ key'ini kullanır — key'i "sızdırabilecek" kişi zaten key'in sahibinin ta kendisi (kendi devtools'u, kendi oturumu). Kalan gerçek risk: key'in Supabase'den güvenli çekilmesi — RLS (`user_id = auth.uid()`) ile korunan bir tablo + ya ince bir backend endpoint'i (`GET /api/my-gemini-key`, JWT doğrular, deşifre eder, sadece o kullanıcıya döner — rate-limit/denetim buraya eklenebilir) ya da Supabase RPC ile tamamen backend'siz bir model.

### 8.5. Backend'in yeni, küçülmüş sorumluluğu

| Kalan | Kalkan |
|---|---|
| Supabase auth/JWT doğrulama | `backend/routers/upload.py`, `extract.py`, `download.py`, `pages.py` |
| BYOK key şifreli saklama + fetch endpoint'i (§8.4) | `backend/services/pdf_service.py`, `docx_service.py` (sunucu yarısı), `preprocessor.py`, `ai_service.py` |
| Statik frontend asset sunumu | `STORAGE_DIR`, `cleanup_old_files`, `secure_delete` — silinecek hiçbir şey kalmadığından anlamsızlaşır |
| (Opsiyonel) kullanıcı başı AI çağrı sayacı/rate-limit | SEC-01 (BOLA), SEC-02 (path traversal), SEC-04 (güvensiz silme) — **not: bunlar çözülmüş değil, ihtiyaç ortadan kalkmış olur**, bu ayrım önemli |

`security.sanitize_filename`'in iki görevi var: (1) path-traversal savunması — paylaşılan sunucu dosya sistemi olmadığı için client-only modelde anlamsızlaşır; (2) "OS için geçerli dosya adı" temizliği (kontrol karakterleri, Windows'ta geçersiz karakterler, uzunluk sınırı) — bu **hâlâ gereklidir**, JS'e taşınmalı, sadece güvenlik sınırı değil, indirme sırasında sessiz hata/öngörülemeyen isim değişimini önlemek için.

### 8.6. KRİTİK RİSK — 1.5GB dosya + pdf-lib bellek sınırı

Kullanıcının "1.5GB pdf yükledim donma olmadı" gözlemi **SADECE Faz 1'in pdf.js lazy-render akışını** doğruluyor (sadece görünen sayfalar render ediliyor, tüm belge tek seferde belleğe açılmıyor). `pdf-lib`'in `PDFDocument.load()`'ı ise **tüm belgeyi** bir kerede tam nesne grafiğine ayrıştırıyor — streaming değil. Somut kanıt: `Hopding/pdf-lib` GitHub Issue #470 (200 sayfa/~10MB'lık bir kırpma işleminde 6GB RAM), Issue #197 ("heap out of memory"). **1.5GB'lık bir dosyada gerçek extract/rotate/merge işlemi, tipik bir tarayıcı sekmesinin bellek sınırını (Chrome'da sekme başına ~2-4GB) aşma ihtimali yüksek.** Bu, "upload-download tamamen client-side" hedefinin en büyük açık riski — Faz 3 (§9) "tamamlandı" sayılmadan önce gerçek 1.5GB'lık bir dosyayla uçtan uca extract/rotate/download testi **kabul kriteri** olmalı. Başarısız olursa seçenekler: (a) dosya boyutu/sayfa sayısı üst sınırı koyup kullanıcıya net mesaj vermek, (b) sadece bu büyük-dosya durumu için opsiyonel/sınırlı bir sunucu-taraflı fallback (bu, "belge backend'e hiç gitmesin" hedefiyle gerilim yaratır — ürün kararı gerektirir), (c) parça parça/worker tabanlı bir yaklaşım (daha fazla mühendislik).

Ayrıca: TIFF→PDF dönüşümü için pdf-lib'in yerleşik TIFF desteği yok (`UTIF.js` gibi ayrı bir saf-JS decoder gerekir) — taranmış evraklarda yaygın CCITT G4 fax sıkıştırmasının bu kütüphanelerde tam desteklendiği doğrulanmadan "tam TIFF desteği var" varsayılmamalı.

### 8.7. Netlik gereken nokta — HUKUKİ UYARI

Bu analiz **yalnızca** "belge hiç backend'e gitmeden bu akış teknik olarak mümkün mü" sorusunu yanıtlıyor. Aşağıdakiler **teknik değil, hukuki belirlemelerdir** ve gerçek bir KVKK/veri koruma avukatına (ve AGPL için ayrıca bir fikri mülkiyet avukatına) danışılmadan bu mimarinin "hukuki riski sıfırladığı" varsayılmamalıdır:
1. KVKK'nın "veri sorumlusu" tanımı işleme amaç/vasıtalarını belirleyenle ilgilidir — işleme mantığı istemci JS'ine taşınsa bile o kodu yazıp kullanıcıya sunan sizsiniz; bunun KVKK bağlamında nasıl değerlendirileceği hukuki bir yorum meselesidir.
2. Client-direct Gemini çağrısı bile belge görüntüsünü **Google'ın sunucularına (yurt dışına)** gönderir — "kendi backend'imize dokunmuyor" argümanı KVKK'nın yurt dışına aktarım hükümlerini çözmez.
3. "Teknik olarak mümkün" ile "hukuken yeterli/tavsiye edilir" ayrı sorulardır; bu belge yalnızca ilkini yanıtlıyor.

---

## 9. Revize Fazlı Yol Haritası (§6/§7'nin yerini alır)

| Faz | Kapsam | Bağımlılık | Risk |
|---|---|---|---|
| **1** | ✅ TAMAMLANDI — sayfa önizlemesi pdf.js ile client-side render | — | — |
| **2a** | Supabase auth + BYOK key şifreli saklama + key-fetch endpoint'i (§8.4) — **2b'nin ön koşulu, atlanamaz** | Supabase projesi | Yüksek (güvenlik-kritik) |
| **2b** | AI isimlendirmeyi client-direct Gemini'ye taşıma (§8.4) — `ai_service.py`/`ai.py` retire | Faz 2a | Düşük-Orta, ROI yüksek |
| **3** | Sayfa düzenleme motorunu (extract/reorder/rotate/merge) `pdf-lib`'e taşıma + upload'ı tamamen client-side yapma (§8.3, §8.6) | Faz 2 ile paralel yapılabilir | **Yüksek — en büyük mühendislik yükü, 1.5GB kabul testi zorunlu** |
| **3.5** | SGK Word şablonunu docxtemplater'a taşıma (§8.2), download/ZIP'i client-side'a taşıma (§8.3) | Faz 3 | Orta |
| **4** | Kalan backend'i (auth + BYOK endpoint) sertleştirme, rate-limit, `deploy_plan.md`'deki "AWS Lambda" hedefinin bu ince endpoint için (artık PyMuPDF/disk yok) Lambda yerine bir Cloudflare Worker'a bile indirgenebileceğini değerlendirme | Faz 2a | Orta |
| **5 (opsiyonel)** | CLAUDE.md'nin "yerel OCR" hedefi — `tesseract.js` (Apache-2.0, WASM, tamamen client-side), aynı ilkeyle tutarlı | — | Düşük öncelik |

---

## Bu oturumda yapılan / yapılmayan

Analiz tamamlandıktan sonra kullanıcı **Faz 1'i (sayfa önizlemesini pdf.js'e taşıma) hemen uygulamaya almamı istedi**. Aşağıdaki "FAZ 1 — Uygulama Planı" bölümü bu fazın kod değişikliği planıdır — bu kod **uygulandı ve gerçek tarayıcı testleriyle doğrulandı** (upload, scroll/render, döndürme, zoom, rename modalı, Batch Update — hepsi başarılı, konsol hatası yok, 1.5GB'lık test dosyasında donma yaşanmadı). Ardından kullanıcı ikinci bir konsültasyonla (§8) yeni bir kısıt getirdi (hukuki risk azaltma) ve DOCX/download/tüm-akış client-side sorularını sordu — bu sorulara §8-9'da cevap verildi, **henüz Faz 2/3 için kod yazılmadı**, bu bölüm kullanıcının onayını bekleyen bir analiz/yol haritasıdır.

---

## FAZ 1 — Uygulama Planı: Sayfa önizlemesini pdf.js'e taşıma

### Amaç
`GET /page/{pdf_id}/{page_number}` (sunucuda PyMuPDF ile PNG üretimi, en sık tetiklenen backend çağrısı) tamamen kaldırılıyor. Yerine: tarayıcı PDF'in ham baytlarını bir kere indirir, sayfaları pdf.js ile kendi içinde canvas'a render eder.

### Backend değişiklikleri

1. **`backend/routers/pages.py`** — mevcut `get_page_image`/`RENDER_SEMAPHORE` kaldırılır, yerine ham PDF baytını dönen yeni bir route eklenir:
   ```python
   @router.get("/pdf-source/{pdf_id}")
   def get_pdf_source(pdf_id: str):
       path, _, _ = pdf_service.get_pdf_info(pdf_id)  # hem orijinal upload hem batch output'u çözer
       return FileResponse(path=str(path), media_type="application/pdf", headers={"Cache-Control": "no-cache"})
   ```
   `no-cache` mevcut PNG endpoint'iyle aynı gerekçeyle korunuyor: Batch Update aynı pdf_id'nin baytlarını yerinde değiştirebiliyor.

2. **`backend/services/pdf_service.py`**:
   - `render_page()` fonksiyonu (satır 129-160) tamamen silinir.
   - `update_pages()` içindeki stale-PNG temizlik bloğu (satır 286-289, `STORAGE_DIR.glob(f"{file_id}_page_*.png")`) silinir — artık hiç PNG üretilmiyor.

3. **`backend/main.py`**: `cleanup_old_files()` içindeki `itertools.chain(...)` çağrısından `STORAGE_DIR.glob("*.png")` dalı kaldırılır (satır 33) — artık depoda PNG dosyası oluşmuyor.

### Frontend değişiklikleri

4. **pdf.js kütüphanesi**: `index.html` `<head>` içine, Tailwind/SortableJS CDN'leriyle aynı üslupta, **UMD/legacy build** (ES module değil — kod tabanı düz `<script>` + global fonksiyon deseni kullanıyor, `window.pdfjsLib` global'i gerekiyor) eklenir + `pdfjsLib.GlobalWorkerOptions.workerSrc` worker dosyasına ayarlanır.

5. **`frontend/templates/partials/viewer.html`** (satır 42-47): `<img src="/page/{{pdf_id}}/{{i}}" loading="lazy">` → `<canvas class="page-img" data-pdf-id="{{pdf_id}}" data-page-index="{{i}}"></canvas>`. `app.css`'teki `.page-img { aspect-ratio: 1/1.414; ... }` kuralı zaten hem `<img>` hem `<canvas>` için geçerli olduğundan, render öncesi placeholder boyutu değişmeden korunur.

6. **`index.html`** yeni JS (mevcut page-card mantığının yanına eklenir):
   - `pdfDocCache` (Map: pdf_id → pdf.js döküman promise'i) — her PDF sadece bir kez indirilip parse edilir, tüm sayfalar aynı dökümandan render edilir.
   - `renderPageCanvas(canvas)` — `data-pdf-id`/`data-page-index`'i okuyup ilgili sayfayı canvas'a çizer.
   - Paylaşılan bir `IntersectionObserver` (`ensurePageObserver`/`observeAllPageCanvases`) — bugünkü `loading="lazy"` davranışının birebir karşılığı: sadece görünüme giren kartlar render edilir.
   - `invalidatePdfDoc(pdfId)` — Batch Update sonrası aynı pdf_id'nin baytları değiştiğinde önbellekteki pdf.js dökümanını düşürür (bugünkü `?v=timestamp` cache-bust mantığının karşılığı).

7. **Mevcut fonksiyonlarda küçük uyarlamalar:**
   - `fetchAndRenderBatch` (satır 1523-1565): `?v=cacheBust` ekleyen blok (satır 1539-1547) → `await invalidatePdfDoc(pdfIdMatch[1])` + `observeAllPageCanvases(viewerContainer)` ile değiştirilir.
   - `showPreview` (satır 1045-1053, zoom modalı): `modalImg.src = img.src` → `modalImg.src = img.toDataURL('image/png')` (artık `.page-img` bir canvas).
   - `loadRenameModalContent`/`updateBatchPreviewUI` (satır 662-771, yeniden adlandırma modalı önizlemesi): `batchPreviewItems` artık `{src: '/page/...'}" yerine `{pdfId, pageIndex}` tutar; `updateBatchPreviewUI` async olur ve pdf.js ile offscreen canvas'a render edip `previewImg.src = canvas.toDataURL()` atar.
   - `rotateSinglePage` (satır 633-642): değişiklik gerekmiyor — `.page-img` class'ı üzerinden CSS `transform` uyguluyor, canvas'ta da aynı şekilde çalışır.
   - Viewer HTML'in enjekte edildiği her yer (upload sonrası `sendFile`, `fetchAndRenderBatch`) sonrasına `observeAllPageCanvases(...)` çağrısı eklenmeli.

### Test/Doğrulama
- Mevcut sunucuda (Lambda'yı beklemeden) çalıştırılıp test edilebilir.
- Gerçek üretim PDF'leriyle (özellikle taranmış TIFF→PDF belgeler) pdf.js render çıktısı görsel olarak PyMuPDF PNG çıktısıyla karşılaştırılmalı.
- 500+ sayfalık bir PDF ile scroll performansı ve tarayıcı bellek kullanımı gözlemlenmeli.
- Batch Mode'da: sayfa döndür/sil/sırala → Güncelle → aynı pdf_id tekrar görüntülendiğinde eski (stale) sayfaların gelmediği doğrulanmalı (invalidatePdfDoc doğru çalışıyor mu).
- Rename modalı ve zoom modalı ayrı ayrı manuel test edilmeli (her ikisi de `/page/` yerine pdf.js'ten besleniyor artık).
-----
Analizi tamamladım ve plan dosyasına (~/.claude/plans/projemle-ilgili-mimari-olarak-enchanted-frog.md, §8-9) detaylı olarak işledim. Özet:

1. SGK Word şablonu frontend'e taşınabilir mi? Evet. sgk_template.docx kullanıcı verisi değil, sizin şablonunuz — statik asset olarak taşınması hukuken sorunsuz. Runtime dolgu mantığı için docxtemplater (MIT, tablo-satırı döngüsü ücretsiz katmanda) öneriyorum; mevcut python-docx "satır cerrahisi" yerine şablona bir kerelik {#files}...{/files} döngü etiketi eklenir, kod çok sadeleşir.

2. Download client-side olabilir mi? Büyük ölçüde evet — tekil PDF, ZIP+Word paketleme (fflate + docxtemplater çıktısı), numaralı sayfa damgalama, hepsi tarayıcıda yapılabilir.

3. Upload→download tamamen client-side olabilir mi? Teknik olarak evet, ama tek büyük açık risk: pdf-lib (extract/rotate/merge motoru) tüm belgeyi belleğe tam açıyor, streaming değil. "1.5GB'de donma olmadı" gözleminiz sadece Faz 1'in (pdf.js lazy-render) başarısını kanıtlıyor — gerçek sayfa düzenleme işlemi çok daha fazla bellek ister. GitHub'da 200 sayfalık bir dosyada 6GB RAM tüketimi bildirilen vakalar var. Bu yüzden Faz 3'ü bitmiş saymadan önce gerçek 1.5GB'lık dosyayla uçtan uca test şart.

4. Yanlış yöne mi evriliyorsunuz? Hayır — tam tersi, hukuki-risk motivasyonu doğru bir mimari pivot. Hatta önceki S3+Lambda+dağıtık-kilit planımı büyük ölçüde gereksiz kılıyor: backend belgeye hiç dokunmazsa, o depolama/kilit mimarisine zaten gerek kalmıyor.

Önemli ek bulgu: PyMuPDF/MuPDF (Artifex) AGPL-3.0/ticari dual-license. Bu, tam sizin "hukuki risk" endişenizle ilgili: backend'den frontend'e taşımak bu riski çözmez — Artifex'in mupdf.js'i de aynı lisansa tabi, hatta WASM'ı tarayıcıya dağıtmak klasik "dağıtım" tetikleyicisini de devreye sokar. Bunun yerine bağımsız/MIT lisanslı pdf-lib seçilmeli.

Önerilen sıralama: Faz 2a (Supabase auth + BYOK key altyapısı, ön koşul) → 2b (AI isimlendirme client-direct Gemini'ye) → 3 (pdf-lib motor geçişi + upload'ı tamamen client-side yapma, en riskli) → 3.5 (Word/ZIP client-side) → 4 (kalan ince backend'i sertleştirme).

