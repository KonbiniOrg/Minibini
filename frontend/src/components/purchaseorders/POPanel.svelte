<script>
  // Job-scoped read-only PO list. POs aren't job-owned (a PO's line items can
  // span jobs), so this panel never offers create — creation stays on the
  // global Purchase Orders page. Copies field usage from PurchaseOrderList.svelte
  // / PurchaseOrderSerializer: po_id, po_number, status, business_name, po_total.
  import { api } from '../../lib/api.js';

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
      errorMsg = e.message || 'Could not load purchase orders.';
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
  {#if loading}
    <p>Loading…</p>
  {:else if errorMsg}
    <p class="err">{errorMsg}</p>
  {:else if purchaseOrders.length === 0}
    <p>No purchase orders touch this job yet.</p>
  {:else}
    <table class="data-table">
      <thead>
        <tr>
          <th>PO #</th>
          <th>Status</th>
          <th>Vendor</th>
          <th class="num">Total</th>
        </tr>
      </thead>
      <tbody>
        {#each purchaseOrders as po (po.po_id)}
          <tr>
            <td><a href={`#/purchase-orders/${po.po_id}`}>{po.po_number}</a></td>
            <td><span class="status-badge status-{po.status}">{po.status}</span></td>
            <td>{po.business_name || '—'}</td>
            <td class="num">{formatTotal(po.po_total)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</div>

<style>
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .err { color: #c00; }
</style>
