/**
 * modals.js
 * Shared openModal/closeModal helpers, the naming-modal's close handler, and
 * the Gemini API key (BYOK) modal + its localStorage-backed getters/setters.
 */

    // ─── Modal open/close helpers ─────────────────────────────────────────
    // Every modal in this page is a `.modal-overlay` toggled via `.active`, with
    // `body.modal-open` locking background scroll for as long as any one of them
    // is open. Centralizing that pair here is what let closeApiKeyGuideModal's
    // "don't unlock scroll if another modal is still open underneath" rule become
    // just "check for any other active modal" instead of hardcoding one specific
    // modal id to watch for.
    function openModal(id) {
      const m = document.getElementById(id);
      if (m) m.classList.add('active');
      document.body.classList.add('modal-open');
    }

    function closeModal(id) {
      const m = document.getElementById(id);
      if (m) m.classList.remove('active');
      if (!document.querySelector('.modal-overlay.active')) {
        document.body.classList.remove('modal-open');
      }
    }

    function closeNamingModal() {
      flushRenameAutoSave(); // fire-and-forget — don't make closing wait on the network
      closeModal('naming-modal');
    }

    // ─── Settings/profile modal ───────────────────────────────────────────
    // Loads /onboarding in an iframe (its own document, so it can't touch this
    // page's in-memory batch/upload state — see viewer-state.js) instead of
    // navigating there in a new tab. ?embed=1 tells onboarding.html to post a
    // message back here on save/cancel instead of doing a top-level redirect,
    // which would otherwise just reload the main app *inside* the iframe.
    function openSettingsModal() {
      const frame = document.getElementById('settings-modal-frame');
      if (frame) frame.src = '/onboarding?embed=1';
      openModal('settings-modal');
    }

    function closeSettingsModal() {
      closeModal('settings-modal');
      const frame = document.getElementById('settings-modal-frame');
      if (frame) frame.src = 'about:blank'; // drop the form once closed, next open starts fresh
    }

    window.addEventListener('message', (e) => {
      if (e.origin !== window.location.origin) return;
      if (e.data && (e.data.type === 'jetek:profile-saved' || e.data.type === 'jetek:settings-cancel')) {
        closeSettingsModal();
      }
    });

    // POST /auth/google (auth.py) redirects here with ?login=1 right after a
    // successful login — pop the settings modal open once so an existing
    // user sees their profile immediately, without requiring the gear-icon
    // click. Stripped from the URL right away so a later F5/reload on the
    // same session doesn't reopen it every time.
    document.addEventListener('DOMContentLoaded', () => {
      if (new URLSearchParams(window.location.search).get('login') === '1') {
        openSettingsModal();
        history.replaceState(null, '', window.location.pathname);
      }
    });

    // ─── Gemini API key (BYOK) ───────────────────────────────────────────
    // Kept only in the browser (localStorage) and sent per-request via the
    // X-Gemini-Api-Key header — the backend never writes it to disk/DB.
    const GEMINI_KEY_STORAGE = 'jetek_gemini_api_key';

    function getGeminiApiKey() {
      return (localStorage.getItem(GEMINI_KEY_STORAGE) || '').trim();
    }

    // Surfaces the tail of the currently-stored key so a save can be visually
    // confirmed without exposing the full value (input stays type="password").
    function updateApiKeyHint() {
      const hint = document.getElementById('api-key-hint');
      if (!hint) return;
      const key = getGeminiApiKey();
      hint.textContent = key
        ? `Bu tarayıcıda kayıtlı anahtar: ...${key.slice(-6)}`
        : 'Bu tarayıcıda kayıtlı bir anahtar yok.';
    }

    function openApiKeyModal() {
      const input = document.getElementById('api-key-input');
      if (input) input.value = getGeminiApiKey();
      updateApiKeyHint();
      openModal('api-key-modal');
    }

    function closeApiKeyModal() {
      closeModal('api-key-modal');
    }

    function saveApiKey() {
      const input = document.getElementById('api-key-input');
      const value = input ? input.value.trim() : '';
      if (value) {
        localStorage.setItem(GEMINI_KEY_STORAGE, value);
      } else {
        localStorage.removeItem(GEMINI_KEY_STORAGE);
      }
      updateApiKeyHint();
      closeApiKeyModal();
    }

    function clearApiKey() {
      localStorage.removeItem(GEMINI_KEY_STORAGE);
      const input = document.getElementById('api-key-input');
      if (input) input.value = '';
      updateApiKeyHint();
      closeApiKeyModal();
    }

    function openApiKeyGuideModal() {
      openModal('api-key-guide-modal');
    }

    function closeApiKeyGuideModal() {
      // The API key modal underneath is still open — closeModal only drops
      // modal-open once no .modal-overlay is left active, so scroll-locking
      // isn't undone too early.
      closeModal('api-key-guide-modal');
    }

