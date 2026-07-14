<script>
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError, showSuccess } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';

  let { item, prefillQty = '', onDone = () => {}, onCancel = () => {} } = $props();

  let qty = $state(prefillQty);
  let drafts = $state(null);   // null = qty phase; [] handled inline
  let busy = $state(false);
  let qtyError = $state('');

  // Phase 1 → on Order: look for open drafts. Zero → order immediately
  // (silent create, same contract as the material order flow); some →
  // show the chooser.
  async function startOrder() {
    qtyError = '';
    if (!String(qty).trim() || Number(qty) <= 0) {
      qtyError = 'Enter a quantity greater than 0.';
      return;
    }
    busy = true;
    try {
      const resp = await api.get('/api/purchase-orders/?status=draft&page_size=100');
      const found = resp.results || resp;
      if (!found.length) {
        await submit(null);
        return;
      }
      drafts = found;
    } catch (e) {
      const t = triageError(e);
      showError(t.overlay || t.message || 'Could not load draft purchase orders.');
    } finally {
      busy = false;
    }
  }

  async function submit(poId) {
    busy = true;
    try {
      const body = poId
        ? { quantity: String(qty), po_id: poId }
        : { quantity: String(qty) };
      const resp = await api.post(
        `/api/inventory/${item.inventory_item_id}/order/`, body);
      showSuccess('Added to', {
        href: `#/purchase-orders/${resp.po_id}`, label: resp.po_number,
      });
      onDone();
    } catch (e) {
      const t = triageError(e);
      showError(t.overlay || t.message || 'Could not order.');
    } finally {
      busy = false;
    }
  }
</script>

<Modal open={true} onCancel={onCancel} busy={busy} maxWidth="480px" label="Order stock">
  <h3>Order — {item.code}</h3>
  {#if drafts === null}
    <p><label for="stock-order-qty">Quantity</label><br>
      <input id="stock-order-qty" type="number" step="0.01" min="0"
        bind:value={qty} oninput={() => qtyError = ''}></p>
    {#if qtyError}<p style="color:#c00">{qtyError}</p>{/if}
    <p>
      <button type="button" disabled={busy} onclick={startOrder}>Order</button>
      <button type="button" disabled={busy} onclick={onCancel}>Cancel</button>
    </p>
  {:else}
    <p>Add to an open draft PO, or start a new one:</p>
    <ul>
      {#each drafts as po (po.po_id)}
        <li><button type="button" disabled={busy} onclick={() => submit(po.po_id)}>
          {po.po_number} — {po.business_name || 'no vendor'}
        </button></li>
      {/each}
    </ul>
    <p>
      <button type="button" disabled={busy} onclick={() => submit(null)}>Start new PO</button>
      <button type="button" disabled={busy} onclick={onCancel}>Cancel</button>
    </p>
  {/if}
</Modal>
