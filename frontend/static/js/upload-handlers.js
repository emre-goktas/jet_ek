/**
 * upload-handlers.js
 * Sidebar toggle, logout, drag/drop + file-picker upload, and the Sortable.js
 * grid wiring used once a viewer is loaded.
 */

    // Mobile/tablet left-panel drawer (see #sidebar / #sidebar-backdrop rules in
    // app.css) — the sidebar is always visible as a static column at the lg breakpoint
    // and up, so this toggle only has a visible effect below that width.
    function toggleSidebar() {
      document.body.classList.toggle('sidebar-open');
    }

    async function logout() {
      try {
        const res = await fetch('/auth/logout', { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        window.location.href = data.redirect || '/login';
      } catch (e) {
        window.location.href = '/login';
      }
    }

    function handleDrop(e) {
      e.preventDefault();
      const zone = document.getElementById('drop-zone');
      if (zone) zone.classList.remove('border-blue-400', 'bg-blue-950');
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) {
        processFiles(files);
      }
    }

    function uploadFile(input) {
      const zone = document.getElementById('drop-zone');
      if (zone) zone.classList.remove('border-blue-400', 'bg-blue-950');
      const files = Array.from(input.files);
      if (files.length > 0) {
        processFiles(files);
      }
      input.value = ""; // reset
    }
    
    document.addEventListener('DOMContentLoaded', () => {
      const viewer = document.getElementById('viewer');
      viewer.addEventListener('dragover', (e) => {
        e.preventDefault();
        viewer.classList.add('bg-gray-800', 'bg-opacity-50');
      });
      viewer.addEventListener('dragleave', (e) => {
        viewer.classList.remove('bg-gray-800', 'bg-opacity-50');
      });
      viewer.addEventListener('drop', (e) => {
        e.preventDefault();
        viewer.classList.remove('bg-gray-800', 'bg-opacity-50');
        const files = Array.from(e.dataTransfer.files);
        if (files.length > 0) {
          processFiles(files);
        }
      });
      
      const outputList = document.getElementById('output-list');
      if (outputList) {
        new Sortable(outputList, {
          animation: 150,
          ghostClass: 'sortable-ghost',
          dragClass: 'sortable-drag',
          forceFallback: true,
          fallbackClass: 'sortable-drag',
          filter: 'button, a, input',
          preventOnFilter: false
        });
      }

      updateBulkDownloadVisibility();
    });

    async function processFiles(files) {
      const validExts = ['.pdf', '.tiff', '.tif', '.jpeg', '.jpg', '.png'];
      let current = 0;
      let total = files.length;
      let skipped = 0;
      let failed = 0;
      let success = 0;

      for (let file of files) {
        current++;
        const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
        if (!validExts.includes(ext)) {
          skipped++;
          continue;
        }

        // JPEG/PNG are converted to PDF right here in the browser (pdf-lib) —
        // only PDF/TIFF ever reach /upload now. TIFF still goes to the backend
        // (fitz), since there's no browser-side TIFF decoder.
        let uploadFile = file;
        try {
          showProgressBar(current - 1, total, `${file.name} hazırlanıyor (${current}/${total})...`);
          uploadFile = await maybeConvertToPdfBeforeUpload(file);
        } catch (e) {
          console.error('Image->PDF conversion failed:', file.name, e);
          failed++;
          showStatus(`✗ ${file.name}: ${e.message || 'dönüştürme hatası'}`, 'text-red-400');
          continue;
        }

        showProgressBar(current - 1, total, `${file.name} yükleniyor (${current}/${total})...`);
        const isOk = await sendFile(uploadFile);
        if (isOk) {
            success++;
        } else {
            failed++;
        }
      }

      if (skipped > 0 || failed > 0) {
        let msgs = [];
        if (success > 0) msgs.push(`${success} yüklendi`);
        if (skipped > 0) msgs.push(`${skipped} atlandı (desteklenmiyor)`);
        if (failed > 0) msgs.push(`${failed} başarısız`);
        if (success > 0) completeProgressBar(msgs.join(', ')); else hideProgressBar();
        showStatus(`⚠ ${msgs.join(', ')}.`, 'text-yellow-400');
      } else if (success > 0) {
        completeProgressBar(`✓ ${success} yükleme tamamlandı.`);
      } else {
        hideProgressBar();
        showStatus(`⚠ Yüklenecek geçerli dosya yok.`, 'text-yellow-400');
      }
    }

    function initSortable() {
      const inner = document.getElementById('viewer-inner');
      const viewer = document.getElementById('viewer');
      if (!inner) return;

      if (sortableInstance) sortableInstance.destroy();
      sortableInstance = new Sortable(inner, {
        multiDrag: true,
        multiDragKey: 'ctrl',
        selectedClass: 'sortable-native-selected',
        animation: 150,
        handle: '.drag-handle',
        forceFallback: true,
        fallbackClass: 'sortable-drag',
        ghostClass: 'sortable-ghost',
        dragClass: 'sortable-drag',
        scroll: viewer,
        scrollSensitivity: 80,
        scrollSpeed: 20
      });
    }

    async function sendFile(file) {
      const form = new FormData();
      form.append('file', file);
      const perfStart = performance.now();

      try {
        const res = await fetch('/upload', { method: 'POST', body: form });
        if (!res.ok) {
          const err = await res.json();
          showStatus('✗ Hata: ' + err.detail, 'text-red-400');
          if (typeof logPerformance === 'function') logPerformance('upload', { batchCount: 1, fileSizeBytes: file.size, durationMs: performance.now() - perfStart, success: false });
          return false;
        }

        const html = await res.text();
        const viewer = document.getElementById('viewer');

        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = html.trim();
        const pageCount = tempDiv.querySelectorAll('.page-card').length || null;

        let inner = document.getElementById('viewer-inner');
        if (!inner) {
          viewer.innerHTML = html;
        } else {
          // find the viewer-inner or assume tempDiv's first child
          const newInner = tempDiv.querySelector('#viewer-inner') || tempDiv.firstElementChild;
          if (newInner) {
            // Append all children to existing grid
            while (newInner.firstChild) {
              inner.appendChild(newInner.firstChild);
            }
          }
        }

        if (typeof htmx !== 'undefined') {
          htmx.process(document.getElementById('viewer'));
        }

        document.getElementById('toolbar').classList.remove('hidden');
        document.getElementById('upload-hint')?.remove();

        initSortable();
        observeAllPageCanvases(viewer);
        if (typeof logEvent === 'function') logEvent('upload', { filename: file.name });
        if (typeof logPerformance === 'function') logPerformance('upload', { pageCount, batchCount: 1, fileSizeBytes: file.size, durationMs: performance.now() - perfStart, success: true });
        return true;
      } catch (err) {
        showStatus('✗ Bağlantı hatası.', 'text-red-400');
        if (typeof logPerformance === 'function') logPerformance('upload', { batchCount: 1, fileSizeBytes: file.size, durationMs: performance.now() - perfStart, success: false });
        return false;
      }
    }

    function showStatus(msg, cls) {
      const el = document.getElementById('upload-status');
      if (!el) return;
      el.textContent = msg;
      el.className = `text-xs text-center mt-2 ${cls}`;
      el.classList.remove('hidden');
    }

    // Shared progress-bar widget (upload + download flows) — replaces the old
    // "X yükleniyor / tamamlandı" text logs with a visual bar in the same
    // footer slot as #upload-status. hideProgressBar's timer is tracked so a
    // fast second operation (e.g. another download right after one finishes)
    // doesn't get its bar yanked away by the previous operation's pending hide.
    let progressHideTimer = null;

    function progressBarEls() {
      return {
        wrap: document.getElementById('task-progress'),
        fill: document.getElementById('task-progress-fill'),
        pct: document.getElementById('task-progress-pct'),
        label: document.getElementById('task-progress-label'),
      };
    }

    function showProgressBar(current, total, label) {
      const { wrap, fill, pct, label: labelEl } = progressBarEls();
      if (!wrap || !fill) return;
      if (progressHideTimer) { clearTimeout(progressHideTimer); progressHideTimer = null; }
      const percent = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;
      wrap.classList.remove('hidden');
      fill.className = 'bg-blue-500 h-1.5 rounded-full transition-all duration-300 ease-out';
      fill.style.width = `${percent}%`;
      if (pct) pct.textContent = `${percent}%`;
      if (labelEl) labelEl.textContent = label || '';
    }

    // Indeterminate variant for single-request operations with no
    // measurable step count (e.g. a lone file download) — same visual
    // language as the per-row "İşleniyor..." bar in output-panel.js.
    function showProgressBarIndeterminate(label) {
      const { wrap, fill, pct, label: labelEl } = progressBarEls();
      if (!wrap || !fill) return;
      if (progressHideTimer) { clearTimeout(progressHideTimer); progressHideTimer = null; }
      wrap.classList.remove('hidden');
      fill.className = 'bg-blue-500 h-1.5 rounded-full w-2/3 animate-pulse';
      fill.style.width = '';
      if (pct) pct.textContent = '';
      if (labelEl) labelEl.textContent = label || '';
    }

    function completeProgressBar(label) {
      const { wrap, fill, pct, label: labelEl } = progressBarEls();
      if (!wrap || !fill) return;
      fill.className = 'bg-green-500 h-1.5 rounded-full transition-all duration-300 ease-out';
      fill.style.width = '100%';
      if (pct) pct.textContent = '100%';
      if (labelEl) labelEl.textContent = label || '';
      if (progressHideTimer) clearTimeout(progressHideTimer);
      progressHideTimer = setTimeout(hideProgressBar, 1400);
    }

    function hideProgressBar() {
      progressHideTimer = null;
      const { wrap, fill, pct, label: labelEl } = progressBarEls();
      if (!wrap) return;
      wrap.classList.add('hidden');
      if (fill) { fill.style.width = '0%'; fill.className = 'bg-blue-500 h-1.5 rounded-full transition-all duration-300 ease-out'; }
      if (pct) pct.textContent = '';
      if (labelEl) labelEl.textContent = '';
    }

