<script>
  import { api } from '../../lib/api.js';
  import { push } from 'svelte-spa-router';

  let {
    invoiceId,
    onchange,
  } = $props();

  async function addManual() {
    try {
      await api.post(`/api/invoices/${invoiceId}/line-items/`, {
        description: '',
        qty: '1',
        units: 'each',
        price: '0.00',
      });
      onchange?.();
    } catch (e) {
      alert(e.message || 'Failed to add manual line item');
    }
  }

  async function discardDraft() {
    if (!confirm('Delete this draft invoice and release all atoms?')) return;
    try {
      await api.delete(`/api/invoices/${invoiceId}/?confirm=true`);
      push('/');
    } catch (e) {
      alert(e.message || 'Failed to discard');
    }
  }

  function done() {
    push(`/invoices/${invoiceId}`);
  }
</script>

<div style="display: flex; justify-content: space-between; margin-top: 12px;">
  <button onclick={discardDraft} style="color: #a00;">Discard draft</button>
  <div style="display: flex; gap: 6px;">
    <button onclick={addManual}>+ Manual</button>
    <button onclick={done}>Done</button>
  </div>
</div>
