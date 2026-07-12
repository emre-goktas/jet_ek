/**
 * preview-zoom.js
 * Pan/zoom state and controls for the full-size page preview modal, plus the
 * keyboard-shortcut and drag-to-pan wiring registered on DOMContentLoaded.
 */

    let currentPreviewZoom = 1;
    let currentTranslateX = 0;
    let currentTranslateY = 0;
    let isDraggingPreview = false;
    let dragStartX = 0;
    let dragStartY = 0;

    function zoomPreview(delta) {
        currentPreviewZoom += delta;
        if (currentPreviewZoom < 0.2) currentPreviewZoom = 0.2;
        if (currentPreviewZoom > 5) currentPreviewZoom = 5;
        applyPreviewZoom();
    }
    function resetZoom(fullView = false) {
        currentTranslateX = 0;
        currentTranslateY = 0;
        
        if (fullView) {
            const container = document.getElementById('preview-scroll-container');
            const img = document.getElementById('naming-preview-img');
            if (container && img && img.clientHeight > 0) {
                currentPreviewZoom = container.clientHeight / img.clientHeight;
                if (currentPreviewZoom < 0.2) currentPreviewZoom = 0.2;
            } else {
                currentPreviewZoom = 0.4;
            }
        } else {
            currentPreviewZoom = 1.4;
        }
        applyPreviewZoom();
    }
    function applyPreviewZoom() {
        const img = document.getElementById('naming-preview-img');
        if (img) {
            let rotationStr = "";
            if (img.dataset.rotation) {
                rotationStr = `rotate(${img.dataset.rotation}deg)`;
            }
            // Applying translate first (leftmost) means translation is in unscaled screen coordinates
            img.style.transform = `translate(${currentTranslateX}px, ${currentTranslateY}px) scale(${currentPreviewZoom}) ${rotationStr}`;
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        const container = document.getElementById('preview-scroll-container');
        if (container) {
            container.addEventListener('wheel', (e) => {
                e.preventDefault();
                if (e.deltaY < 0) {
                    zoomPreview(0.1);
                } else {
                    zoomPreview(-0.1);
                }
            });

            container.addEventListener('mousedown', (e) => {
                if (e.button !== 0) return; // Only left click
                e.preventDefault(); // Prevent browser from shifting focus
                
                // Explicitly keep/set focus on the filename input
                const filenameInput = document.getElementById('custom-filename');
                if (filenameInput) filenameInput.focus();

                isDraggingPreview = true;
                dragStartX = e.clientX;
                dragStartY = e.clientY;
                container.classList.add('cursor-grabbing');
                container.classList.remove('cursor-move');
            });
            
            window.addEventListener('mouseup', () => {
                isDraggingPreview = false;
                if (container) {
                    container.classList.remove('cursor-grabbing');
                    container.classList.add('cursor-move');
                }
            });
            
            window.addEventListener('mousemove', (e) => {
                if (!isDraggingPreview) return;
                e.preventDefault();
                const dx = e.clientX - dragStartX;
                const dy = e.clientY - dragStartY;
                dragStartX = e.clientX;
                dragStartY = e.clientY;
                
                currentTranslateX += dx;
                currentTranslateY += dy;
                applyPreviewZoom();
            });
        }
    });
    document.addEventListener('DOMContentLoaded', () => {
        const input = document.getElementById('custom-filename');
        if (input) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    // Mirrors the "Sonraki Ek" button — saves the current name and
                    // advances, consistent with what the primary (blue) button does.
                    if (renamingFileId) {
                        previewNextBatch();
                    } else {
                        proceedToExtract(); // legacy new-extraction naming path
                    }
                }
            });
        }

        const viewerArea = document.getElementById('viewer');
        if (viewerArea) {
            viewerArea.addEventListener('mousedown', (e) => {
                // Check if click is on the scrollbar
                const isScrollbar = e.offsetX > e.target.clientWidth || e.offsetY > e.target.clientHeight;
                if (!isScrollbar) {
                    const inp = document.getElementById('batch-name-input');
                    // Avoid preventing default on inputs to allow normal text selection.
                    // Also skip page-card clicks entirely: forcing focus back onto the batch
                    // name field on every click there permanently pins document.activeElement
                    // to an <input>, which silently disables the Ctrl+Z/Ctrl+X page shortcuts.
                    if (inp && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA' && !e.target.closest('.page-card')) {
                        e.preventDefault();
                        inp.focus();
                    }
                }
            });
        }

        document.addEventListener('keydown', (e) => {
            const isCtrl = e.ctrlKey || e.metaKey;
            const activeEl = document.activeElement;
            // Checkboxes are <input> too, but they're not text-editing fields — a
            // focused page-select checkbox shouldn't suppress Ctrl+Z/Ctrl+X/Escape.
            const isInput = activeEl && (
              (activeEl.tagName === 'INPUT' && activeEl.type !== 'checkbox' && activeEl.type !== 'radio') ||
              activeEl.tagName === 'TEXTAREA' ||
              activeEl.isContentEditable
            );

            if (isCtrl && (e.key === 'z' || e.key === 'Z')) {
                if (isInput) return; // Let default browser undo work inside inputs
                e.preventDefault();
                undoLastSelection();
            }
            
            if (isCtrl && (e.key === 'x' || e.key === 'X')) {
                if (isInput) return; // Let default browser cut work inside inputs
                e.preventDefault();
                doExtract();
            }

            if (e.key === 'Escape') {
                if (isInput) return;
                e.preventDefault();
                const menu = document.getElementById('page-context-menu');
                if (menu && !menu.classList.contains('hidden')) {
                    closeCardContextMenu();
                    return;
                }
                clearSelection();
            }

            if (e.altKey && e.key === 'ArrowLeft') {
                const isModalOpen = document.getElementById('naming-modal')?.classList.contains('active');
                if (isModalOpen) {
                    e.preventDefault();
                    previewPrevPage();
                } else if (isBatchMode) {
                    e.preventDefault();
                    if (isInput) activeEl.blur(); // Trigger onchange if renaming
                    prevBatch();
                }
            }
            if (e.altKey && e.key === 'ArrowRight') {
                const isModalOpen = document.getElementById('naming-modal')?.classList.contains('active');
                if (isModalOpen) {
                    e.preventDefault();
                    previewNextPage();
                } else if (isBatchMode) {
                    e.preventDefault();
                    if (isInput) activeEl.blur(); // Trigger onchange if renaming
                    nextBatch();
                }
            }

            if (e.altKey && e.key === 'ArrowUp') {
                const isModalOpen = document.getElementById('naming-modal')?.classList.contains('active');
                if (isModalOpen) {
                    e.preventDefault();
                    previewPrevBatch();
                }
            }
            if (e.altKey && e.key === 'ArrowDown') {
                const isModalOpen = document.getElementById('naming-modal')?.classList.contains('active');
                if (isModalOpen) {
                    e.preventDefault();
                    previewNextBatch();
                }
            }
        });
    });

