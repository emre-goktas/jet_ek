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

    function loadingRowInnerHtml(filename) {
      const safeFilename = escapeHtml(filename);
      return `
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
    }

    // Places a freshly-built <li> (loading placeholder, pending row, or a
    // real completed one) into #output-list — while inside Batch Mode, new
    // rows stack chronologically right under the batch they came from
    // instead of jumping to the top of the whole list.
    function insertOutputListWrapper(wrapper) {
      const list = document.getElementById('output-list');
      const empty = document.getElementById('output-empty');
      if (empty) empty.remove();

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

    function pendingDisplayFilename(pending) {
      return pending.customName ? `${pending.customName}.pdf` : 'evrak.pdf';
    }

    // Same DOM shape as the server-rendered partials/pdf_item.html (same
    // classes, same data-file-id/data-custom-name, same button wiring) so
    // every existing consumer of an output-list row — the checkbox, rename
    // button, delete button, batch context menu, gatherOutputFilesData —
    // works on a pending row completely unmodified. pendingId doubles as
    // data-file-id; isPendingFileId() is what tells the two apart anywhere
    // a real backend call is about to be made from one.
    function pendingItemHtml(pendingId, pages, customName) {
      const filename = pendingDisplayFilename({ customName });
      const safeFilename = escapeHtml(filename);
      const safeCustomName = escapeHtml(customName || '');
      const pageCount = pages.length;
      return `
        <div class="pdf-item pdf-item-pending" data-file-id="${pendingId}" oncontextmenu="openBatchContextMenu(event, this)">
          <div class="output-select-checkbox-wrap">
            <input type="checkbox" class="output-select-checkbox" onclick="event.stopPropagation(); toggleOutputSelection(this, '${pendingId}')" title="Bu belgeyi seç">
          </div>
          <div class="flex items-start gap-2">
            <svg class="w-4 h-4 text-amber-400 mt-0.5 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round"
                d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"/>
            </svg>
            <div class="flex-1 min-w-0">
              <p class="text-xs font-medium text-gray-200 truncate" title="${safeFilename}">${safeFilename}</p>
              <p class="text-xs text-gray-500 mt-0.5">${pageCount} sayfa</p>
            </div>
          </div>
          <div class="flex items-center gap-2 mt-2">
            <button
              data-file-id="${pendingId}"
              data-custom-name="${safeCustomName}"
              onclick="downloadSingleFile('${pendingId}', this)"
              class="download-btn flex-1 text-center"
            >
              ↓ İndir
            </button>
            <button
              onclick="openRenameModal('${pendingId}', '${safeCustomName || safeFilename}', ${pageCount})"
              class="rename-btn p-2 text-gray-400 hover:text-white bg-gray-800 hover:bg-gray-700 rounded transition-colors"
              data-file-id="${pendingId}"
              data-page-count="${pageCount}"
              title="Yeniden adlandır"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round"
                  d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/>
              </svg>
            </button>
            <button
              onclick="removeOutputItem(this)"
              class="p-2 text-gray-400 hover:text-red-400 bg-gray-800 hover:bg-gray-700 rounded transition-colors"
              title="Sil"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>
        </div>
      `;
    }

    function addPendingRowToOutputList(pendingId) {
      const pending = pendingOutputs[pendingId];
      if (!pending) return;
      const wrapper = document.createElement('li');
      wrapper.innerHTML = pendingItemHtml(pendingId, pending.pages, pending.customName);
      insertOutputListWrapper(wrapper);
    }

    // Updates a pending row's displayed name in place after a rename — mirrors
    // how a materialized row's rename swaps in fresh server HTML (submitRename
    // in rename-modal.js), just rendered client-side since there's nothing to
    // ask the server for yet.
    function updatePendingRowDisplay(pendingId) {
      const pending = pendingOutputs[pendingId];
      if (!pending) return;
      const li = document.querySelector(`.download-btn[data-file-id='${pendingId}']`)?.closest('li');
      if (!li) return;
      li.innerHTML = pendingItemHtml(pendingId, pending.pages, pending.customName);
    }

    // Cuts a pending row into a real backend file on demand — the moment
    // something needs actual bytes server-side (opening it in Grup
    // Düzenleyici, a single-item "İndir", AI ile yeniden adlandır), instead
    // of waiting for the bulk "İndir" finalize pass. Every other still-pending
    // row is left untouched. In-flight de-duped per pendingId so a double
    // click (or two different trigger points racing on the same row) can't
    // fire two /extract calls — and thus create two orphaned real files — for
    // one logical row. Resolves to the new real file_id, or null on failure
    // (postAction() already surfaced a status message in that case).
    let materializingPromises = {};

    function materializeRow(pendingId) {
      const pending = pendingOutputs[pendingId];
      if (!pending) return Promise.resolve(null);
      if (materializingPromises[pendingId]) return materializingPromises[pendingId];

      const p = (async () => {
        const li = document.querySelector(`.download-btn[data-file-id='${pendingId}']`)?.closest('li');
        if (!li) return null;

        li.id = `loading-task-${pendingId}`;
        li.innerHTML = loadingRowInnerHtml(pendingDisplayFilename(pending));

        const res = await postAction('/extract', {
          pages: pending.pages,
          custom_name: pending.customName || null
        });

        if (!res) {
          li.removeAttribute('id');
          li.innerHTML = pendingItemHtml(pendingId, pending.pages, pending.customName);
          return null;
        }

        replaceLoadingWithOutput(pendingId, res);
        delete pendingOutputs[pendingId];
        selectedBatchIds.delete(pendingId); // fresh HTML has no notion of "was selected", mirrors runJetRenameAll's own cleanup
        return getListItemFileId(li);
      })();

      materializingPromises[pendingId] = p;
      p.finally(() => { delete materializingPromises[pendingId]; });
      return p;
    }

    // Bulk counterpart to materializeRow — cuts many still-pending rows in
    // ONE /extract/batch-split call instead of one /extract call per row.
    // Needed for runJetRenameAll's "AI ile Adlandır" on a whole batch:
    // materializing rows one at a time was both slow (one round trip per
    // row) and could blow straight through /extract's 30/minute limit once
    // a batch got past ~30 rows — this app's whole use case is hundreds of
    // documents at once (see split-mode.js), so that wasn't a corner case.
    // Chunked at MAX_SPLIT_GROUPS (split-mode.js) since /extract/batch-split
    // itself rejects a request bigger than that. Rows already being
    // materialized by a concurrent materializeRow() call are left alone —
    // materializeRow's own promise is awaited instead of re-submitting them.
    // Returns a map of pendingId -> real file_id (or null for any that
    // failed to resolve — that row is rolled back to its pending display).
    async function materializeRows(pendingIds) {
      const results = {};
      const inFlight = pendingIds.filter(id => materializingPromises[id]);
      const targets = pendingIds.filter(id => pendingOutputs[id] && !materializingPromises[id]);

      for (const id of inFlight) {
        results[id] = await materializingPromises[id];
      }

      for (let start = 0; start < targets.length; start += MAX_SPLIT_GROUPS) {
        const chunk = targets.slice(start, start + MAX_SPLIT_GROUPS);
        Object.assign(results, await materializeRowsChunk(chunk));
      }
      return results;
    }

    async function materializeRowsChunk(targets) {
      const lis = {};
      targets.forEach(id => {
        const li = document.querySelector(`.download-btn[data-file-id='${id}']`)?.closest('li');
        if (!li) return;
        lis[id] = li;
        li.id = `loading-task-${id}`;
        li.innerHTML = loadingRowInnerHtml(pendingDisplayFilename(pendingOutputs[id]));
      });

      const rollback = () => {
        const results = {};
        targets.forEach(id => {
          const li = lis[id];
          if (li) { li.removeAttribute('id'); li.innerHTML = pendingItemHtml(id, pendingOutputs[id].pages, pendingOutputs[id].customName); }
          results[id] = null;
        });
        return results;
      };

      const payload = {
        groups: targets.map(id => ({
          pages: pendingOutputs[id].pages,
          custom_name: pendingOutputs[id].customName || null,
        })),
      };

      let res;
      try {
        res = await fetch('/extract/batch-split', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } catch (e) {
        showStatus('✗ Bağlantı hatası.', 'text-red-400');
        return rollback();
      }

      if (!res.ok) {
        showStatus(
          res.status === 404
            ? '⏱ Oturumunuz zaman aşımına uğradı — belge temizlendi. Lütfen tekrar yükleyin.'
            : '✗ Belgeler oluşturulamadı.',
          res.status === 404 ? 'text-yellow-400' : 'text-red-400'
        );
        return rollback();
      }

      const resultMap = await res.json();
      const results = {};
      targets.forEach((id, i) => {
        const li = lis[id];
        const html = resultMap[`group-${i}`];
        if (html && li) {
          replaceLoadingWithOutput(id, html);
          delete pendingOutputs[id];
          selectedBatchIds.delete(id);
          results[id] = getListItemFileId(li);
        } else {
          if (li) { li.removeAttribute('id'); li.innerHTML = pendingItemHtml(id, pendingOutputs[id].pages, pendingOutputs[id].customName); }
          results[id] = null;
        }
      });
      return results;
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
      delete pendingOutputs[fileId]; // no-op for a real fileId — this is what makes "Sil" on a never-materialized row completely free (no backend call ever happened)
      updateBulkDownloadVisibility();
      refreshBatchNavStatus();
    }

    // Adds the current selection to the output list as a pending row — pure
    // client-side metadata, no backend call. The actual cut happens later,
    // either on demand (materializeRow, if the user opens this row in Grup
    // Düzenleyici / downloads it alone / AI-renames it) or all at once when
    // "İndir" sends every still-pending row to /extract/finalize in one pass.
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

      const pendingId = makePendingId();
      pendingOutputs[pendingId] = { pendingId, pages: extractionList, customName: currentCustomName || '' };

      addPendingRowToOutputList(pendingId);
      markPagesExtracted(extractedCardEls, pendingId);
      clearSelection();

      if (typeof logEvent === 'function') logEvent('extract', { page_count: extractionList.length });
      await persistBatchExtractionCut(extractedCardEls); // no-op unless currently viewing a batch in Batch Mode — still a real server cut of the parent batch, independent of the new child row being pending
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

