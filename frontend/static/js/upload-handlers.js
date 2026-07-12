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
          showStatus(`⏳ ${file.name} hazırlanıyor (${current}/${total})...`, 'text-gray-400');
          uploadFile = await maybeConvertToPdfBeforeUpload(file);
        } catch (e) {
          console.error('Image->PDF conversion failed:', file.name, e);
          failed++;
          showStatus(`✗ ${file.name}: ${e.message || 'dönüştürme hatası'}`, 'text-red-400');
          continue;
        }

        showStatus(`⏳ ${file.name} yükleniyor (${current}/${total})...`, 'text-gray-400');
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
        showStatus(`⚠ ${msgs.join(', ')}.`, 'text-yellow-400');
      } else if (success > 0) {
        showStatus(`✓ ${success} yükleme tamamlandı.`, 'text-green-400');
      } else {
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

      try {
        const res = await fetch('/upload', { method: 'POST', body: form });
        if (!res.ok) {
          const err = await res.json();
          showStatus('✗ Hata: ' + err.detail, 'text-red-400');
          return false;
        }

        const html = await res.text();
        const viewer = document.getElementById('viewer');
        
        let inner = document.getElementById('viewer-inner');
        if (!inner) {
          viewer.innerHTML = html;
        } else {
          // Robustly append elements
          const tempDiv = document.createElement('div');
          tempDiv.innerHTML = html.trim();
          
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
        return true;
      } catch (err) {
        showStatus('✗ Bağlantı hatası.', 'text-red-400');
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

