/**
 * batch-mode.js
 * Batch Mode: stepping through generated PDFs in the main grid, persisting
 * grid edits (reorder/rotate) back to the server, and the extraction-as-cut
 * bookkeeping that keeps a source batch in sync with what's been pulled out
 * of it.
 */

    // BATCH MODE LOGIC
    function toggleBatchMode() {
        isBatchMode = !isBatchMode;
        const uploadSection = document.getElementById('drop-zone');
        const uploadStatus = document.getElementById('upload-status');
        const batchNavUI = document.getElementById('batch-nav-ui');

        document.body.classList.remove('sidebar-open'); // reveal the grid on mobile after toggling from the drawer

        if (isBatchMode) {
            // Backup current viewer state
            const firstCard = document.querySelector('.page-card');
            if (firstCard && firstCard.dataset.pdfId) {
                // If it's a batch, we might overwrite originalPdfId. Wait, if it's already in batch mode?
                // No, we are entering batch mode here, so the grid currently holds the original upload.
                originalPdfId = firstCard.dataset.pdfId;
            }
            // For page count and filename, we assume they are handled by backend or we can just fetch original again.
            // Actually, we can just load the first batch if any exist.
            uploadSection.classList.add('hidden');
            uploadStatus.classList.add('hidden');
            batchNavUI.classList.remove('hidden');
            
            const listItems = document.querySelectorAll('#output-list li:not(#output-empty) .download-btn');
            if (listItems.length > 0) {
                currentBatchIndex = 0;
                // loadBatch can fail (e.g. a still-pending row's materialize call
                // fails) — nothing valid to fall back to on the very first entry,
                // so revert out of Batch Mode the same way the "no batches" case
                // above already does.
                loadBatch(currentBatchIndex).then(ok => { if (!ok) toggleBatchMode(); });
            } else {
                showStatus('Önizlenecek grup yok', 'text-yellow-400');
                toggleBatchMode(); // revert
            }
            // Auto focus input when entering batch mode
            setTimeout(() => document.getElementById('batch-name-input').focus(), 50);
        } else {
            uploadSection.classList.remove('hidden');
            uploadStatus.classList.remove('hidden');
            batchNavUI.classList.add('hidden');
            
            currentBatchIndex = -1;
            
            // Restore original upload if exists
            if (originalPdfId) {
                // To restore the grid, we need the viewer.html endpoint for the original pdf.
                // For now, if originalPdfId exists, we can re-fetch it from a new endpoint `GET /batch_viewer/{pdf_id}`
                // since it's the same logic!
                fetchAndRenderBatch(originalPdfId, 'Original Upload');
            } else {
                // Clear grid
                document.getElementById('viewer').innerHTML = `
                    <div id="upload-hint" class="flex flex-col items-center justify-center h-full gap-4 text-gray-600">
                      <svg class="w-20 h-20" fill="none" stroke="currentColor" stroke-width="1" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>
                      <p class="text-lg">Aşağıdan bir PDF yükleyin</p>
                    </div>`;
                document.getElementById('toolbar').classList.add('hidden');
            }
        }
    }

    function prevBatch() {
        const listItems = document.querySelectorAll('#output-list li:not(#output-empty) .download-btn');
        if (listItems.length === 0) return;
        const prevIndex = currentBatchIndex;
        currentBatchIndex--;
        if (currentBatchIndex < 0) currentBatchIndex = listItems.length - 1;
        loadBatch(currentBatchIndex).then(ok => { if (!ok) currentBatchIndex = prevIndex; });
    }

    function nextBatch() {
        const listItems = document.querySelectorAll('#output-list li:not(#output-empty) .download-btn');
        if (listItems.length === 0) return;
        const prevIndex = currentBatchIndex;
        currentBatchIndex++;
        if (currentBatchIndex >= listItems.length) currentBatchIndex = 0;
        loadBatch(currentBatchIndex).then(ok => { if (!ok) currentBatchIndex = prevIndex; });
    }

    // Grup Düzenleyici only ever views a real backend file — a still-pending
    // row (see viewer-state.js's pendingOutputs) is materialized on demand
    // right here before /batch_viewer is ever called. Returns whether a batch
    // was actually loaded, so callers can revert/restore their own index on
    // failure instead of being left pointed at a batch that never rendered.
    async function loadBatch(index) {
        let listItems = document.querySelectorAll('#output-list li:not(#output-empty) .download-btn');
        if (index < 0 || index >= listItems.length) return false;

        let fileId = listItems[index].dataset.fileId;
        if (isPendingFileId(fileId)) {
            const realId = await materializeRow(fileId);
            if (!realId) {
                showStatus('✗ Grup açılamadı — sayfalar oluşturulamadı.', 'text-red-400');
                return false;
            }
            listItems = document.querySelectorAll('#output-list li:not(#output-empty) .download-btn'); // materializeRow only swapped this row's innerHTML in place — same positions, fresh element
            fileId = listItems[index].dataset.fileId;
        }

        const filenameEl = listItems[index].closest('li').querySelector('p.truncate');
        const filename = filenameEl ? filenameEl.textContent : 'Grup';

        document.getElementById('batch-nav-status').textContent = `${index + 1} / ${listItems.length}`;
        document.getElementById('batch-name-input').value = filename.replace(/\.pdf$/i, '');

        // Highlight active batch in left panel
        document.querySelectorAll('#output-list li').forEach(li => li.classList.remove('batch-active'));
        listItems[index].closest('li').classList.add('batch-active');

        fetchAndRenderBatch(fileId, filename);

        // Auto focus input when switching batches
        setTimeout(() => document.getElementById('batch-name-input').focus(), 50);
        return true;
    }

    // Keeps currentBatchIndex and the "X / Y" nav counter correct after the output list
    // changes shape without a batch-nav action causing it (e.g. deleting an item). The
    // batch actually being viewed is identified by its file_id (read off the page-cards
    // currently in the grid), not by position, since deleting an earlier item shifts
    // everyone after it down by one.
    function refreshBatchNavStatus() {
        if (!isBatchMode) return;

        const listItems = document.querySelectorAll('#output-list li:not(#output-empty) .download-btn');
        const total = listItems.length;
        const viewedFileId = document.querySelector('.page-card')?.dataset.pdfId;
        const newIndex = viewedFileId
            ? Array.from(listItems).findIndex(btn => btn.dataset.fileId === viewedFileId)
            : -1;

        if (newIndex === -1) {
            // The batch we were viewing was itself the one just removed.
            if (total > 0) {
                loadBatch(Math.min(currentBatchIndex, total - 1));
            } else {
                toggleBatchMode(); // no batches left; fall back out of batch mode
            }
            return;
        }

        currentBatchIndex = newIndex;
        const statusEl = document.getElementById('batch-nav-status');
        if (statusEl) statusEl.textContent = `${newIndex + 1} / ${total}`;
    }

    // pageRotations deliberately survives switching away from a batch without
    // clicking "Güncelle" (see persistPagesToBatch's scoped clear), so a page-card
    // rebuilt by fetchAndRenderBatch can be re-created with a rotation already
    // recorded under its id from a previous, unsaved visit. Without this, the fresh
    // canvas renders unrotated (visually correct-looking) while gatherCurrentGridPages
    // still reads the stale entry and silently ships that old rotation to the server
    // on the next save — this re-applies the CSS transform so what's on screen always
    // matches what pageRotations actually holds.
    function reapplyStoredRotations(container) {
      container.querySelectorAll('.page-card').forEach(card => {
        const rotation = pageRotations[card.id];
        if (rotation) {
          const img = card.querySelector('.page-img');
          if (img) img.style.transform = `rotate(${rotation}deg)`;
        }
      });
    }

    async function fetchAndRenderBatch(fileId, filename) {
        try {
            const res = await fetch('/batch_viewer/' + fileId);
            if (!res.ok) throw new Error('Failed to load batch view');

            // Reusing HTMX logic by manually processing the response or just injecting HTML
            // The endpoint should return partials/viewer.html
            const html = await res.text();

            // Extract the HX-Trigger headers to trigger viewerReady manually
            const pageCountMatch = html.match(/data-page-count="(\d+)"/);
            const pdfIdMatch = html.match(/data-pdf-id="([^"]+)"/);

            const viewerContainer = document.getElementById('viewer');
            viewerContainer.innerHTML = html; // inject into viewer container
            reapplyStoredRotations(viewerContainer);

            // A Batch Mode Update may have rewritten this same pdf_id's bytes in place —
            // drop any cached pdf.js document for it so the freshly-injected canvases
            // re-fetch and re-render from disk instead of reusing stale pages.
            if (pdfIdMatch) {
                await invalidatePdfDoc(pdfIdMatch[1]);
            }
            observeAllPageCanvases(viewerContainer);

            initSortable(); // #viewer-inner was just replaced, so the old Sortable instance is stale
            reconcileExtractedState(); // ...and so is any extracted-page hiding; the fresh HTML has none applied

            // Manually re-trigger viewerReady
            if (pageCountMatch && pdfIdMatch) {
                document.body.dispatchEvent(new CustomEvent('viewerReady', {
                    detail: {
                        pdfId: pdfIdMatch[1],
                        pageCount: parseInt(pageCountMatch[1])
                    }
                }));
            }
        } catch (e) {
            console.error(e);
            showStatus('Grup ızgarası yüklenirken hata oluştu', 'text-red-400');
        }
    }

    function renameActiveBatch(newName) {
        if (!isBatchMode || currentBatchIndex < 0) return;
        const listItems = document.querySelectorAll('#output-list li:not(#output-empty) .download-btn');
        if (listItems.length === 0) return;
        const fileId = listItems[currentBatchIndex].dataset.fileId;
        submitRename(fileId, newName);
    }

    // Persists the active batch's current grid state (rotation/reorder) —
    // the only edit type that isn't already auto-saved via renameActiveBatch — back
    // to the server, rewriting that same file_id's PDF in place.
    // Reads the current grid's page order/rotation, excluding any cards already sent
    // to another batch (.extracted-page — see persistBatchExtractionCut) and,
    // optionally, a caller-supplied set of cards to leave out too.
    function gatherCurrentGridPages(excludeCardEls = []) {
        const excludeSet = new Set(excludeCardEls);
        return Array.from(document.querySelectorAll('.page-card'))
            .filter(card => !excludeSet.has(card) && !card.classList.contains('extracted-page'))
            .map(card => ({
                pdf_id: card.dataset.pdfId,
                page_idx: parseInt(card.dataset.pageIndex),
                rotation: pageRotations[card.id] || 0
            }));
    }

    // POSTs the given page list to /update/{fileId}, refreshes that output-list row,
    // and clears out now-stale per-page bookkeeping for fileId. Returns whether it
    // succeeded; the caller decides whether/when to reload the grid.
    async function persistPagesToBatch(fileId, pages) {
        const res = await postAction('/update/' + fileId, { pages });
        if (!res) return false;

        const link = document.querySelector(`.download-btn[data-file-id='${fileId}']`);
        const li = link ? link.closest('li') : null;
        if (li) li.innerHTML = res;

        // Scoped clear: only THIS file_id's card-keyed state is stale (indices were
        // just renumbered). Other batches may have their own unsaved pending edits —
        // do not touch those.
        const prefix = `page-card-${fileId}-`;
        Object.keys(pageRotations).forEach(k => { if (k.startsWith(prefix)) delete pageRotations[k]; });

        // extractedPageIndices[fileId] refers to pre-persist page numbering, and once
        // extraction is a real cut (see persistBatchExtractionCut) there is no more
        // "restore into the source" meaning for it anyway — drop it.
        delete extractedPageIndices[fileId];

        return true;
    }

    async function updateActiveBatch() {
        if (!isBatchMode || currentBatchIndex < 0) return;
        const listItems = document.querySelectorAll('#output-list li:not(#output-empty) .download-btn');
        if (listItems.length === 0) return;
        const fileId = listItems[currentBatchIndex].dataset.fileId;

        const pages = gatherCurrentGridPages();
        if (pages.length === 0) {
            // Nothing left to keep — a 0-page batch isn't a meaningful thing to save,
            // so treat "delete every page, then Update" as "remove this batch".
            removeOutputByFileId(fileId);
            showStatus('✓ Grup kaldırıldı — tüm sayfaları silinmişti.', 'text-green-400');
            return;
        }

        if (await persistPagesToBatch(fileId, pages)) {
            loadBatch(currentBatchIndex); // refetch fresh grid: new order/count, rotations reset, thumbnails regenerated server-side
        }
    }

    // Extracting pages while viewing a batch in Batch Mode is a cut, not a copy: the
    // extracted pages must actually leave the source batch's file on the server, or
    // the same pages could be re-extracted into unlimited further batches and — since
    // updateActiveBatch() didn't used to exclude them either — clicking Update later
    // would silently write them back into the source, undoing the extraction.
    async function persistBatchExtractionCut(extractedCardEls) {
        if (!isBatchMode || currentBatchIndex < 0) return;
        const listItems = document.querySelectorAll('#output-list li:not(#output-empty) .download-btn');
        if (listItems.length === 0) return;
        const sourceFileId = listItems[currentBatchIndex].dataset.fileId;

        const remainingPages = gatherCurrentGridPages(extractedCardEls);
        if (remainingPages.length === 0) {
            // Extracting every remaining page leaves nothing behind — a 0-page batch
            // isn't meaningful, so remove the now-fully-consumed source outright
            // instead of leaving a stale, endlessly re-extractable duplicate around.
            removeOutputByFileId(sourceFileId);
            showStatus('✓ Grup tamamen ayıklandı ve kaldırıldı.', 'text-green-400');
            return;
        }

        if (await persistPagesToBatch(sourceFileId, remainingPages)) {
            loadBatch(currentBatchIndex);
        }
    }
