<script>
  import LinkifiedText from './LinkifiedText.svelte';

  let {
    lineItems = [],
    categories = [],
    showSource = false,
    canEdit = false,         // true when document is draft + user can edit
    actions = null,          // optional snippet `(li, i) => ...` for action buttons
  } = $props();

  const categoryById = $derived(
    Object.fromEntries((categories || []).map(c => [c.id, c]))
  );

  function fmtMoney(n) { return `$${Number(n).toFixed(2)}`; }
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
        <tr class:adjustment-row={!!li.adjustment_service} class:comment-row={li.is_comment}>
          <td>{li.line_number}</td>
          <td class:needs-category={canEdit && !li.is_comment && li.accounting_category == null}>
            {#if li.is_comment}
              —
            {:else if canEdit && li.accounting_category == null}
              needs category
            {:else}
              {categoryName(li.accounting_category)}
            {/if}
          </td>
          <td>{li.is_comment ? '—' : categoryTaxable(li.accounting_category)}</td>
          <td class="preserve-breaks">
            {#if li.is_comment}
              <span class="comment-badge">Comment</span>
              <LinkifiedText text={li.description || 'No description'} />
            {:else if li.adjustment_service}
              <span class="adj-badge">{adjustmentBadge(li)}</span>
            {:else}
              <LinkifiedText text={li.description || 'No description'} />
            {/if}
          </td>
          {#if showSource}
            <td>
              {#if li.is_comment}
                —
              {:else if li.sources?.length}
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
          {#if li.is_comment}
            <td>—</td>
            <td>—</td>
            <td>—</td>
            <td>—</td>
          {:else}
            <td>{li.qty}</td>
            <td>{li.units || '—'}</td>
            <td>{fmtMoney(li.price)}</td>
            <td>{fmtMoney(lineTotal(li))}</td>
          {/if}
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
  .comment-row { background-color: #fafafa; font-style: italic; color: #555; }
  .comment-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    background: #e5e5e5;
    color: #444;
    font-size: 12px;
    font-weight: 600;
    font-style: normal;
    white-space: nowrap;
    margin-right: 6px;
  }
  .needs-category {
    background-color: #fff8e1;
    color: #b45309;
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
</style>
