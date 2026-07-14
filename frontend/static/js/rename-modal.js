/**
 * rename-modal.js
 * The naming/rename modal: autosave-while-typing, its per-batch preview pane
 * (prev/next page, prev/next batch), and submitRename.
 */

    // ─── Rename modal auto-save ──────────────────────────────────────────
    // The modal's own prev/next buttons use onmousedown="event.preventDefault()"
    // (so clicking them doesn't yank focus/cursor out of the textarea while
    // typing), which as a side effect also suppresses the textarea's blur —
    // so nothing here can rely on a blur/onchange handler the way Batch
    // Mode's grid-view rename input does. Instead: a short debounce saves
    // while the user is still typing (so nothing is lost even if they just
    // walk away), and every way of leaving a batch (nav buttons, Alt+Up/Down,
    // Kapat) explicitly flushes first so there's never a race between "still
    // debouncing" and "already switched to a different file_id".
    let renameAutoSaveTimer = null;
    let renameAutoSaveLastSent = {};

    function getTrimmedCustomFilename() {
      const el = document.getElementById('custom-filename');
      return el ? el.value.replace(/[\r\n]+/g, ' ').trim() : '';
    }

    function scheduleRenameAutoSave() {
      if (!renamingFileId) return;
      clearTimeout(renameAutoSaveTimer);
      renameAutoSaveTimer = setTimeout(flushRenameAutoSave, 700);
    }

    async function flushRenameAutoSave() {
      clearTimeout(renameAutoSaveTimer);
      renameAutoSaveTimer = null;
      if (!renamingFileId) return;
      const value = getTrimmedCustomFilename();
      if (!value || renameAutoSaveLastSent[renamingFileId] === value) return;
      renameAutoSaveLastSent[renamingFileId] = value;
      await submitRename(renamingFileId, value);
    }

    function doExtract() {
      if (quickSplitModeActive) {
        runQuickSplit();
        return;
      }
      if (selectedPages.size === 0) return;
      currentCustomName = ''; // Force auto-naming
      confirmExtract(true);
    }

    // Every generated PDF in the left panel is a "batch". Ordered by DOM position
    // so batch-switching in the rename preview matches the order shown in the list.
    function getRenameQueueButtons() {
        return Array.from(document.querySelectorAll('#output-list li:not(#output-empty) .rename-btn'));
    }

    async function updateBatchPreviewUI() {
        if (batchPreviewItems.length === 0) return;
        const item = batchPreviewItems[currentBatchPreviewIndex];

        const previewImg = document.getElementById('naming-preview-img');
        if (previewImg) {
            previewImg.src = await renderPageDataUrl(item.pdfId, item.pageIndex);
            previewImg.dataset.rotation = item.rotation;
            if (typeof resetZoom === 'function') resetZoom();
        }

        const queueButtons = getRenameQueueButtons();
        const queueLength = queueButtons.length;
        const queueIndex = queueButtons.findIndex(btn => btn.dataset.fileId === renamingFileId);
        const hasMultiplePages = batchPreviewItems.length > 1;
        const hasMultipleBatches = queueLength > 1;

        const navContainer = document.getElementById('preview-nav-container');
        if (navContainer) navContainer.style.display = (hasMultiplePages || hasMultipleBatches) ? "flex" : "none";

        const pageNav = document.getElementById('preview-page-nav');
        if (pageNav) {
            pageNav.style.display = hasMultiplePages ? "flex" : "none";
            if (hasMultiplePages) {
                document.getElementById('preview-page-input').value = currentBatchPreviewIndex + 1;
                document.getElementById('preview-total-pages').textContent = batchPreviewItems.length;
            }
        }

        const batchStatus = document.getElementById('preview-batch-status');
        if (batchStatus) {
            batchStatus.style.display = hasMultipleBatches ? "block" : "none";
            if (hasMultipleBatches) {
                batchStatus.textContent = `Grup ${queueIndex + 1} / ${queueLength}`;
            }
        }

    }

    function previewPrevPage() {
        if (batchPreviewItems.length === 0) return;
        currentBatchPreviewIndex--;
        if (currentBatchPreviewIndex < 0) {
            currentBatchPreviewIndex = batchPreviewItems.length - 1;
        }
        updateBatchPreviewUI();
    }
    
    function previewNextPage() {
        if (batchPreviewItems.length === 0) return;
        currentBatchPreviewIndex++;
        if (currentBatchPreviewIndex >= batchPreviewItems.length) {
            currentBatchPreviewIndex = 0;
        }
        updateBatchPreviewUI();
    }
    
    function previewGoToPage() {
        const input = document.getElementById('preview-page-input');
        let val = parseInt(input.value);
        if (isNaN(val)) val = 1;
        
        if (val < 1) {
            val = batchPreviewItems.length;
        } else if (val > batchPreviewItems.length) {
            val = 1;
        }
        
        currentBatchPreviewIndex = val - 1;
        updateBatchPreviewUI();
    }

    let renamingFileId = null;

    function proceedToExtract() {
      let input = document.getElementById('custom-filename').value.replace(/[\r\n]+/g, ' ').trim();
      currentCustomName = input || 'evrak';
      
      closeNamingModal();
      
      if (renamingFileId) {
        submitRename(renamingFileId, currentCustomName);
        renamingFileId = null;
      } else {
        confirmExtract(true);
      }
    }

    function loadRenameModalContent(fileId, currentName, pageCount) {
      renamingFileId = fileId;

      batchPreviewItems = [];
      for (let i = 0; i < pageCount; i++) {
        batchPreviewItems.push({ pdfId: fileId, pageIndex: i, rotation: 0 });
      }
      currentBatchPreviewIndex = 0;
      updateBatchPreviewUI();

      const input = document.getElementById('custom-filename');
      const baseName = currentName.replace(/\.pdf$/i, '');
      input.value = baseName;
      // Seed with the name already on disk so an unmodified switch away
      // from this batch doesn't fire a redundant no-op save.
      renameAutoSaveLastSent[fileId] = baseName;
    }

    function openRenameModal(fileId, currentName, pageCount = 1) {
      loadRenameModalContent(fileId, currentName, pageCount);
      openModal('naming-modal');
      document.getElementById('custom-filename').focus();
    }

    // Switches the rename preview to the previous/next generated PDF ("batch") in the
    // left panel, wrapping around. Independent of the main grid's Batch Mode navigation.
    // Always flushes the pending name first — even when there's only one batch and
    // there's nowhere to navigate to — so "type a name, hit Sonraki/Önceki Ek" never
    // silently drops the edit.
    async function previewPrevBatch() {
      await flushRenameAutoSave();
      const queueButtons = getRenameQueueButtons();
      if (queueButtons.length <= 1) return;
      let idx = queueButtons.findIndex(btn => btn.dataset.fileId === renamingFileId);
      if (idx === -1) idx = 0;
      idx = (idx - 1 + queueButtons.length) % queueButtons.length;
      switchRenameModalToQueueButton(queueButtons[idx]);
    }

    async function previewNextBatch() {
      await flushRenameAutoSave();
      const queueButtons = getRenameQueueButtons();
      if (queueButtons.length <= 1) return;
      let idx = queueButtons.findIndex(btn => btn.dataset.fileId === renamingFileId);
      if (idx === -1) idx = 0;
      idx = (idx + 1) % queueButtons.length;
      switchRenameModalToQueueButton(queueButtons[idx]);
    }

    function switchRenameModalToQueueButton(btn) {
      const fileId = btn.dataset.fileId;
      const pageCount = parseInt(btn.dataset.pageCount, 10) || 1;
      const filenameEl = btn.closest('li')?.querySelector('p.truncate');
      const filename = filenameEl ? filenameEl.textContent : fileId;
      loadRenameModalContent(fileId, filename, pageCount);
      document.getElementById('custom-filename').focus();
    }

    async function submitRename(fileId, newName) {
      const res = await postAction('/rename/' + fileId, { custom_name: newName });
      if (res) {
        const link = document.querySelector(`.download-btn[data-file-id='${fileId}']`);
        if (link) {
          const li = link.closest('li');
          if (li) {
            li.innerHTML = res;
          }
        }
      }
    }

