<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import { push } from 'svelte-spa-router';

  let {
    apiBase,            // e.g. '/api/invoices/123' or '/api/estimates/123'
    detailRoute,        // e.g. '/invoices/123' or '/estimates/123'
    discardRoute = '/', // where to go after discarding (default: home)
    onDone,             // optional async () => void — flush pending line-item
                        // edits; may reject to keep the user here (a save failed)
  } = $props();

  let doneBusy = $state(false);

  // No confirm: the draft is easily remade from its source on the page the
  // user returns to, so discarding is effectively reversible.
  async function discard() {
    try {
      await api.delete(`${apiBase}/?confirm=true`);
      push(discardRoute);
    } catch (e) {
      showError(errorMessage(e, 'Failed to discard.'));
    }
  }

  // Flush any unsaved line-item edits before leaving. If a save fails, stay on
  // the wizard and surface it rather than silently losing the edit.
  async function done() {
    if (doneBusy) return;
    doneBusy = true;
    try {
      await onDone?.();
      push(detailRoute);
    } catch (e) {
      showError(errorMessage(e, 'Some changes could not be saved — please fix and try again.'));
    } finally {
      doneBusy = false;
    }
  }
</script>

<div style="display: flex; justify-content: space-between; margin-top: 12px;">
  <button onclick={discard} style="color: #a00;">Discard draft</button>
  <button onclick={done} disabled={doneBusy}>{doneBusy ? 'Saving…' : 'Done'}</button>
</div>
