<script>
  // PO reconciliation (task-owned-money Phase 5, spec §7 rule 3): bill
  // total, vendor invoice ref, per-line final prices, and invoice-only
  // appended lines (freight, tax, etc. that were never ordered/received).
  //
  // WHOLESALE REPLACE semantics mirror the backend (PurchaseOrderService.
  // reconcile docstring): every save resends the COMPLETE current picture —
  // omitted ordered-line final prices revert to "as ordered" (null), and
  // any previously-appended invoice_only line not resent is deleted
  // server-side. The form prefills every editable field from the PO's
  // current state, so a save with no edits is an identity operation.
  import UnitsSelect from '../UnitsSelect.svelte';
  import TaskLinkPicker from '../TaskLinkPicker.svelte';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';
  import { formatMoney } from '../../lib/format.js';

  const {
    po,
    canManageFinancials = false,
    categories = [],
    busy = false,
    errors = {},
    formError = '',
    onReconcile = null,
  } = $props();

  const orderedLines = $derived(
    (po.line_items || []).filter((li) => !li.invoice_only)
      .slice().sort((a, b) => a.line_number - b.line_number)
  );
  const existingAppended = $derived(
    (po.line_items || []).filter((li) => li.invoice_only)
      .slice().sort((a, b) => a.line_number - b.line_number)
  );

  // Mount-seed by design (parent remounts this section via {#key} if it
  // ever needs a hard resync — e.g. after a save, the just-submitted
  // values already match what's shown, so no resync is required for
  // identity to hold on the next save).
  // svelte-ignore state_referenced_locally
  let billTotal = $state(po.bill_total ?? '');
  // svelte-ignore state_referenced_locally
  let vendorRef = $state(po.vendor_invoice_ref ?? '');

  // svelte-ignore state_referenced_locally -- mount-seed by design (see note above)
  const finals = $state(
    Object.fromEntries(orderedLines.map((li) => [li.line_item_id, li.final_price ?? '']))
  );

  let nextKey = -1;
  function appendedRow(li) {
    return {
      _key: li.line_item_id,
      line_item_id: li.line_item_id,
      description: li.description,
      qty: li.qty,
      units: li.units || 'none',
      price: li.price,
      accounting_category: li.accounting_category || '',
      task: li.task || null,
    };
  }
  // svelte-ignore state_referenced_locally -- mount-seed by design (see note above)
  const appended = $state(existingAppended.map(appendedRow));

  function addAppendedLine() {
    appended.push({
      _key: nextKey--, line_item_id: null,
      description: '', qty: '', units: 'none', price: '',
      accounting_category: '', task: null,
    });
  }

  function removeAppendedLine(row) {
    // No confirm: pre-save, reversible by re-adding.
    const idx = appended.indexOf(row);
    if (idx >= 0) appended.splice(idx, 1);
  }

  function buildPayload() {
    const line_finals = {};
    for (const li of orderedLines) {
      const v = finals[li.line_item_id];
      if (v !== '' && v != null) {
        line_finals[li.line_item_id] = v;
      }
    }
    const appended_lines = appended.map((row) => {
      const entry = {
        description: row.description,
        qty: Number(row.qty),
        units: row.units,
        price: row.price,
      };
      if (row.line_item_id != null) entry.line_item_id = row.line_item_id;
      if (row.accounting_category) entry.accounting_category = Number(row.accounting_category);
      if (row.task) entry.task = row.task;
      return entry;
    });
    return {
      bill_total: billTotal === '' ? null : billTotal,
      vendor_invoice_ref: vendorRef,
      line_finals,
      appended_lines,
    };
  }

  function handleSubmit(e) {
    e.preventDefault();
    if (onReconcile) onReconcile(buildPayload());
  }

  const varianceDisplay = $derived(
    po.variance == null ? null : formatMoney(po.variance)
  );
</script>

{#if po.status !== 'draft'}
  <h3>Reconciliation</h3>

  {#if canManageFinancials}
    <form onsubmit={handleSubmit}>
      <p>
        <label for="recon-bill-total"><strong>Bill Total</strong></label><br>
        <input type="number" id="recon-bill-total" bind:value={billTotal} step="0.01" min="0">
        <FieldError {errors} field="bill_total" />
      </p>
      <p>
        <label for="recon-vendor-ref"><strong>Vendor Invoice Ref</strong></label><br>
        <input type="text" id="recon-vendor-ref" bind:value={vendorRef}>
        <FieldError {errors} field="vendor_invoice_ref" />
      </p>

      {#if orderedLines.length}
        <table class="data-table">
          <thead>
            <tr>
              <th>#</th><th>Description</th><th class="text-right">Ordered Price</th>
              <th class="text-right">Final Price</th>
            </tr>
          </thead>
          <tbody>
            {#each orderedLines as li}
              <tr>
                <td>{li.line_number}</td>
                <td>{li.description}</td>
                <td class="text-right">${Number(li.price).toFixed(2)}</td>
                <td class="text-right">
                  <input type="number" step="0.01" min="0"
                    placeholder="as ordered"
                    bind:value={finals[li.line_item_id]}
                    style="width:90px;text-align:right;">
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
      <FieldError {errors} field="line_finals" />

      <h4>Invoice-Only Lines</h4>
      <p><small>Vendor-invoice-only charges (e.g. freight) never ordered or received.</small></p>
      {#if appended.length}
        <table class="data-table">
          <thead>
            <tr>
              <th>Description</th><th class="text-right">Qty</th><th>Units</th>
              <th class="text-right">Price</th><th>Category</th><th>Task Link</th><th></th>
            </tr>
          </thead>
          <tbody>
            {#each appended as row (row._key)}
              <tr>
                <td><input type="text" bind:value={row.description} required></td>
                <td><input type="number" step="any" min="0" bind:value={row.qty} required style="width:70px;text-align:right;"></td>
                <td><UnitsSelect bind:value={row.units} /></td>
                <td><input type="number" step="0.01" min="0" bind:value={row.price} required style="width:80px;text-align:right;"></td>
                <td>
                  <select bind:value={row.accounting_category}>
                    <option value="">-- None --</option>
                    {#each categories as cat}
                      <option value={cat.id}>{cat.name}</option>
                    {/each}
                  </select>
                </td>
                <td><TaskLinkPicker bind:value={row.task} /></td>
                <td><button type="button" onclick={() => removeAppendedLine(row)}>Remove</button></td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
      <p>
        <button type="button" onclick={addAppendedLine}>Add Invoice-Only Line</button>
      </p>
      <FieldError {errors} field="appended_lines" />

      <p><strong>Variance:</strong> {varianceDisplay ?? '—'}</p>

      <p>
        <button type="submit" disabled={busy}>{po.reconciled ? 'Update reconciliation' : 'Reconcile'}</button>
      </p>
      <FormMessage error={formError} />
    </form>
  {:else if po.reconciled}
    <dl>
      <dt>Bill Total</dt><dd>{po.bill_total == null ? '—' : formatMoney(po.bill_total)}</dd>
      <dt>Vendor Invoice Ref</dt><dd>{po.vendor_invoice_ref || '—'}</dd>
      <dt>Reconciled</dt>
      <dd>{po.reconciled_date ? new Date(po.reconciled_date).toLocaleDateString() : '—'}</dd>
      <dt>Variance</dt><dd>{varianceDisplay ?? '—'}</dd>
    </dl>
    {#if existingAppended.length}
      <table class="data-table">
        <thead><tr><th>Description</th><th class="text-right">Qty</th><th class="text-right">Price</th></tr></thead>
        <tbody>
          {#each existingAppended as li}
            <tr><td>{li.description}</td><td class="text-right">{li.qty}</td><td class="text-right">${Number(li.price).toFixed(2)}</td></tr>
          {/each}
        </tbody>
      </table>
    {/if}
  {/if}
{/if}

<style>
  .text-right { text-align: right; }
</style>
