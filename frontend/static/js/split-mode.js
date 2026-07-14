/**
 * split-mode.js
 * "Kurallı Böl" (right-click, fixed N-page chunks) and "Hızlı Ayıkla"
 * (toolbar toggle, click anchors to mark group starts) — both compute an
 * ordered list of page-groups client-side, never letting a group cross a
 * source document's boundary, then POST them all in one call to
 * /extract/batch-split so splitting hundreds of pages doesn't mean hundreds
 * of round trips.
 */

    const MAX_SPLIT_GROUPS = 300;

    // DOM-ordered, non-extracted page cards — the canonical order both split
    // modes group over (not click order, which selectedPages/Set insertion
    // order would otherwise reflect).
    function orderedVisiblePageCards() {
      return Array.from(document.querySelectorAll('.page-card'))
        .filter(c => !c.classList.contains('extracted-page'));
    }

    // ─── Kurallı Böl (fixed-size chunks) ──────────────────────────────────

    function computeRuleSplitGroups(groupSize) {
      const cards = orderedVisiblePageCards().filter(c => selectedPages.has(c.id));
      const groups = [];
      let current = [];
      let currentPdfId = null;

      cards.forEach(card => {
        const pid = card.dataset.pdfId;
        if (pid !== currentPdfId || current.length >= groupSize) {
          if (current.length > 0) groups.push(current);
          current = [];
          currentPdfId = pid;
        }
        current.push(card);
      });
      if (current.length > 0) groups.push(current);
      return groups;
    }

    function openRuleSplitPopup() {
      const menu = document.getElementById('page-context-menu');
      const popup = document.getElementById('rule-split-popup');
      if (!popup) return;

      popup.style.left = menu.style.left;
      popup.style.top = menu.style.top;
      popup.classList.remove('hidden');

      const input = document.getElementById('rule-split-input');
      const error = document.getElementById('rule-split-error');
      if (input) input.value = '';
      if (error) error.textContent = '';

      requestAnimationFrame(() => {
        const rect = popup.getBoundingClientRect();
        if (rect.right > window.innerWidth) popup.style.left = Math.max(8, window.innerWidth - rect.width - 8) + 'px';
        if (rect.bottom > window.innerHeight) popup.style.top = Math.max(8, window.innerHeight - rect.height - 8) + 'px';
        if (input) input.focus();
      });
    }

    function closeRuleSplitPopup() {
      document.getElementById('rule-split-popup')?.classList.add('hidden');
    }

    document.addEventListener('click', (e) => {
      const popup = document.getElementById('rule-split-popup');
      if (popup && !popup.classList.contains('hidden') && !popup.contains(e.target)) closeRuleSplitPopup();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeRuleSplitPopup();
    });

    function submitRuleSplit() {
      const input = document.getElementById('rule-split-input');
      const errorEl = document.getElementById('rule-split-error');
      const n = parseInt(input?.value, 10);

      if (!Number.isInteger(n) || n < 1) {
        if (errorEl) errorEl.textContent = 'Lütfen geçerli bir sayı giriniz (1 veya üzeri).';
        return;
      }
      if (selectedPages.size === 0) {
        if (errorEl) errorEl.textContent = 'Seçili sayfa kalmadı.';
        return;
      }

      const groups = computeRuleSplitGroups(n);
      if (groups.length > MAX_SPLIT_GROUPS) {
        if (errorEl) errorEl.textContent = `Bu ayar ${groups.length} parça oluşturur (en fazla ${MAX_SPLIT_GROUPS}). Grup boyutunu artırın.`;
        return;
      }

      closeRuleSplitPopup();
      submitSplitGroups(groups, 'rule_split');
    }

    // ─── Hızlı Ayıkla (anchor-based, irregular ranges) ────────────────────

    function toggleSplitAnchor(card) {
      if (splitAnchors.has(card.id)) {
        splitAnchors.delete(card.id);
        card.classList.remove('split-anchor');
      } else {
        splitAnchors.add(card.id);
        card.classList.add('split-anchor');
        // A card is a group-start or a closer, never both — see setDocCloser().
        if (splitClosers.has(card.id)) { splitClosers.delete(card.id); card.classList.remove('split-closer'); }
      }
      updateQuickSplitInfo();
    }

    // "Son Sayfa" (right-click menu, quick-split mode only): explicitly marks
    // where a document's last group ends, without starting a new group there —
    // unlike a plain anchor click, this lets the final group span multiple
    // pages (e.g. anchor at 45, closer at 50 → one 45-50 group, not a lone 50).
    // Only one closer per document makes sense, so marking a new one replaces
    // any earlier one for that same pdf_id.
    //
    // A closer only makes sense once a group is already open — otherwise
    // computeQuickSplitGroups() just silently drops it (no anchor means no
    // open `current` to push it into), which looked to the user like the cut
    // came out "reversed". Rather than leave that footgun to the user's own
    // ordering discipline, require a start-anchor to already exist earlier in
    // this same document (strictly before this card, so converting a doc's
    // *only* anchor into a closer via this same click doesn't count).
    function setDocCloser(card) {
      const pid = card.dataset.pdfId;
      const docCards = orderedVisiblePageCards().filter(c => c.dataset.pdfId === pid);
      const cardIdx = docCards.indexOf(card);
      const hasPrecedingAnchor = docCards.slice(0, cardIdx).some(c => splitAnchors.has(c.id));
      if (!hasPrecedingAnchor) {
        showStatus('İlk sayfa seçimleri tamamlanmadan son sayfa seçilemez.', 'text-yellow-400');
        return;
      }
      Array.from(splitClosers).forEach(id => {
        const existing = document.getElementById(id);
        if (existing && existing.dataset.pdfId === pid) {
          splitClosers.delete(id);
          existing.classList.remove('split-closer');
        }
      });
      if (splitAnchors.has(card.id)) { splitAnchors.delete(card.id); card.classList.remove('split-anchor'); }
      splitClosers.add(card.id);
      card.classList.add('split-closer');
      updateQuickSplitInfo();
    }

    function toggleDocCloser(card) {
      if (splitClosers.has(card.id)) {
        splitClosers.delete(card.id);
        card.classList.remove('split-closer');
        updateQuickSplitInfo();
      } else {
        setDocCloser(card);
      }
    }

    function updateQuickSplitInfo() {
      const info = document.getElementById('selection-info');
      if (!info) return;
      if (splitAnchors.size === 0 && splitClosers.size === 0) {
        info.textContent = 'Eklerin sadece ilk sayfasını seçiniz.';
        return;
      }
      const parts = [`${splitAnchors.size} grup başlangıcı`];
      if (splitClosers.size > 0) parts.push(`${splitClosers.size} son sayfa`);
      info.textContent = `Hızlı Ayıkla: ${parts.join(', ')} işaretlendi.`;
    }

    // Every loaded document's actual last (visible, non-extracted) page gets a
    // persistent "Belge Sonu" badge while quick-split mode is active — so the
    // user can see where each document truly ends instead of guessing, before
    // deciding whether to mark it (a plain anchor click for a 1-page final
    // group) or place a "Son Sayfa" closer earlier for a multi-page one.
    function markDocLastPageHints(show) {
      document.querySelectorAll('.page-card.doc-last-page-hint').forEach(c => c.classList.remove('doc-last-page-hint'));
      if (!show) return;
      const lastPerDoc = new Map();
      orderedVisiblePageCards().forEach(card => lastPerDoc.set(card.dataset.pdfId, card));
      lastPerDoc.forEach(card => card.classList.add('doc-last-page-hint'));
    }

    // Clears anchor/closer marks+classes without touching #selection-info —
    // callers decide what the info line should say afterward (exitQuickSplitMode
    // wants the normal "Sayfa seçin" text; clearSplitAnchors wants the prompt).
    function clearAnchorMarks() {
      splitAnchors.forEach(id => document.getElementById(id)?.classList.remove('split-anchor'));
      splitAnchors.clear();
      splitClosers.forEach(id => document.getElementById(id)?.classList.remove('split-closer'));
      splitClosers.clear();
    }

    // Bound to "Seçimi Temizle" while quick-split mode is active (see
    // clearSelection() in page-selection.js) — clears anchors instead of the
    // (frozen, always-empty) normal selection.
    function clearSplitAnchors() {
      clearAnchorMarks();
      updateQuickSplitInfo();
    }

    // "Tümünü Seç"/"Kurallı Böl"/context-menu "Ayıkla" all act on selectedPages,
    // which stays frozen empty in this mode — hiding them avoids offering
    // buttons that look clickable but silently do nothing.
    function setQuickSplitOnlyUiVisible(hideNormalControls) {
      document.getElementById('select-all-btn')?.classList.toggle('hidden', hideNormalControls);
      document.getElementById('ctx-menu-extract-btn')?.classList.toggle('hidden', hideNormalControls);
      document.getElementById('ctx-menu-rule-split-btn')?.classList.toggle('hidden', hideNormalControls);
      // Inverse: "Son Sayfa" only makes sense while marking anchors.
      document.getElementById('ctx-menu-last-page-btn')?.classList.toggle('hidden', !hideNormalControls);
    }

    // The main toolbar button is reused as this mode's "run" trigger (see
    // doExtract() in rename-modal.js) — relabeling it avoids "Hızlı Ayıkla" and
    // "Ayıkla" reading as two unrelated actions side by side.
    function setExtractButtonLabel(quickSplitActive) {
      const btn = document.getElementById('btn-extract');
      if (btn) btn.innerHTML = quickSplitActive ? '✓ Tamamla' : '✂ Ayıkla';
    }

    function toggleQuickSplitMode() {
      if (quickSplitModeActive) exitQuickSplitMode();
      else enterQuickSplitMode();
    }

    function enterQuickSplitMode() {
      clearSelection(); // still normal mode here — clears the real selection, not anchors
      quickSplitModeActive = true;
      document.getElementById('quick-split-toggle-btn')?.classList.add('active');
      setExtractButtonLabel(true);
      setQuickSplitOnlyUiVisible(true);
      markDocLastPageHints(true);
      updateQuickSplitInfo();
    }

    function exitQuickSplitMode() {
      quickSplitModeActive = false;
      clearAnchorMarks();
      document.getElementById('quick-split-toggle-btn')?.classList.remove('active');
      setExtractButtonLabel(false);
      setQuickSplitOnlyUiVisible(false);
      markDocLastPageHints(false);
      updateSelectionInfo();
    }

    // Anchors sort by DOM order; a document boundary always closes the current
    // group (even without an anchor there), and any pages before a document's
    // first anchor are left out entirely — only explicitly anchored ranges get
    // extracted. A "Son Sayfa" closer (splitClosers) ends the current group
    // right after that page without starting a new one — everything past it in
    // that document is left untouched, same as pages before the first anchor.
    function computeQuickSplitGroups() {
      const cards = orderedVisiblePageCards();
      const groups = [];
      let current = null;
      let currentPdfId = null;

      cards.forEach(card => {
        const pid = card.dataset.pdfId;
        if (pid !== currentPdfId) {
          if (current) groups.push(current);
          current = null;
          currentPdfId = pid;
        }
        if (splitAnchors.has(card.id)) {
          if (current) groups.push(current);
          current = [];
        }
        if (current) {
          current.push(card);
          if (splitClosers.has(card.id)) {
            groups.push(current);
            current = null;
          }
        }
      });
      if (current) groups.push(current);
      return groups;
    }

    // Requires every document that has at least one anchor to also have an
    // explicit closing decision — either its own actual last page is itself an
    // anchor (a 1-page final group), or a "Son Sayfa" closer is placed
    // somewhere in it (a multi-page final group ending there). Otherwise the
    // final group would silently run to "wherever the document happens to
    // end" instead of a page the user consciously chose. Returns the list of
    // documents' last cards that are missing this (empty = validation passed).
    function findDocsMissingClosingAnchor() {
      const byDoc = new Map();
      orderedVisiblePageCards().forEach(card => {
        const pid = card.dataset.pdfId;
        if (!byDoc.has(pid)) byDoc.set(pid, []);
        byDoc.get(pid).push(card);
      });

      const missing = [];
      byDoc.forEach(docCards => {
        const hasAnyAnchor = docCards.some(c => splitAnchors.has(c.id));
        if (!hasAnyAnchor) return;
        const hasCloser = docCards.some(c => splitClosers.has(c.id));
        const lastCard = docCards[docCards.length - 1];
        if (!hasCloser && !splitAnchors.has(lastCard.id)) missing.push(lastCard);
      });
      return missing;
    }

    function runQuickSplit() {
      if (splitAnchors.size === 0) {
        showStatus('İşaretli sayfa yok — önce en az bir ekin ilk sayfasına tıklayın.', 'text-yellow-400');
        return;
      }

      const missingClosers = findDocsMissingClosingAnchor();
      if (missingClosers.length > 0) {
        missingClosers.forEach(card => card.classList.add('split-anchor-missing'));
        showStatus(
          missingClosers.length === 1
            ? 'Bu belgenin son sayfasını işaretleyin (normal tıklama) veya sağ tık → "Son Sayfa" seçin (turuncu kenarlıklı kart).'
            : `${missingClosers.length} belgenin son sayfasını işaretlemelisiniz (turuncu kenarlıklı kartlar).`,
          'text-yellow-400'
        );
        setTimeout(() => missingClosers.forEach(card => card.classList.remove('split-anchor-missing')), 2000);
        return;
      }

      const groups = computeQuickSplitGroups();
      if (groups.length > MAX_SPLIT_GROUPS) {
        showStatus(`Bu işaretleme ${groups.length} parça oluşturur (en fazla ${MAX_SPLIT_GROUPS}). Daha az işaretleyin.`, 'text-yellow-400');
        return;
      }
      submitSplitGroups(groups, 'quick_split');
      exitQuickSplitMode();
    }

    // ─── Shared submit path ────────────────────────────────────────────────

    async function submitSplitGroups(groups, eventName) {
      if (groups.length === 0) return;

      const tempEntries = groups.map(cards => {
        const tempId = 'split-' + Math.random().toString(36).substring(2, 9);
        const firstPage = parseInt(cards[0].dataset.pageIndex) + 1;
        const lastPage = parseInt(cards[cards.length - 1].dataset.pageIndex) + 1;
        const label = firstPage === lastPage ? `${firstPage}` : `${firstPage}-${lastPage}`;
        appendLoadingToOutputList(tempId, `evrak_${label}.pdf`);
        return { tempId, cards };
      });

      const payload = {
        groups: groups.map(cards => ({
          pages: cards.map(card => ({
            pdf_id: card.dataset.pdfId,
            page_idx: parseInt(card.dataset.pageIndex),
            rotation: pageRotations[card.id] || 0,
          })),
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
        tempEntries.forEach(({ tempId }) => document.getElementById(`loading-task-${tempId}`)?.remove());
        showStatus('✗ Bağlantı hatası.', 'text-red-400');
        return;
      }

      if (!res.ok) {
        tempEntries.forEach(({ tempId }) => document.getElementById(`loading-task-${tempId}`)?.remove());
        showStatus(
          res.status === 404
            ? '⏱ Oturumunuz zaman aşımına uğradı — belge temizlendi. Lütfen tekrar yükleyin.'
            : '✗ Bölme başarısız oldu.',
          res.status === 404 ? 'text-yellow-400' : 'text-red-400'
        );
        return;
      }

      const resultMap = await res.json();
      const allExtractedCards = [];
      let successCount = 0;

      tempEntries.forEach(({ tempId, cards }, i) => {
        const html = resultMap[`group-${i}`];
        if (html) {
          markPagesExtracted(cards, tempId);
          replaceLoadingWithOutput(tempId, html);
          allExtractedCards.push(...cards);
          successCount++;
        } else {
          document.getElementById(`loading-task-${tempId}`)?.remove();
        }
      });

      if (typeof logEvent === 'function') logEvent(eventName, { group_count: groups.length, success_count: successCount });
      if (allExtractedCards.length > 0) await persistBatchExtractionCut(allExtractedCards);

      if (successCount === groups.length) {
        showStatus(`✓ ${successCount} parça oluşturuldu.`, 'text-green-400');
      } else {
        showStatus(`⚠ ${successCount}/${groups.length} parça oluşturuldu.`, 'text-yellow-400');
      }
    }
