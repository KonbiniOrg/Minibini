<script>
  // Job-scoped read-only PO list. POs aren't job-owned (a PO's line items can
  // span jobs), so this panel never offers create — creation stays on the
  // global Purchase Orders page. Copies field usage from PurchaseOrderList.svelte
  // / PurchaseOrderSerializer: po_id, po_number, status, business_name, po_total.
  import { api, errorMessage } from '../../lib/api.js';
  import LoadState from '../LoadState.svelte';
  import DataTable from '../DataTable.svelte';

  let { job } = $props();

  const jobId = $derived(job?.job_id);

  let purchaseOrders = $state([]);
  let loading = $state(true);
  let errorMsg = $state('');

  async function load() {
    loading = true;
    errorMsg = '';
    try {
      const resp = await api.get(`/api/purchase-orders/?job=${jobId}`);
      purchaseOrders = resp?.results || resp || [];
    } catch (e) {
      errorMsg = errorMessage(e, 'Could not load purchase orders.');
    } finally {
      loading = false;
    }
  }

  $effect(() => { if (jobId) load(); });

  function formatTotal(total) {
    return total != null ? `$${Number(total).toFixed(2)}` : '—';
  }
</script>

<div class="page-body">
  <LoadState {loading} error={errorMsg}>
    <DataTable
      rows={purchaseOrders}
      key={(po) => po.po_id}
      emptyText="No purchase orders touch this job yet."
      columns={[
        { id: 'number', label: 'PO #',   cell: numberCell },
        { id: 'status', label: 'Status', cell: statusCell },
        { id: 'vendor', label: 'Vendor', cell: vendorCell },
        { id: 'total',  label: 'Total',  cell: totalCell, align: 'right' },
      ]}
    />
  </LoadState>
</div>


{#snippet numberCell(po)}<a href={`#/purchase-orders/${po.po_id}`}>{po.po_number}</a>{/snippet}
{#snippet statusCell(po)}<span class="status-badge status-{po.status}">{po.status}</span>{/snippet}
{#snippet vendorCell(po)}{po.business_name || '—'}{/snippet}
{#snippet totalCell(po)}{formatTotal(po.po_total)}{/snippet}

<style>
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .err { color: #c00; }
</style>
