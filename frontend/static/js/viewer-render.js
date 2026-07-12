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
        const task = pdfjsLib.getDocument({ url: `/pdf-source/${pdfId}` });
        pdfDocCache.set(pdfId, task.promise);
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

    async function renderPageCanvas(canvas) {
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
            renderPageCanvas(entry.target);
            pageRenderObserver.unobserve(entry.target);
          }
        }
      }, { rootMargin: '200px' });
      return pageRenderObserver;
    }

    function observeAllPageCanvases(container) {
      const observer = ensurePageObserver();
      container.querySelectorAll('canvas.page-img:not([data-rendered="1"])').forEach(c => observer.observe(c));
    }

