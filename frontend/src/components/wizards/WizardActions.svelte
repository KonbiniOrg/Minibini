<script>
  import { api } from '../../lib/api.js';
  import { push } from 'svelte-spa-router';

  let {
    apiBase,            // e.g. '/api/invoices/123' or '/api/estimates/123'
    detailRoute,        // e.g. '/invoices/123' or '/estimates/123'
    discardRoute = '/', // where to go after discarding (default: home)
  } = $props();

  // No confirm: the draft is easily remade from its source on the page the
  // user returns to, so discarding is effectively reversible.
  async function discard() {
    try {
      await api.delete(`${apiBase}/?confirm=true`);
      push(discardRoute);
    } catch (e) {
      alert(e.message || 'Failed to discard');
    }
  }

  function done() {
    push(detailRoute);
  }
</script>

<div style="display: flex; justify-content: space-between; margin-top: 12px;">
  <button onclick={discard} style="color: #a00;">Discard draft</button>
  <button onclick={done}>Done</button>
</div>
