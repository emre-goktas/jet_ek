/**
 * viewer-render.js
 * pdf.js client-side page rendering: fetches each pdf_id's bytes once via
 * /pdf-source/{id}, caches the parsed document, and lazily renders pages into
 * <canvas> elements via IntersectionObserver as they scroll into view.
 */

    // ─── pdf.js client-side page rendering ───────────────────────────────
    // Replaces the old server-rendered "/page/{pdf_id}/{i}" PNG endpoint: each
    // pdf_id's bytes are fetched and parsed once, then every page is rendered
    // straight into a <canvas> in the browser.
    const RENDER_SCALE = 120 / 72; // matches the old server-side render DPI (120)
    const pdfDocCache = new Map(); // pdf_id -> Promise<PDFDocumentProxy>
    let pageRenderObserver = null;

    function getPdfDoc(pdfId) {
      if (!pdfDocCache.has(pdfId)) {
        // rangeChunkSize: pdf.js's default (64KB) means a large source PDF
        // needs one HTTP Range request per 64KB just to progressively load
        // it — for a few-hundred-page/multi-ten-MB document that's easily
        // hundreds of requests, enough to blow through /pdf-source's own
        // 60/minute limit on its own (seen in practice: an 837-page ~27MB
        // book hit 429s and left some page thumbnails permanently blank).
        // 1MB chunks cut that request count by ~16x for the same file.
        const task = pdfjsLib.getDocument({ url: `/pdf-source/${pdfId}`, rangeChunkSize: 1024 * 1024 });
        // A transient fetch/parse failure must not poison every future attempt —
        // evict so the next getPdfDoc() call actually retries instead of forever
        // reusing this same rejected promise (see renderPageCanvas's retry).
        const promise = task.promise.catch(err => {
          if (pdfDocCache.get(pdfId) === promise) pdfDocCache.delete(pdfId);
          throw err;
        });
        pdfDocCache.set(pdfId, promise);
      }
      return pdfDocCache.get(pdfId);
    }

    // A Batch Mode Update rewrites a pdf_id's bytes in place — drop the cached
    // document so the next getPdfDoc() re-fetches fresh content instead of
    // silently continuing to render the old pages.
    async function invalidatePdfDoc(pdfId) {
      const pending = pdfDocCache.get(pdfId);
      pdfDocCache.delete(pdfId);
      if (pending) {
        try {
          const doc = await pending;
          doc.destroy();
        } catch (e) { /* already gone or failed to load, nothing to clean up */ }
      }
    }

    // attempt is internal (retry bookkeeping) — callers always call with just canvas.
    async function renderPageCanvas(canvas, attempt = 0) {
      if (canvas.dataset.rendered === '1') return;
      const pdfId = canvas.dataset.pdfId;
      const pageIndex = parseInt(canvas.dataset.pageIndex, 10);
      try {
        const pdfDoc = await getPdfDoc(pdfId);
        const page = await pdfDoc.getPage(pageIndex + 1); // pdf.js pages are 1-based
        const viewport = page.getViewport({ scale: RENDER_SCALE });
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise;
        canvas.dataset.rendered = '1';
      } catch (e) {
        console.error('Sayfa render edilemedi:', pdfId, pageIndex, e);
        // A card that's already fully in view won't get a fresh IntersectionObserver
        // event to hang a retry off of, so retry here directly (bounded, with
        // backoff) instead of leaving it permanently blank on one transient failure.
        if (attempt < 2 && document.body.contains(canvas)) {
          setTimeout(() => renderPageCanvas(canvas, attempt + 1), 800 * (attempt + 1));
        }
      }
    }

    // Renders a single page into an offscreen canvas and returns it as a data URL,
    // for spots (rename modal, zoom preview) that need a plain <img>-compatible src.
    async function renderPageDataUrl(pdfId, pageIndex, scale = RENDER_SCALE) {
      const pdfDoc = await getPdfDoc(pdfId);
      const page = await pdfDoc.getPage(pageIndex + 1);
      const viewport = page.getViewport({ scale });
      const off = document.createElement('canvas');
      off.width = viewport.width;
      off.height = viewport.height;
      await page.render({ canvasContext: off.getContext('2d'), viewport }).promise;
      return off.toDataURL('image/png');
    }

    // Shared IntersectionObserver so only visible page-cards render — the
    // client-side equivalent of the old <img loading="lazy">.
    function ensurePageObserver() {
      if (pageRenderObserver) return pageRenderObserver;
      pageRenderObserver = new IntersectionObserver((entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const canvas = entry.target;
            // Only stop observing once it actually rendered — unobserving
            // unconditionally meant a single failed fetch/parse left that page
            // permanently blank, since nothing would ever ask it to render again.
            renderPageCanvas(canvas).then(() => {
              if (canvas.dataset.rendered === '1') pageRenderObserver.unobserve(canvas);
            });
          }
        }
      }, { rootMargin: '200px' });
      return pageRenderObserver;
    }

    function observeAllPageCanvases(container) {
      const observer = ensurePageObserver();
      container.querySelectorAll('canvas.page-img:not([data-rendered="1"])').forEach(c => observer.observe(c));
    }

