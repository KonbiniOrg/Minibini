<script>
  const { purchaseOrders = [], onSelect = null } = $props();

  function formatDate(d) {
    if (!d) return '';
    return new Date(d).toLocaleDateString();
  }

  function totalAmount(lineItems) {
    if (!lineItems?.length) return 0;
    return lineItems.reduce((sum, li) => sum + Number(li.qty) * Number(li.price), 0);
  }
</script>

{#if purchaseOrders.length === 0}
  <p>No purchase orders found.</p>
{:else}
  <table class="data-table">
    <thead>
      <tr>
        <th>PO #</th>
        <th>Vendor</th>
        <th>Status</th>
        <th>Created</th>
        <th>Requested</th>
        <th class="text-right">Total</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {#each purchaseOrders as po}
        <tr>
          <td>
            {#if onSelect}
              <button onclick={() => onSelect(po)}>
                {po.po_number}
              </button>
            {:else}
              {po.po_number}
            {/if}
          </td>
          <td>{po.business_name || '—'}</td>
          <td>{po.status}</td>
          <td>{formatDate(po.created_date)}</td>
          <td>{formatDate(po.requested_date)}</td>
          <td class="text-right">${totalAmount(po.line_items).toFixed(2)}</td>
          <td>
            {#if po.awaiting_reconciliation}
              <span class="awaiting-badge">Awaiting Reconciliation</span>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}

<style>
  .text-right { text-align: right; }
  .awaiting-badge {
    font-size: 11px; font-weight: 600; padding: 2px 8px;
    border-radius: 8px; white-space: nowrap;
    background: #fef3c7; color: #92400e;
  }
</style>
