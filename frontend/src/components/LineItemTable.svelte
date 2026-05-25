<script>
  import LinkifiedText from './LinkifiedText.svelte';

  let {
    lineItems = [],
    categories = [],
    showSource = false,
    actions = null,        // optional snippet `(li, i) => ...` for action buttons
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
  function sourceLabel(li) {
    if (li.sources?.length) return `${li.sources.length} atom${li.sources.length === 1 ? '' : 's'}`;
    if (li.price_list_item) return `PLI #${li.price_list_item}`;
    return 'No source';
  }

  let subtotal = $derived(
    (lineItems || []).reduce((s, li) => s + lineTotal(li), 0)
  );

  // Number of leading columns used to compute tfoot colspans (everything
  // before the Total column, counting the Source column when shown).
  let footerColspan = $derived(showSource ? 8 : 7);
</script>

{#if lineItems.length > 0}
  <table class="line-items-table">
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
        <tr>
          <td>{li.line_number}</td>
          <td>{categoryName(li.accounting_category)}</td>
          <td>{categoryTaxable(li.accounting_category)}</td>
          <td class="preserve-breaks"><LinkifiedText text={li.description || 'No description'} /></td>
          {#if showSource}<td>{sourceLabel(li)}</td>{/if}
          <td>{li.qty}</td>
          <td>{li.units || '—'}</td>
          <td>{fmtMoney(li.price)}</td>
          <td>{fmtMoney(lineTotal(li))}</td>
          {#if actions}<td>{@render actions(li, i)}</td>{/if}
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
  .line-items-table { border-collapse: collapse; width: 100%; margin-top: 10px; }
  .line-items-table th, .line-items-table td { padding: 6px 10px; }
  .subtotal-row { background-color: #f5f5f5; }
  .total-row { background-color: #e8e8e8; }
</style>
