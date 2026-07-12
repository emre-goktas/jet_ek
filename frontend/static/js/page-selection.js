/**
 * page-selection.js
 * Page selection (click/shift-click/select-all/undo), rotation, and the two
 * right-click context menus (page-card grid + sidebar batch list).
 */

    function selectAllPages() {
      document.querySelectorAll('.page-card').forEach(c => {
        if (!c.classList.contains('extracted-page')) selectedPages.add(c.id);
      });
      updateHighlight();
      updateSelectionInfo();
    }

    function clearSelection() {
      selectedPages.clear();
      selectionHistory = [];
      lastClickedCardId = null;
      updateHighlight();
      updateSelectionInfo();
    }

    function updateHighlight() {
      document.querySelectorAll('.page-card').forEach(card => {
        const shouldBeSelected = selectedPages.has(card.id);
        card.classList.toggle('selected', shouldBeSelected);

        try {
          if (typeof Sortable !== 'undefined' && Sortable.utils && Sortable.utils.select) {
            if (shouldBeSelected) Sortable.utils.select(card);
            else Sortable.utils.deselect(card);
          }
        } catch (e) { }

        const pageCheckbox = card.querySelector('.page-select-checkbox');
        if (pageCheckbox) pageCheckbox.checked = shouldBeSelected;
      });

      // Keep each document's "select all" checkbox in sync: checked only when
      // every one of its (non-extracted) pages is currently selected.
      document.querySelectorAll('.document-separator').forEach(sep => {
        const checkbox = sep.querySelector('.batch-select-checkbox');
        if (!checkbox) return;
        const cards = Array.from(document.querySelectorAll(`.page-card[data-pdf-id="${sep.dataset.pdfId}"]`))
          .filter(c => !c.classList.contains('extracted-page'));
        checkbox.checked = cards.length > 0 && cards.every(c => selectedPages.has(c.id));
      });
    }

    function toggleBatchSelection(checkbox, pdfId) {
      document.querySelectorAll(`.page-card[data-pdf-id="${pdfId}"]`).forEach(card => {
        if (card.classList.contains('extracted-page')) return;
        if (checkbox.checked) selectedPages.add(card.id);
        else selectedPages.delete(card.id);
      });
      updateHighlight();
      updateSelectionInfo();
    }

    // Single click (checkbox or anywhere on the card body) toggles just that page;
    // shift-click extends the selection as a range from the last-touched page. Ctrl
    // is deliberately not a separate gesture here — a plain click already only
    // affects the one page it's on, which testing showed was the part people found
    // confusing about the old modifier-key-driven scheme.
    function applyPageSelection(checkbox, event) {
      const card = checkbox.closest('.page-card');
      if (!card || card.classList.contains('extracted-page')) return;

      const cid = card.id;
      const shouldSelect = checkbox.checked;
      const added = [];
      const removed = [];
      const prevAnchor = lastClickedCardId;

      const applyOne = (id) => {
        if (shouldSelect && !selectedPages.has(id)) { selectedPages.add(id); added.push(id); }
        else if (!shouldSelect && selectedPages.has(id)) { selectedPages.delete(id); removed.push(id); }
      };

      if (event.shiftKey && lastClickedCardId) {
        const cards = Array.from(document.querySelectorAll('.page-card'));
        const idx1 = cards.findIndex(c => c.id === lastClickedCardId);
        const idx2 = cards.findIndex(c => c === card);
        if (idx1 !== -1 && idx2 !== -1) {
          const start = Math.min(idx1, idx2);
          const end = Math.max(idx1, idx2);
          for (let i = start; i <= end; i++) {
            if (!cards[i].classList.contains('extracted-page')) applyOne(cards[i].id);
          }
        } else {
          applyOne(cid);
        }
      } else {
        applyOne(cid);
      }

      if (added.length > 0 || removed.length > 0) {
        selectionHistory.push({ added, removed, prevAnchor });
      }
      lastClickedCardId = cid;

      updateHighlight();
      updateSelectionInfo();
    }

    // Clicking anywhere on a card outside the top-bar strip is the same as
    // clicking its checkbox — a bigger, more forgiving target for the common case.
    function handleCardBodyClick(event) {
      if (event.target.closest('.card-top-bar') || event.target.closest('.page-select-checkbox-wrap')) return;
      const card = event.currentTarget;
      if (card.classList.contains('extracted-page')) return;
      const checkbox = card.querySelector('.page-select-checkbox');
      if (!checkbox) return;
      checkbox.checked = !checkbox.checked;
      applyPageSelection(checkbox, event);
    }

    function updateSelectionInfo() {
      const info = document.getElementById('selection-info');
      if(info) info.textContent = selectedPages.size === 0 ? 'Sayfa seçin' : `${selectedPages.size} sayfa seçildi.`;
    }

    function rotateSinglePage(event, card, direction) {
      event.stopPropagation();
      const angle = direction === 'left' ? -90 : 90;
      let currentRotation = pageRotations[card.id] || 0;
      currentRotation = (currentRotation + angle) % 360;
      if (currentRotation < 0) currentRotation += 360;
      pageRotations[card.id] = currentRotation;
      const img = card.querySelector('.page-img');
      if (img) img.style.transform = `rotate(${currentRotation}deg)`;
    }

    // ─── Right-click card context menu (rotate + quick extract) ──────────
    let contextMenuCard = null;

    function openCardContextMenu(event, card) {
      event.preventDefault();
      if (card.classList.contains('extracted-page')) return;
      contextMenuCard = card;

      const menu = document.getElementById('page-context-menu');
      menu.classList.remove('hidden');
      menu.style.left = event.clientX + 'px';
      menu.style.top = event.clientY + 'px';

      // Clamp on-screen once the menu has real dimensions (it's hidden -> visible,
      // so getBoundingClientRect is only meaningful after this paint).
      requestAnimationFrame(() => {
        const rect = menu.getBoundingClientRect();
        if (rect.right > window.innerWidth) menu.style.left = Math.max(8, window.innerWidth - rect.width - 8) + 'px';
        if (rect.bottom > window.innerHeight) menu.style.top = Math.max(8, window.innerHeight - rect.height - 8) + 'px';
      });
    }

    function closeCardContextMenu() {
      document.getElementById('page-context-menu')?.classList.add('hidden');
      contextMenuCard = null;
    }

    function contextMenuAction(action) {
      const card = contextMenuCard;
      closeCardContextMenu();
      if (!card) return;

      if (action === 'rotate-left' || action === 'rotate-right') {
        rotateSinglePage({ stopPropagation() {} }, card, action === 'rotate-left' ? 'left' : 'right');
      } else if (action === 'extract') {
        // Right-clicking a page that isn't part of the current selection should
        // still act on it — extract "this page (plus whatever else is already
        // selected)" rather than silently no-op on an empty selection.
        if (!selectedPages.has(card.id)) {
          selectedPages.add(card.id);
          updateHighlight();
          updateSelectionInfo();
        }
        doExtract();
      } else if (action === 'clear-selection') {
        clearSelection();
      } else if (action === 'delete') {
        // Right-clicking a page that's part of the current multi-selection deletes
        // the whole selection, same convention as 'extract' above; otherwise just
        // the one page under the cursor.
        const targets = selectedPages.has(card.id)
          ? Array.from(document.querySelectorAll('.page-card'))
              .filter(c => selectedPages.has(c.id) && !c.classList.contains('extracted-page'))
          : [card];
        markPagesDeleted(targets);
        showStatus(
          isBatchMode
            ? `✓ ${targets.length} sayfa silindi — kalıcı olması için "Güncelle"ye basın.`
            : `✓ ${targets.length} sayfa görünümden kaldırıldı.`,
          'text-green-400'
        );
      }
    }

    document.addEventListener('click', (e) => {
      const menu = document.getElementById('page-context-menu');
      if (menu && !menu.classList.contains('hidden') && !menu.contains(e.target)) {
        closeCardContextMenu();
      }
    });
    // A second right-click elsewhere should just reposition/reopen for the new
    // target rather than leaving a stale menu behind.
    document.addEventListener('contextmenu', (e) => {
      if (!e.target.closest('.page-card')) closeCardContextMenu();
    });

    // ─── Sidebar batch selection + right-click menu ──────────────────────
    let selectedBatchIds = new Set();
    let batchContextMenuLi = null;

    function toggleOutputSelection(checkbox, fileId) {
      if (checkbox.checked) selectedBatchIds.add(fileId);
      else selectedBatchIds.delete(fileId);
      checkbox.closest('.pdf-item')?.classList.toggle('selected', checkbox.checked);
    }

    function clearBatchSelection() {
      selectedBatchIds.clear();
      document.querySelectorAll('#output-list .pdf-item.selected').forEach(el => el.classList.remove('selected'));
      document.querySelectorAll('#output-list .output-select-checkbox').forEach(cb => { cb.checked = false; });
    }

    function openBatchContextMenu(event, itemEl) {
      event.preventDefault();
      batchContextMenuLi = itemEl.closest('li');

      const menu = document.getElementById('batch-context-menu');
      menu.classList.remove('hidden');
      menu.style.left = event.clientX + 'px';
      menu.style.top = event.clientY + 'px';

      requestAnimationFrame(() => {
        const rect = menu.getBoundingClientRect();
        if (rect.right > window.innerWidth) menu.style.left = Math.max(8, window.innerWidth - rect.width - 8) + 'px';
        if (rect.bottom > window.innerHeight) menu.style.top = Math.max(8, window.innerHeight - rect.height - 8) + 'px';
      });
    }

    function closeBatchContextMenu() {
      document.getElementById('batch-context-menu')?.classList.add('hidden');
      batchContextMenuLi = null;
    }

    // Right-clicking an item that's part of the current multi-selection acts on
    // the whole selection (same convention as the page-card context menu above);
    // otherwise it acts on just the one item under the cursor.
    function getBatchActionTargets(li) {
      const fileId = getListItemFileId(li);
      if (fileId && selectedBatchIds.has(fileId)) return Array.from(selectedBatchIds);
      return fileId ? [fileId] : [];
    }

    function batchContextMenuAction(action) {
      const li = batchContextMenuLi;
      closeBatchContextMenu();
      if (!li) return;
      const targetIds = getBatchActionTargets(li);
      if (targetIds.length === 0) return;

      if (action === 'ai-rename') {
        runJetRenameAll(targetIds);
      } else if (action === 'download') {
        openDownloadConfirmModal(targetIds);
      } else if (action === 'clear-selection') {
        clearBatchSelection();
      } else if (action === 'remove') {
        targetIds.forEach(id => removeOutputByFileId(id));
      }
    }

    document.addEventListener('click', (e) => {
      const menu = document.getElementById('batch-context-menu');
      if (menu && !menu.classList.contains('hidden') && !menu.contains(e.target)) {
        closeBatchContextMenu();
      }
    });
    document.addEventListener('contextmenu', (e) => {
      if (!e.target.closest('.pdf-item')) closeBatchContextMenu();
    });

    function undoLastSelection() {
        if (selectionHistory.length === 0) return;
        const lastAction = selectionHistory.pop();
        
        lastAction.added.forEach(id => selectedPages.delete(id));
        lastAction.removed.forEach(id => selectedPages.add(id));
        lastClickedCardId = lastAction.prevAnchor;
        
        updateHighlight();
        updateSelectionInfo();
    }

