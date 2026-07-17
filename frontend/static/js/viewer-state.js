/**
 * viewer-state.js
 * Global mutable state shared by every other frontend/static/js/*.js module and
 * index.html's remaining inline script — selection, rotations, batch-mode status,
 * and per-output bookkeeping. Loaded first (see index.html's <script> order) so
 * every other deferred module can read/write these the moment it needs to; classic
 * (non-module) scripts share one global scope, so this is just plain top-level
 * `let` state, not an explicit export.
 */

    let batchPreviewItems = [];
    let currentBatchPreviewIndex = 0;
    
    let selectedPages = new Set();
    let selectionHistory = []; // Track selection actions for undo
    let lastClickedCardId = null;

    // Pages consumed by an extraction are hidden from their source grid. Keyed by the
    // source id (an original upload's pdf_id, or an already-extracted batch's file_id,
    // since Batch Mode lets you extract from an extraction) -> Set of page indices.
    // This is separate from the DOM so it survives fetchAndRenderBatch() re-rendering
    // the grid from scratch when switching batches.
    let extractedPageIndices = {};
    // What each output (keyed by its temp UI id, then renamed to its real file_id once
    // the server responds) consumed, so deleting that output can restore those pages.
    let outputSourcePages = {};
    let pageRotations = {};
    let sortableInstance = null;
    let currentCustomName = '';

    // Batch Mode variables
    let isBatchMode = false;
    let originalPdfId = null;
    let currentBatchIndex = -1;

    // Hızlı Ayıkla (quick/anchor split) — see split-mode.js. While active, clicking
    // a page card marks/unmarks it as a group-start anchor instead of selecting it.
    let quickSplitModeActive = false;
    let splitAnchors = new Set();
    // "Son Sayfa" closers (right-click menu) — ends a group without starting a
    // new one, so a document's final group can span multiple pages.
    let splitClosers = new Set();

    // Output rows that only exist client-side so far — no backend file, no
    // file_id. Created by confirmExtract/submitSplitGroups instead of an
    // eager /extract call; only cut server-side once something actually needs
    // real bytes (materializeRow, see output-panel.js) or the final "İndir"
    // sends every still-pending row to /extract/finalize in one pass. Keyed
    // by pendingId, same convention as outputSourcePages/extractedPageIndices
    // (keyed by "whatever this output's current id is").
    let pendingOutputs = {};
    const PENDING_ID_PREFIX = 'pend-';

    function makePendingId() {
      return PENDING_ID_PREFIX + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
    }
    // A real file_id is always a 32-char hex uuid — this prefix can never
    // collide with one, so any output-list id can be told apart with just
    // the string itself, no separate "is this row pending" lookup needed.
    function isPendingFileId(id) {
      return typeof id === 'string' && id.startsWith(PENDING_ID_PREFIX);
    }

