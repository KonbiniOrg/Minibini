<script>
  import { api } from '../../lib/api.js';
  import PurchaseOrderList from '../../components/purchaseorders/PurchaseOrderList.svelte';
  import { push } from 'svelte-spa-router';
  import { canManageFinancials as canManageFinancialsStore } from '../../stores/permissions.js';
  import { pageRange, pageFromUrl } from '../../lib/pagination.js';

  let purchaseOrders = $state(null);
  let page = $state(1);
  let loading = $state(true);
  let error = $state(null);
  let statusFilter = $state('');

  let canManageFinancials = $derived($canManageFinancialsStore);

  async function loadPOs() {
    loading = true;
    error = null;
    try {
      let url = `/api/purchase-orders/?page=${page}`;
      if (statusFilter) {
        url += `&status=${statusFilter}`;
      }
      purchaseOrders = await api.get(url);
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function handleSelect(po) {
    push(`/purchase-orders/${po.po_id}`);
  }

  $effect(() => {
    void page;
    void statusFilter;
    loadPOs();
  });
</script>

<div class="page-body">
<h2>Purchase Orders {purchaseOrders ? `(${purchaseOrders.count})` : ''}</h2>

<p>
  {#if canManageFinancials}
    <a href="#/purchase-orders/new">New Purchase Order</a> |
  {/if}
  <label>
    Status:
    <select bind:value={statusFilter} onchange={() => { page = 1; }}>
      <option value="">All</option>
      <option value="draft">Draft</option>
      <option value="issued">Issued</option>
      <option value="partly_received">Partly Received</option>
      <option value="received_in_full">Received in Full</option>
      <option value="cancelled">Cancelled</option>
    </select>
  </label>
</p>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else if purchaseOrders}
  <PurchaseOrderList
    purchaseOrders={purchaseOrders.results}
    onSelect={handleSelect}
  />

  {#if purchaseOrders.count > 25}
    <p>
      {pageRange(purchaseOrders)}
      {#if purchaseOrders.previous}
        | <button onclick={() => { page = pageFromUrl(purchaseOrders.previous); }}>Previous</button>
      {/if}
      {#if purchaseOrders.next}
        | <button onclick={() => { page = pageFromUrl(purchaseOrders.next); }}>Next</button>
      {/if}
    </p>
  {/if}
{/if}
</div>
