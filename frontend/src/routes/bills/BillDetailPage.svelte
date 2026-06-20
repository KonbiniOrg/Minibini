<script>
  import { onMount } from 'svelte';
  import { push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { canManageFinancials } from '../../stores/permissions.js';
  import LineItemModal from '../../components/LineItemModal.svelte';
  import RecordPaymentModal from '../../components/RecordPaymentModal.svelte';

  let { params = {} } = $props();
  let billId = $derived(params.id);

  let bill = $state(null);
  let categories = $state([]);
  let loading = $state(true);
  let error = $state(null);
  let cancelReason = $state('');

  // LineItemModal state
  let modalOpen = $state(false);
  let modalMode = $state('create');
  let modalItem = $state(null);

  let isDraft = $derived(bill?.status === 'draft');
  let isReceived = $derived(bill?.status === 'received');
  let isPayable = $derived(bill?.status === 'received' || bill?.status === 'partly_paid');

  // RecordPaymentModal state
  let showPayment = $state(false);
  let payDefault = $state('');
  let lineItems = $derived(
    (bill?.line_items || []).slice().sort((a, b) => a.line_number - b.line_number)
  );

  async function load() {
    loading = true;
    error = null;
    try {
      bill = await api.get(`/api/bills/${billId}/`);
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function loadCategories() {
    try {
      const resp = await api.get('/api/accounting-categories/?page_size=100');
      categories = resp.results || resp;
    } catch (_) {
      categories = [];
    }
  }

  onMount(() => {
    load();
    loadCategories();
  });

  function openAddItem() { modalItem = null; modalMode = 'create'; modalOpen = true; }
  function openEditItem(li) { modalItem = li; modalMode = 'edit'; modalOpen = true; }
  function handleSaved() { modalOpen = false; modalItem = null; load(); }

  async function handleDeleteItem(li) {
    try {
      await api.delete(`/api/bills/${billId}/line-items/${li.line_item_id}/`);
      await load();
    } catch (e) {
      alert(e.message || 'Could not delete line item.');
    }
  }

  function lineTotal(li) {
    return `$${(Number(li.qty || 0) * Number(li.price || 0)).toFixed(2)}`;
  }

  async function doAction(action, body = undefined) {
    try {
      await api.post(`/api/bills/${billId}/${action}/`, body);
      cancelReason = '';
      await load();
    } catch (e) {
      alert(e.message || `Could not perform action: ${action}`);
    }
  }

  async function deletePayment(pid) {
    await api.delete(`/api/bills/${bill.bill_id}/payments/${pid}/`);
    load();
  }

  async function deleteBill() {
    if (!confirm('Delete this draft bill? This cannot be undone.')) return;
    try {
      await api.delete(`/api/bills/${billId}/`);
      push('/bills');
    } catch (e) {
      alert(e.message || 'Could not delete bill.');
    }
  }
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p class="error"><strong>Error:</strong> {error}</p>
{:else if bill}
  <h2>Bill {bill.vendor_invoice_number || `#${bill.bill_id}`}</h2>

  <table class="metadata-table">
    <tbody>
      <tr><td><strong>Vendor</strong></td><td>{bill.vendor_name || '—'}</td></tr>
      <tr><td><strong>Vendor Invoice #</strong></td><td>{bill.vendor_invoice_number || '—'}</td></tr>
      <tr><td><strong>PO</strong></td>
        <td>
          {#if bill.po_number}
            <a href={`#/purchase-orders/${bill.purchase_order}`}>{bill.po_number}</a>
          {:else}
            —
          {/if}
        </td>
      </tr>
      <tr><td><strong>Status</strong></td><td>{bill.status}</td></tr>
      <tr><td><strong>Due</strong></td><td>{bill.due_date ? bill.due_date.slice(0, 10) : '—'}</td></tr>
      <tr><td><strong>Received</strong></td><td>{bill.received_date ? bill.received_date.slice(0, 10) : '—'}</td></tr>
      <tr><td><strong>Paid</strong></td><td>{bill.paid_date ? bill.paid_date.slice(0, 10) : '—'}</td></tr>
      <tr><td><strong>Balance</strong></td><td>${Number(bill.balance).toFixed(2)}</td></tr>
    </tbody>
  </table>

  {#if $canManageFinancials && isDraft}
    <p><a href={`#/bills/${bill.bill_id}/edit`}>Edit header</a></p>
  {/if}

  <h3>Line Items</h3>

  {#if $canManageFinancials && isDraft}
    <p>
      <button type="button" onclick={openAddItem}>Add Line Item</button>
    </p>
  {/if}

  <table class="data-table">
    <thead>
      <tr>
        <th>#</th>
        <th>Description</th>
        <th class="text-right">Qty</th>
        <th>Units</th>
        <th class="text-right">Price</th>
        <th class="text-right">Total</th>
        {#if $canManageFinancials && isDraft}<th></th>{/if}
      </tr>
    </thead>
    <tbody>
      {#each lineItems as li (li.line_item_id)}
        <tr>
          <td>{li.line_number}</td>
          <td>{li.description}</td>
          <td class="text-right">{li.qty}</td>
          <td>{li.units || '—'}</td>
          <td class="text-right">${Number(li.price).toFixed(2)}</td>
          <td class="text-right">{lineTotal(li)}</td>
          {#if $canManageFinancials && isDraft}
            <td>
              <button type="button" onclick={() => openEditItem(li)}>Edit</button>
              <button type="button" onclick={() => handleDeleteItem(li)}>Delete</button>
            </td>
          {/if}
        </tr>
      {/each}
      {#if lineItems.length === 0}
        <tr><td colspan={$canManageFinancials && isDraft ? 7 : 6}>No line items.</td></tr>
      {/if}
    </tbody>
  </table>

  {#if $canManageFinancials}
    <h3>Actions</h3>
    {#if isDraft}
      <p>
        <button type="button"
                onclick={() => doAction('receive')}
                disabled={lineItems.length === 0}>
          Mark Received
        </button>
        {#if lineItems.length === 0}
          <small>Add a line item first.</small>
        {/if}
        &nbsp;
        <button type="button" onclick={deleteBill}>Delete</button>
      </p>
    {:else if isReceived}
      <p>
        <label>
          Reason for cancel (required):<br>
          <input type="text" bind:value={cancelReason} placeholder="Enter reason…">
        </label>
        <button type="button"
                onclick={() => doAction('cancel', { reason: cancelReason })}
                disabled={!cancelReason.trim()}>
          Cancel Bill
        </button>
      </p>
    {/if}
    {#if isPayable && $canManageFinancials}
      <p>
        <button type="button" onclick={() => { payDefault = ''; showPayment = true; }}>Record Payment</button>
        <button type="button" onclick={() => { payDefault = bill.balance; showPayment = true; }}>Pay in full</button>
      </p>
    {/if}
  {/if}

  {#if bill.payments?.length}
    <h3>Payments</h3>
    <table><tbody>
      {#each bill.payments as p}
        <tr>
          <td>{p.method}</td><td>{p.reference}</td>
          <td>${Number(p.amount).toFixed(2)}</td>
          <td>{p.cleared_date ? `cleared ${p.cleared_date.slice(0,10)}` : 'pending'}</td>
          {#if $canManageFinancials}
            <td><button type="button" onclick={() => deletePayment(p.payment_id)}>Delete</button></td>
          {/if}
        </tr>
      {/each}
    </tbody></table>
  {/if}

  <LineItemModal
    open={modalOpen}
    mode={modalMode}
    apiBase={`/api/bills/${bill.bill_id}`}
    item={modalItem}
    {categories}
    onSaved={handleSaved}
    onClose={() => { modalOpen = false; }}
  />
  <RecordPaymentModal
    open={showPayment}
    billId={bill.bill_id}
    defaultAmount={payDefault}
    onSaved={() => { showPayment = false; load(); }}
    onClose={() => { showPayment = false; }}
  />
{/if}

<style>
  .error { color: #a8071a; }
  .metadata-table { border-collapse: collapse; margin-bottom: 16px; }
  .metadata-table td { padding: 4px 12px 4px 0; vertical-align: top; }
  .metadata-table td:first-child { white-space: nowrap; }
  h3 { margin-top: 24px; margin-bottom: 8px; }
</style>
