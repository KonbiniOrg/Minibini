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

  // Mount-seed by design. The parent (PurchaseOrderDetailPage) remounts
  // this section via `{#key}` on every successful save (keyed off
  // po.reconciled_date, which always changes) — that's load-bearing, not
  // just a resync convenience: a same-session invoice-only line has no
  // server id until the save round-trips, so without a forced remount its
  // `line_item_id` would stay null even after the server assigned one,
  // breaking the persisted-removal notice and causing a later save to
  // delete-recreate the row instead of updating it in place.
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

  // Persisted invoice-only rows the user has removed THIS session but not
  // yet saved. No confirm() on Remove (repo doctrine: it's reversible —
  // re-add it) — but "reversible" only holds if the section is honest
  // about the save-time consequence: unlike a same-session draft add,
  // removing a row that already has a `line_item_id` means the append-only
  // mirror (PurchaseOrderService.reconcile) will hard-delete it server-side
  // if it's not resent. Tracked separately (not just "missing from
  // `appended`") so the notice can list exactly what's at risk and offer a
  // one-click re-add that clears it.
  let removedPersisted = $state([]);

  function addAppendedLine() {
    appended.push({
      _key: nextKey--, line_item_id: null,
      description: '', qty: '', units: 'none', price: '',
      accounting_category: '', task: null,
    });
  }

  function removeAppendedLine(row) {
    // No confirm: pre-save, reversible by re-adding — see removedPersisted
    // above for why a persisted row needs its own honest notice instead of
    // silently vanishing.
    const idx = appended.indexOf(row);
    if (idx < 0) return;
    appended.splice(idx, 1);
    if (row.line_item_id != null) {
      removedPersisted.push(row);
    }
  }

  function restoreAppendedLine(row) {
    const idx = removedPersisted.indexOf(row);
    if (idx < 0) return;
    removedPersisted.splice(idx, 1);
    appended.push(row);
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

      {#if removedPersisted.length}
        <div class="recon-notice">
          <p>
            {removedPersisted.length}
            recorded line{removedPersisted.length === 1 ? '' : 's'}
            will be deleted when you save —
            re-add {removedPersisted.length === 1 ? 'it' : 'them'} to keep
            {removedPersisted.length === 1 ? 'it' : 'them'}.
          </p>
          <ul>
            {#each removedPersisted as row (row._key)}
              <li>
                {row.description}
                <button type="button" onclick={() => restoreAppendedLine(row)}>Re-add</button>
              </li>
            {/each}
          </ul>
        </div>
      {/if}
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
  /* Same amber warning treatment as the PO list's awaiting-reconciliation
     badge and the line-status "partial" pill — the codebase's established
     caution color, reused here for consistency rather than inventing one. */
  .recon-notice {
    background: #fef3c7; color: #92400e;
    border-radius: 4px; padding: 4px 10px; margin: 0.5em 0;
  }
  .recon-notice ul { margin: 0.25em 0 0.25em 1.2em; padding: 0; }
</style>
