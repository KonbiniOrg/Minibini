<script>
  import { api } from '../../lib/api.js';
  import ContactDetail from '../../components/contacts/ContactDetail.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();

  let contact = $state(null);
  let invoices = $state(null);
  let purchaseOrders = $state(null);
  let bills = $state(null);
  let history = $state(null);
  let financials = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let error = $state(null);
  let success = $state(null);
  let deleteConfirm = $state(null);

  async function loadContact() {
    loading = true;
    loadError = null;
    try {
      contact = await api.get(`/api/contacts/${params.id}/`);
      await Promise.all([loadInvoices(1), loadPOs(1), loadBills(1), loadHistory(), loadFinancials()]);
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function loadInvoices(page) {
    invoices = await api.get(`/api/invoices/?contact=${params.id}&summary=true&page=${page}`);
  }

  async function loadPOs(page) {
    purchaseOrders = await api.get(`/api/purchase-orders/?contact=${params.id}&page=${page}`);
  }

  async function loadBills(page) {
    bills = await api.get(`/api/bills/?contact=${params.id}&page=${page}`);
  }

  async function loadFinancials() {
    financials = await api.get(`/api/contacts/${params.id}/financials/`);
  }

  async function loadHistory() {
    history = await api.get(`/api/contacts/${params.id}/history/`);
  }

  async function handleAddNote(text) {
    try {
      await api.post(`/api/contacts/${params.id}/notes/`, { text });
      await loadHistory();
    } catch (e) {
      error = e.message;
    }
  }

  async function handleDelete() {
    if (!deleteConfirm) {
      try {
        const result = await api.delete(`/api/contacts/${params.id}/`);
        if (result && result.confirm_required) {
          deleteConfirm = result.impact;
        }
      } catch (e) {
        error = e.message;
      }
      return;
    }

    deleteConfirm = null;
    try {
      const result = await api.delete(`/api/contacts/${params.id}/?confirm=true`);
      success = result.message || 'Contact deleted.';
    } catch (e) {
      error = e.message;
    }
  }

  $effect(() => {
    void params.id;
    loadContact();
  });
</script>

{#if success}
  <div class="success-overlay">
    <div class="success-overlay-content">
      <button class="success-overlay-close" onclick={() => push('/contacts')}>&times;</button>
      <p>{success}</p>
    </div>
  </div>
{/if}

{#if error}
  <div class="error-overlay">
    <div class="error-overlay-content">
      <button class="error-overlay-close" onclick={() => { error = null; }}>&times;</button>
      <p><strong>Error:</strong> {error}</p>
    </div>
  </div>
{/if}

{#if loading}
  <p>Loading...</p>
{:else if loadError}
  <p>Error: {loadError}</p>
{:else if contact}
  <ContactDetail
    {contact}
    {invoices}
    {purchaseOrders}
    {bills}
    {history}
    {financials}
    onEdit={() => push(`/contacts/${params.id}/edit`)}
    onDelete={handleDelete}
    onInvoicePageChange={loadInvoices}
    onPOPageChange={loadPOs}
    onBillPageChange={loadBills}
    onAddNote={handleAddNote}
  />

  {#if deleteConfirm}
    <p>
      <strong>Are you sure?</strong>
      This contact is associated with {deleteConfirm.jobs} job(s).
      <button onclick={handleDelete}>Yes, delete</button>
      <button onclick={() => { deleteConfirm = null; }}>Cancel</button>
    </p>
  {/if}

  <p><a href="#/contacts">Back to list</a></p>
{/if}
