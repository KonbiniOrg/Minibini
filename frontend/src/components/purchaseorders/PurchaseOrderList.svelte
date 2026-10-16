<script>
  import DataTable from '../DataTable.svelte';
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

<DataTable
  rows={purchaseOrders}
  key={(po) => po.po_id}
  emptyText="No purchase orders found."
  columns={[
    { id: 'number',    label: 'PO #',      cell: numberCell },
    { id: 'vendor',    label: 'Vendor',    cell: vendorCell },
    { id: 'status',    label: 'Status',    field: 'status' },
    { id: 'created',   label: 'Created',   cell: createdCell },
    { id: 'requested', label: 'Requested', cell: requestedCell },
    { id: 'total',     label: 'Total',     cell: totalCell, align: 'right' },
    { id: 'flags',     label: '',          cell: flagsCell },
  ]}
/>

{#snippet numberCell(po)}
  {#if onSelect}
    <button onclick={() => onSelect(po)}>{po.po_number}</button>
  {:else}
    {po.po_number}
  {/if}
{/snippet}
{#snippet vendorCell(po)}{po.business_name || '—'}{/snippet}
{#snippet createdCell(po)}{formatDate(po.created_date)}{/snippet}
{#snippet requestedCell(po)}{formatDate(po.requested_date)}{/snippet}
{#snippet totalCell(po)}${totalAmount(po.line_items).toFixed(2)}{/snippet}
{#snippet flagsCell(po)}
  {#if po.awaiting_reconciliation}
    <span class="awaiting-badge">Awaiting Reconciliation</span>
  {/if}
{/snippet}

<style>
  .awaiting-badge {
    font-size: 11px; font-weight: 600; padding: 2px 8px;
    border-radius: 8px; white-space: nowrap;
    background: #fef3c7; color: #92400e;
  }
</style>
