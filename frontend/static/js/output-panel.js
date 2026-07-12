/**
 * output-panel.js
 * The left-panel output list: loading placeholders, marking/restoring
 * extracted-page state, confirmExtract, the shared postAction() fetch helper,
 * and the page zoom/preview modal.
 */

    // Minimal HTML-escape for text interpolated into innerHTML template literals —
    // reuses the browser's own textContent->innerHTML encoding instead of a
    // hand-rolled regex. Needed anywhere user-typed text (e.g. the custom filename
    // field) gets interpolated into markup rather than assigned via textContent.
    function escapeHtml(str) {
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
    }

    function appendLoadingToOutputList(taskId, filename) {
      const list = document.getElementById('output-list');
      const empty = document.getElementById('output-empty');
      if (empty) empty.remove();

      const wrapper = document.createElement('li');
      wrapper.id = `loading-task-${taskId}`;
      const safeFilename = escapeHtml(filename);
      wrapper.innerHTML = `
        <div class="pdf-item opacity-75 border border-dashed border-gray-800 p-2.5 rounded-lg bg-gray-900/50 flex flex-col gap-2">
          <div class="flex items-start gap-2">
            <svg class="animate-spin w-4 h-4 text-blue-500 shrink-0 mt-0.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
            </svg>
            <div class="flex-1 min-w-0">
              <p class="text-xs font-medium text-gray-400 truncate" title="${safeFilename}">${safeFilename}</p>
              <p class="text-[10px] text-blue-400 font-semibold animate-pulse mt-0.5">İşleniyor...</p>
            </div>
          </div>
          <div class="w-full bg-gray-850 rounded-full h-1 overflow-hidden">
            <div class="bg-blue-500 h-1 rounded-full w-2/3 animate-pulse"></div>
          </div>
        </div>
      `;
      if (isBatchMode && currentBatchIndex >= 0) {
        const listItems = list.querySelectorAll('li:not(#output-empty)');
        const parentLi = listItems[currentBatchIndex];
        const parentFileId = parentLi ? getListItemFileId(parentLi) : null;
        if (parentLi && parentFileId) {
          wrapper.dataset.parentFileId = parentFileId;
          // Insert after the last existing item in this batch's group (the parent itself,
          // or the most recent prior extraction from it) so repeated extractions from the
          // same batch stack in chronological order underneath it, instead of each new one
          // jumping straight above the previous one.
          let insertAfter = parentLi;
          let sibling = parentLi.nextElementSibling;
          while (sibling && sibling.dataset.parentFileId === parentFileId) {
            insertAfter = sibling;
            sibling = sibling.nextElementSibling;
          }
          insertAfter.insertAdjacentElement('afterend', wrapper);
        } else {
          list.appendChild(wrapper);
        }
      } else {
        list.appendChild(wrapper);
      }
      updateBulkDownloadVisibility();
    }

    function getListItemFileId(li) {
      return li?.querySelector('[data-file-id]')?.dataset.fileId || null;
    }

    // Marks the given page-card elements as consumed by outputKey: hides them from
    // their source grid immediately, and records what to restore if outputKey is
    // later deleted from the output list.
    function markPagesExtracted(cardEls, outputKey) {
      outputSourcePages[outputKey] = cardEls.map(card => ({
        pdf_id: card.dataset.pdfId,
        page_idx: parseInt(card.dataset.pageIndex)
      }));
      cardEls.forEach(card => {
        const pid = card.dataset.pdfId;
        const idx = parseInt(card.dataset.pageIndex);
        if (!extractedPageIndices[pid]) extractedPageIndices[pid] = new Set();
        extractedPageIndices[pid].add(idx);
        card.classList.add('extracted-page');
      });
    }

    // Right-click "Sil": hides the given cards from the grid using the exact same
    // extracted-page mechanism as a real extraction (same class, same tracking map),
    // so every existing filter (selection, gatherCurrentGridPages, reconciliation
    // after a re-render) already treats them as gone with no extra bookkeeping. There's
    // no outputSourcePages entry since there's no output to undo it from — in Batch
    // Mode the removal only becomes permanent once "Güncelle" is pressed (same as any
    // other grid edit there); outside Batch Mode nothing is ever persisted, since the
    // original upload is meant to stay intact and reusable for further extractions.
    function markPagesDeleted(cardEls) {
      cardEls.forEach(card => {
        const pid = card.dataset.pdfId;
        const idx = parseInt(card.dataset.pageIndex);
        if (!extractedPageIndices[pid]) extractedPageIndices[pid] = new Set();
        extractedPageIndices[pid].add(idx);
        card.classList.add('extracted-page');
        selectedPages.delete(card.id);
      });
      updateHighlight();
      updateSelectionInfo();
    }

    // Reverses markPagesExtracted for outputKey: un-hides its source pages (if their
    // grid happens to be visible right now) and forgets they were ever extracted.
    function restoreExtractedPages(outputKey) {
      const sources = outputSourcePages[outputKey];
      if (!sources) return;
      delete outputSourcePages[outputKey];
      sources.forEach(({ pdf_id, page_idx }) => {
        extractedPageIndices[pdf_id]?.delete(page_idx);
      });
      reconcileExtractedState();
    }

    // Re-applies the extracted-page hidden state to whatever .page-card elements are
    // currently in the DOM. Needed after the grid is rebuilt from scratch (batch switch,
    // exiting batch mode) since that HTML comes fresh from the server with no notion of
    // "some of these pages were already consumed by a later extraction".
    function reconcileExtractedState() {
      document.querySelectorAll('.page-card').forEach(card => {
        const pid = card.dataset.pdfId;
        const idx = parseInt(card.dataset.pageIndex);
        card.classList.toggle('extracted-page', !!extractedPageIndices[pid]?.has(idx));
      });
    }

    function replaceLoadingWithOutput(taskId, html) {
      const loader = document.getElementById(`loading-task-${taskId}`);
      if (loader) {
        loader.removeAttribute('id');
        loader.innerHTML = html;
        const realFileId = getListItemFileId(loader);
        if (realFileId && outputSourcePages[taskId] && !outputSourcePages[realFileId]) {
          outputSourcePages[realFileId] = outputSourcePages[taskId];
          delete outputSourcePages[taskId];
        }
        updateBulkDownloadVisibility();
      }
    }

    // Restores any pages this output consumed, then removes it from the list.
    function removeOutputItem(button) {
      const li = button.closest('li');
      const fileId = getListItemFileId(li);
      if (fileId) removeOutputByFileId(fileId);
      else li.remove();
    }

    // Same as removeOutputItem, but addressed by file_id instead of a click on its
    // own button — used when code (rather than the user) decides an output should go
    // away, e.g. a batch that's been emptied out via full extraction or full deletion.
    function removeOutputByFileId(fileId) {
      const btn = document.querySelector(`.download-btn[data-file-id='${fileId}']`);
      const li = btn ? btn.closest('li') : null;
      if (!li) return;
      restoreExtractedPages(fileId);
      li.remove();
      selectedBatchIds.delete(fileId);
      updateBulkDownloadVisibility();
      refreshBatchNavStatus();
    }

    async function confirmExtract() {
      if (selectedPages.size === 0) return;

      const cardsInOrder = Array.from(document.querySelectorAll('.page-card'));
      const extractionList = [];
      const extractedCardEls = [];

      cardsInOrder.forEach(card => {
        if (selectedPages.has(card.id)) {
          extractionList.push({
             pdf_id: card.dataset.pdfId,
             page_idx: parseInt(card.dataset.pageIndex),
             rotation: pageRotations[card.id] || 0
          });
          extractedCardEls.push(card);
        }
      });

      if(extractionList.length === 0) {
          return;
      }

      // Generate temporary display filename
      let displayFilename = '';
      if (currentCustomName) {
        displayFilename = `${currentCustomName}.pdf`;
      } else {
        displayFilename = `evrak.pdf`;
      }

      // Generate a temp UI ID for tracking until response
      const tempUiId = 'temp-' + Math.random().toString(36).substring(2, 9);
      appendLoadingToOutputList(tempUiId, displayFilename);
      markPagesExtracted(extractedCardEls, tempUiId);
      clearSelection();

      const res = await postAction('/extract', {
        pages: extractionList,
        custom_name: currentCustomName
      });

      if (res) {
        replaceLoadingWithOutput(tempUiId, res);
        if (typeof logEvent === 'function') logEvent('extract', { page_count: extractionList.length });
        await persistBatchExtractionCut(extractedCardEls); // no-op unless currently viewing a batch in Batch Mode
      } else {
        const loader = document.getElementById(`loading-task-${tempUiId}`);
        if (loader) loader.remove();
        restoreExtractedPages(tempUiId); // extraction failed server-side, undo the optimistic hide
        updateBulkDownloadVisibility();
        // postAction() already showed a status message (timeout-specific for
        // a 404, generic otherwise) — nothing more to show here.
      }
    }



    async function postAction(url, body) {
      try {
        const res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        });
        if (!res.ok) {
          // A 404 here almost always means the source/target file was swept
          // by the 15-minute idle cleanup (see backend/main.py) — reads
          // already keep an in-use file's clock reset, so this only really
          // fires after a genuinely long gap with the tab sitting idle.
          // Surfacing that plainly beats a generic "failed" message that
          // gives no hint the file itself is simply gone.
          if (res.status === 404) {
            showStatus('⏱ Oturumunuz zaman aşımına uğradı — belge uzun süre işlem görmediği için temizlendi. Lütfen dosyayı tekrar yükleyin.', 'text-yellow-400');
          } else {
            showStatus('✗ İşlem başarısız oldu.', 'text-red-400');
          }
          return null;
        }
        showStatus('✓ İşlem tamamlandı.', 'text-green-400');
        return await res.text();
      } catch (e) {
        showStatus('✗ Bağlantı hatası.', 'text-red-400');
        return null;
      }
    }

    async function showPreview(card) {
      const canvas = card.querySelector('.page-img');
      const modalImg = document.getElementById('preview-img');
      // The thumbnail canvas renders lazily (IntersectionObserver) — if the
      // user clicks right as a card scrolls into view, the render may still
      // be in flight. renderPageCanvas no-ops once already rendered, so this
      // is just "make sure it's actually done" before snapshotting it.
      await renderPageCanvas(canvas);
      modalImg.src = canvas.toDataURL('image/png');
      modalImg.style.transform = canvas.style.transform;
      openModal('preview-modal');
    }

    function closePreview() {
      closeModal('preview-modal');
    }

    function appendToOutputList(html) {
      const list = document.getElementById('output-list');
      const empty = document.getElementById('output-empty');
      if (empty) empty.remove();
      const wrapper = document.createElement('li');
      wrapper.innerHTML = html;
      list.appendChild(wrapper);
      updateBulkDownloadVisibility();
    }

    function updateBulkDownloadVisibility() {
      const container = document.getElementById('bulk-download-container');
      const list = document.getElementById('output-list');
      if (!list || !container) return;
      const items = list.querySelectorAll('.pdf-item');
      if (items.length > 0) {
        container.classList.remove('hidden');
      } else {
        container.classList.add('hidden');
      }
    }

