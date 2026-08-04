<script>
  import LinkifiedText from './LinkifiedText.svelte';
  import { formatMoney as fmtMoney } from '../lib/format.js';

  let {
    lineItems = [],
    categories = [],
    showSource = false,
    canEdit = false,         // true when document is draft + user can edit
    actions = null,          // optional snippet `(li, i) => ...` for action buttons
    // Estimate-only (task-owned-money Phase 3, Task 2): a line sourced from
    // a null-AC task/material atom is legitimate there — hand-lines still
    // require AC at entry (apps/estimates/services.py), so a null AC on an
    // estimate line always means "sourced from an uncategorized atom", not
    // an incomplete hand-line. Renders "Uncategorized" (informational, not
    // an error) instead of the "needs category" warning. Invoices keep the
    // warning treatment (default false) — the compose-time fallback stamp
    // that makes a null-AC invoice line impossible is Phase 3 Task 3, not
    // yet built.
    allowNullCategory = false,
  } = $props();

  const categoryById = $derived(
    Object.fromEntries((categories || []).map(c => [c.id, c]))
  );

  function lineTotal(li) { return Number(li.qty || 0) * Number(li.price || 0); }
  function categoryName(id) { return categoryById[id]?.name || '—'; }
  function categoryTaxable(id) {
    const c = categoryById[id];
    if (!c) return '—';
    return c.taxable ? 'Yes' : 'No';
  }

  let subtotal = $derived(
    (lineItems || []).reduce((s, li) => s + lineTotal(li), 0)
  );

  // Number of leading columns used to compute tfoot colspans (everything
  // before the Total column, counting the Source column when shown).
  let footerColspan = $derived(showSource ? 8 : 7);

  /** freeform_kind ('work'|'material'|'fee') is set IFF this is a bare
   *  hand-authored line (no inventory_item/service_item/adjustment_service) —
   *  catalog/service/adjustment lines carry null, so the badge only ever
   *  shows on hand lines. */
  const KIND_LABELS = { work: 'Work', material: 'Material', fee: 'Fee/Credit' };
  function kindLabel(k) { return KIND_LABELS[k] || ''; }

  /** Build the adjustment badge label, e.g. "+15% Rush on Labor, Materials" */
  function adjustmentBadge(li) {
    if (!li.adjustment_service) return '';
    const detail = li.adjustment_service_detail;
    if (!detail) return '';
    const pct = Number(detail.rate);
    const sign = pct >= 0 ? '+' : '';
    const targetNames = (li.adjustment_target_categories || [])
      .map(pk => categoryById[pk]?.name)
      .filter(Boolean);
    const targets = targetNames.length ? ' on ' + targetNames.join(', ') : '';
    return `${sign}${pct}% ${detail.name}${targets}`;
  }
</script>

{#if lineItems.length > 0}
  <table class="data-table">
    <thead>
      <tr>
        <th>#</th>
        <th>Type</th>
        <th>Taxable</th>
        <th>Description</th>
        {#if showSource}<th>Source</th>{/if}
        <th>Quantity</th>
        <th>Unit</th>
        <th>Price</th>
        <th>Total</th>
        {#if actions}<th>Actions</th>{/if}
      </tr>
    </thead>
    <tbody>
      {#each lineItems as li, i}
        <tr class:adjustment-row={!!li.adjustment_service}>
          <td>{li.line_number}</td>
          <td
            class:needs-category={canEdit && li.accounting_category == null && !allowNullCategory}
            class:uncategorized={li.accounting_category == null && allowNullCategory}
          >
            {#if li.accounting_category == null && allowNullCategory}
              Uncategorized
            {:else if canEdit && li.accounting_category == null}
              needs category
            {:else}
              {categoryName(li.accounting_category)}
            {/if}
          </td>
          <td>{categoryTaxable(li.accounting_category)}</td>
          <td class="preserve-breaks">
            {#if li.adjustment_service}
              <span class="adj-badge">{adjustmentBadge(li)}</span>
            {:else}
              {#if li.freeform_kind}
                <span class="kind-badge kind-{li.freeform_kind}">{kindLabel(li.freeform_kind)}</span>
              {/if}
              <LinkifiedText text={li.description || 'No description'} />
            {/if}
          </td>
          {#if showSource}
            <td>
              {#if li.sources?.length}
                <ul class="source-list">
                  {#each li.sources as s (s.source_type + ':' + s.source_pk)}
                    <li>{s.description} <span class="src-amt">{fmtMoney(s.computed_amount)}</span></li>
                  {/each}
                </ul>
              {:else if li.inventory_item}
                PLI #{li.inventory_item}
              {:else if li.adjustment_service}
                Adjustment
              {:else}
                No source
              {/if}
            </td>
          {/if}
          <td>{li.qty}</td>
          <td>{li.units || '—'}</td>
          <td>{fmtMoney(li.price)}</td>
          <td>{fmtMoney(lineTotal(li))}</td>
          {#if actions}
            <td>
              {@render actions(li, i)}
            </td>
          {/if}
        </tr>
      {/each}
    </tbody>
    <tfoot>
      <tr class="subtotal-row">
        <td colspan={footerColspan} style="text-align: right;"><strong>Subtotal:</strong></td>
        <td>{fmtMoney(subtotal)}</td>
        {#if actions}<td></td>{/if}
      </tr>
      <tr class="total-row">
        <td colspan={footerColspan} style="text-align: right;"><strong>Total:</strong></td>
        <td><strong>{fmtMoney(subtotal)}</strong></td>
        {#if actions}<td></td>{/if}
      </tr>
    </tfoot>
  </table>
{:else}
  <p>No line items.</p>
{/if}

<style>
  /* The table chrome (width, header band, padding, zebra) comes from the
     house `.data-table` in app.css. Only the line-item-specific row/cell
     semantics live here. */
  .subtotal-row { background-color: #f5f5f5; }
  .total-row { background-color: #e8e8e8; }
  .source-list { margin: 0; padding-left: 1em; list-style: disc; }
  .source-list li { font-size: 0.9em; }
  .src-amt { color: #555; }
  .adjustment-row { background-color: #f0f7ff; }
  .needs-category {
    background-color: #fff8e1;
    color: #b45309;
    font-style: italic;
  }
  .uncategorized {
    color: #6b7280;
    font-style: italic;
  }
  .adj-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    background: #dbeafe;
    color: #1e40af;
    font-size: 12px;
    font-weight: 600;
    white-space: nowrap;
  }
  .kind-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 600;
    white-space: nowrap;
    margin-right: 6px;
  }
  .kind-work { background: #e0e7ff; color: #3730a3; }
  .kind-material { background: #d1fae5; color: #065f46; }
  .kind-fee { background: #ffedd5; color: #9a3412; }
</style>
