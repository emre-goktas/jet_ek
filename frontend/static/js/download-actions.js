/**
 * download-actions.js
 * Download-confirm modal, the "Adlandır" (AI vs manual rename) menu, and the
 * single-file / Gemini batch-rename download actions.
 */

    // ZIP + Word index packaging used to be GET /download-zip(-numbered); it's
    // now built entirely in the browser — see frontend/static/js/document-builder.js.
    // fileIds: optional subset (from the batch right-click menu's "İndir"); omitted
    // entirely for the sidebar's main "İndir" button, which packages everything.
    let pendingDownloadFileIds = null;
    function openDownloadConfirmModal(fileIds) {
      pendingDownloadFileIds = (fileIds && fileIds.length > 0) ? fileIds : null;
      openModal('download-confirm-modal');
    }

    function closeDownloadConfirmModal() {
      closeModal('download-confirm-modal');
    }

    // ─── "Adlandır" menu: Gemini API vs Manuel ───────────────────────────
    function toggleAiRenameMenu(e) {
      e.stopPropagation();
      document.getElementById('ai-rename-menu')?.classList.toggle('hidden');
    }

    function closeAiRenameMenu() {
      document.getElementById('ai-rename-menu')?.classList.add('hidden');
    }

    document.addEventListener('click', (e) => {
      const menu = document.getElementById('ai-rename-menu');
      if (menu && !menu.classList.contains('hidden') && !menu.contains(e.target) && !e.target.closest('#btn-ai-rename')) {
        closeAiRenameMenu();
      }
    });

    // "Manuel": skips Gemini entirely — opens the same rename/preview modal the
    // pencil icon on a PDF item opens, pre-loaded with the first batch in the list.
    function openFirstBatchManualRename() {
      const renameBtn = document.querySelector('#output-list li:not(#output-empty) .rename-btn');
      if (renameBtn) {
        renameBtn.click();
      } else {
        showStatus('Önce en az bir PDF oluşturmalısınız.', 'text-yellow-400');
      }
    }

    function confirmDownload(numbered) {
      closeDownloadConfirmModal();
      buildAndDownloadZip(numbered, pendingDownloadFileIds);
      pendingDownloadFileIds = null;
    }

    // explicitFileIds: passed by the batch right-click menu ("AI ile Adlandır" on
    // one item or the current multi-selection). Without it, falls back to the
    // sidebar checkbox selection if any batches are checked, else every batch —
    // so the "Adlandır" button's "Gemini API" option automatically respects
    // whatever's selected without needing its own separate code path.
    async function runJetRenameAll(explicitFileIds) {
      const apiKey = getGeminiApiKey();
      if (!apiKey) {
        openApiKeyModal();
        return;
      }

      let targetIds = (explicitFileIds && explicitFileIds.length > 0)
        ? explicitFileIds
        : (selectedBatchIds.size > 0 ? Array.from(selectedBatchIds) : null);

      // /ai/jet-rename-batch needs a real file_id per item — materialize any
      // still-pending rows in the target set in ONE /extract/batch-split call
      // (materializeRows, output-panel.js) rather than one /extract call per
      // row: with dozens/hundreds of pending rows (this app's normal scale),
      // materializing one at a time was slow and could blow through
      // /extract's 30/minute limit.
      if (targetIds) {
        const pendingTargets = targetIds.filter(id => isPendingFileId(id));
        if (pendingTargets.length > 0) {
          const materialized = await materializeRows(pendingTargets);
          targetIds = targetIds.map(id => isPendingFileId(id) ? materialized[id] : id).filter(Boolean);
        }
        if (targetIds.length === 0) return;
      } else {
        const pendingIds = Object.keys(pendingOutputs);
        if (pendingIds.length > 0) await materializeRows(pendingIds);
      }

      // Find the relevant download buttons in the list to extract the file IDs
      const downloadBtns = Array.from(document.querySelectorAll('#output-list .download-btn'))
        .filter(btn => !targetIds || targetIds.includes(btn.dataset.fileId));
      if (downloadBtns.length === 0) return;

      const fileIds = [];
      const originalBtns = {};
      const listItems = {};

      downloadBtns.forEach((btn, index) => {
        const fileId = btn.dataset.fileId;
        const li = btn.closest('li');
        if (!li) return;
        
        fileIds.push(fileId);
        listItems[fileId] = li;

        // Add domino animation class with a slight delay for visual effect
        setTimeout(() => {
          li.classList.add('animate-domino');
          setTimeout(() => li.classList.remove('animate-domino'), 600);
        }, index * 100);

        // Find the rename button (pen icon) and replace it with a spinner temporarily
        const renameBtn = li.querySelector('button[onclick^="openRenameModal"]');
        if (renameBtn) {
          originalBtns[fileId] = renameBtn.outerHTML;
          renameBtn.outerHTML = `<button type="button" class="text-blue-400 cursor-wait focus:outline-none" disabled data-spinner-for="${fileId}">
            <svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
          </button>`;
        }
      });

      if (fileIds.length === 0) return;

      try {
        const res = await fetch(`/ai/jet-rename-batch`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Gemini-Api-Key': apiKey },
          body: JSON.stringify({ file_ids: fileIds })
        });

        if (res.ok) {
          const results = await res.json();
          // Update all successfully renamed files
          for (const [fileId, htmlSnippet] of Object.entries(results)) {
             if (listItems[fileId]) {
               listItems[fileId].innerHTML = htmlSnippet;
               // The fresh partial has no notion of "was selected" — drop it from
               // the selection set to match the now-unchecked checkbox it just got.
               selectedBatchIds.delete(fileId);
             }
          }
          // Restore buttons for files that failed or were missing from the AI response
          for (const fileId of fileIds) {
             if (!results[fileId] && originalBtns[fileId] && listItems[fileId]) {
                const spinnerBtn = listItems[fileId].querySelector(`button[data-spinner-for="${fileId}"]`);
                if (spinnerBtn) spinnerBtn.outerHTML = originalBtns[fileId];
             }
          }
          if (typeof logEvent === 'function') logEvent('ai_rename', { requested: fileIds.length, succeeded: Object.keys(results).length });
        } else {
          console.error('Failed to batch rename files');
          let errMsg = 'Toplu isimlendirme sırasında hata oluştu.';
          try {
            const errBody = await res.json();
            if (errBody && errBody.detail) errMsg = errBody.detail;
          } catch (e) { /* not JSON, keep default message */ }
          alert(errMsg);
          // Restore all buttons
          for (const fileId of fileIds) {
             if (originalBtns[fileId] && listItems[fileId]) {
                const spinnerBtn = listItems[fileId].querySelector(`button[data-spinner-for="${fileId}"]`);
                if (spinnerBtn) spinnerBtn.outerHTML = originalBtns[fileId];
             }
          }
        }
      } catch (e) {
        console.error('Error during batch rename', e);
        alert('Toplu isimlendirme sırasında hata oluştu.');
        for (const fileId of fileIds) {
           if (originalBtns[fileId] && listItems[fileId]) {
              const spinnerBtn = listItems[fileId].querySelector(`button[data-spinner-for="${fileId}"]`);
              if (spinnerBtn) spinnerBtn.outerHTML = originalBtns[fileId];
           }
        }
      }
    }

    // Fetch+blob (rather than a window.location.href navigation) so we get a
    // completion signal to hang the post-delivery /cleanup call off of —
    // see cleanupDeliveredFiles() in document-builder.js.
    async function downloadSingleFile(fileId, btn) {
      if (isPendingFileId(fileId)) {
        const realId = await materializeRow(fileId);
        if (!realId) return; // materializeRow/postAction already showed a status message
        fileId = realId;
        btn = document.querySelector(`.download-btn[data-file-id='${realId}']`); // the row's innerHTML was just replaced
        if (!btn) return;
      }

      const listItems = Array.from(document.querySelectorAll('#output-list li'));
      const li = btn.closest('li');
      let count = 0;
      let index = 1;
      for (let i = 0; i < listItems.length; i++) {
         if (listItems[i].id === 'output-empty') continue;
         count++;
         if (listItems[i] === li) {
            index = count;
            break;
         }
      }

      const perfStart = performance.now();
      const pageCount = parseInt(li?.querySelector('.rename-btn')?.dataset.pageCount, 10) || null;

      if (typeof showProgressBarIndeterminate === 'function') showProgressBarIndeterminate('İndiriliyor...');
      try {
        const res = await fetch(`/download/${fileId}?ek_no=${index}`);
        if (!res.ok) {
          if (typeof hideProgressBar === 'function') hideProgressBar();
          showStatus('✗ İndirme başarısız oldu.', 'text-red-400');
          if (typeof logPerformance === 'function') logPerformance('download_single', { pageCount, batchCount: 1, durationMs: performance.now() - perfStart, success: false });
          return;
        }
        const blob = await res.blob();
        const filename = li?.querySelector('p.truncate')?.textContent?.trim() || `${fileId}.pdf`;
        triggerBlobDownload(blob, ekPrefixedFilename(index, filename));
        if (typeof completeProgressBar === 'function') completeProgressBar('✓ İndirme tamamlandı');
        if (typeof logEvent === 'function') logEvent('download_single', {});
        if (typeof logPerformance === 'function') logPerformance('download_single', { pageCount, batchCount: 1, fileSizeBytes: blob.size, durationMs: performance.now() - perfStart, success: true });
        await cleanupDeliveredFiles([fileId]);
      } catch (e) {
        console.error('Download failed:', e);
        if (typeof hideProgressBar === 'function') hideProgressBar();
        showStatus('✗ İndirme sırasında hata oluştu.', 'text-red-400');
        if (typeof logPerformance === 'function') logPerformance('download_single', { pageCount, batchCount: 1, durationMs: performance.now() - perfStart, success: false });
      }
    }

