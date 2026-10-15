<script>
  // The two modal-backed material fulfillment flows — Order (OrderModal) and Mark on-hand / Mark received
  // (quantity receipt) — extracted from TasksPanel so every surface that
  // renders MaterialRow can offer them. Host pages mount this once and call
  // startOrder(material) / startReceipt(material) via bind:this.
  import { api } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { orderPrefillQty } from '../../lib/materials.js';
  import Modal from '../Modal.svelte';
  import OrderModal from '../purchaseorders/OrderModal.svelte';

  let { onDone = () => {} } = $props();

  // Order flow — OrderModal owns the whole dialog (vendor, draft choice, line).
  let orderMaterial = $state(null);

  // Receipt qty prompt — shared by "Mark on-hand" (quiet) and "Mark
  // received" (customer-supplied), both hitting the mark-on-hand endpoint.
  let receiptDialogOpen = $state(false);
  let receiptMaterial = $state(null);
  let receiptQty = $state('');
  let receiptBusy = $state(false);

  export function startOrder(material) { orderMaterial = material; }

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

{#if orderMaterial}
  <OrderModal source="material" material={orderMaterial}
    onDone={async () => { orderMaterial = null; await onDone(); }}
    onCancel={() => { orderMaterial = null; }} />
{/if}

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
  .dialog-actions { display: flex; gap: 8px; margin-top: 12px; }
  .dialog-actions button {
    padding: 6px 14px; border: 1px solid #d1d5db; border-radius: 4px;
    background: #fff; cursor: pointer; font-size: 13px;
  }
  .dialog-actions button:hover { background: #f3f4f6; }
  .dialog-actions button:disabled { opacity: 0.5; cursor: default; }
</style>
