<script>
  // The two modal-backed material fulfillment flows — Order (append to an
  // open draft PO or start a new one) and Mark on-hand / Mark received
  // (quantity receipt) — extracted from TasksPanel so every surface that
  // renders MaterialRow can offer them. Host pages mount this once and call
  // startOrder(material) / startReceipt(material) via bind:this.
  import { api } from '../../lib/api.js';
  import { showError, showSuccess } from '../../stores/messages.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { orderPrefillQty } from '../../lib/materials.js';
  import Modal from '../Modal.svelte';

  let { onDone = () => {} } = $props();

  // Order flow — draft-PO chooser dialog
  let orderDialogOpen = $state(false);
  let orderMaterial = $state(null);
  let orderDrafts = $state([]);
  let orderBusy = $state(false);

  // Receipt qty prompt — shared by "Mark on-hand" (quiet) and "Mark
  // received" (customer-supplied), both hitting the mark-on-hand endpoint.
  let receiptDialogOpen = $state(false);
  let receiptMaterial = $state(null);
  let receiptQty = $state('');
  let receiptBusy = $state(false);

  // Order flow. Zero open drafts → POST immediately (starts a new PO). One or
  // more → open the chooser so the user can append to an existing draft or
  // start a new one. Reversible process step: no confirm() dialog.
  export async function startOrder(material) {
    try {
      const resp = await api.get('/api/purchase-orders/?status=draft&page_size=100');
      const drafts = resp.results || resp;
      if (!drafts.length) {
        await submitOrder(material, null);
        return;
      }
      orderMaterial = material;
      orderDrafts = drafts;
      orderDialogOpen = true;
    } catch (e) {
      const t = triageError(e);
      showError(t.overlay || t.message || 'Could not load draft purchase orders.');
    }
  }

  async function submitOrder(material, poId) {
    orderBusy = true;
    try {
      const resp = await api.post(`/api/materials/${material.material_id}/order/`,
        poId ? { po_id: poId } : {});
      orderDialogOpen = false;
      orderMaterial = null;
      if (resp.po_id && resp.po_number) {
        showSuccess('Added to', {
          href: `#/purchase-orders/${resp.po_id}`, label: resp.po_number,
        });
      } else {
        showSuccess(`Added to ${resp.po_number || 'a new purchase order'}.`);
      }
      await onDone();
    } catch (e) {
      const t = triageError(e);
      showError(t.overlay || t.message || 'Could not order material.');
    } finally {
      orderBusy = false;
    }
  }

  function closeOrderDialog() {
    orderDialogOpen = false;
    orderMaterial = null;
  }

  // Receipt prompt (Mark on-hand / Mark received) — quantity input, not a
  // confirmation. Defaults to the outstanding shortfall.
  export function startReceipt(material) {
    receiptMaterial = material;
    receiptQty = orderPrefillQty(material);
    receiptDialogOpen = true;
  }

  async function submitReceipt() {
    const quantity = String(receiptQty).trim();
    if (!quantity) return;
    receiptBusy = true;
    try {
      await api.post(`/api/materials/${receiptMaterial.material_id}/mark-on-hand/`, { quantity });
      receiptDialogOpen = false;
      receiptMaterial = null;
      await onDone();
    } catch (e) {
      const t = triageError(e);
      showError(t.overlay || t.message || 'Could not mark received.');
    } finally {
      receiptBusy = false;
    }
  }

  function closeReceiptDialog() {
    receiptDialogOpen = false;
    receiptMaterial = null;
  }
</script>

<!-- Order chooser: Esc-only (no onSave) — with drafts present, Enter has no
     unambiguous primary action; the user picks a draft or "Start new PO". -->
<Modal open={orderDialogOpen} onCancel={closeOrderDialog} busy={orderBusy} maxWidth="480px" label="Order material">
  <h3>Order — {orderMaterial?.description || '(material)'}</h3>
  <p class="dialog-hint">Add this material to an open draft purchase order, or start a new one.</p>
  <ul class="draft-list">
    {#each orderDrafts as po (po.po_id)}
      <li>
        <button type="button" disabled={orderBusy} onclick={() => submitOrder(orderMaterial, po.po_id)}>
          {po.po_number} — {po.business_name || 'no vendor'}
        </button>
      </li>
    {/each}
  </ul>
  <p class="dialog-actions">
    <button type="button" disabled={orderBusy} onclick={() => submitOrder(orderMaterial, null)}>Start new PO</button>
    <button type="button" disabled={orderBusy} onclick={closeOrderDialog}>Cancel</button>
  </p>
</Modal>

<!-- Receipt qty prompt: native <form> owns Enter (Modal omits onSave). -->
<Modal open={receiptDialogOpen} onCancel={closeReceiptDialog} busy={receiptBusy} maxWidth="420px" label="Mark received">
  <form onsubmit={(e) => { e.preventDefault(); submitReceipt(); }}>
    <h3>Mark received — {receiptMaterial?.description || '(material)'}</h3>
    <p>
      <label for="receipt-qty"><strong>Quantity received</strong></label><br>
      <input id="receipt-qty" type="number" step="0.01" min="0" bind:value={receiptQty} required>
    </p>
    <p class="dialog-actions">
      <button type="submit" disabled={receiptBusy}>Mark received</button>
      <button type="button" disabled={receiptBusy} onclick={closeReceiptDialog}>Cancel</button>
    </p>
  </form>
</Modal>

<style>
  .dialog-hint { color: #555; font-size: 13px; }
  .draft-list { list-style: none; padding: 0; margin: 8px 0; max-height: 40vh; overflow-y: auto; }
  .draft-list li { margin: 0 0 4px; }
  .draft-list button {
    width: 100%; text-align: left; padding: 8px 10px;
    border: 1px solid #d1d5db; border-radius: 4px; background: #fff; cursor: pointer;
  }
  .draft-list button:hover { background: #f3f4f6; }
  .dialog-actions { display: flex; gap: 8px; margin-top: 12px; }
  .dialog-actions button {
    padding: 6px 14px; border: 1px solid #d1d5db; border-radius: 4px;
    background: #fff; cursor: pointer; font-size: 13px;
  }
  .dialog-actions button:hover { background: #f3f4f6; }
  .dialog-actions button:disabled { opacity: 0.5; cursor: default; }
</style>
