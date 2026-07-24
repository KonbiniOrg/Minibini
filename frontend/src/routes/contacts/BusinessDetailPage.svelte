<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { showError, showSuccess } from '../../stores/messages.js';
  import BusinessDetail from '../../components/contacts/BusinessDetail.svelte';
  import CustomerHeader from '../../components/contacts/CustomerHeader.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();

  let business = $state(null);
  let invoices = $state(null);
  let purchaseOrders = $state(null);
  let history = $state(null);
  let financials = $state(null);
  let poPage = $state(1);
  let loading = $state(true);
  let loadError = $state(null);
  let deleteConfirm = $state(null);

  async function loadBusiness() {
    loading = true;
    loadError = null;
    try {
      business = await api.get(`/api/businesses/${params.id}/`);
      await Promise.all([loadInvoices(1), loadPOs(1), loadHistory(), loadFinancials()]);
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function loadInvoices(page) {
    invoices = await api.get(`/api/invoices/?business=${params.id}&summary=true&page=${page}`);
  }

  async function loadPOs(page) {
    poPage = page;
    purchaseOrders = await api.get(`/api/purchase-orders/?business=${params.id}&page=${page}`);
  }

  async function loadFinancials() {
    financials = await api.get(`/api/businesses/${params.id}/financials/`);
  }

  async function loadHistory() {
    history = await api.get(`/api/businesses/${params.id}/history/`);
  }

  async function handleAddNote(text) {
    try {
      await api.post(`/api/businesses/${params.id}/notes/`, { text });
      await loadHistory();
    } catch (e) {
      showError(errorMessage(e, 'Could not add note.'));
    }
  }

  async function handleDelete() {
    if (!deleteConfirm) {
      try {
        const result = await api.delete(`/api/businesses/${params.id}/`);
        if (result && result.confirm_required) {
          deleteConfirm = result.impact;
        }
      } catch (e) {
        showError(errorMessage(e, 'Could not delete business.'));
      }
      return;
    }

    deleteConfirm = null;
    try {
      const result = await api.delete(`/api/businesses/${params.id}/?confirm=true`);
      showSuccess(result.message || 'Business deleted.');
      push('/businesses');
    } catch (e) {
      showError(errorMessage(e, 'Could not delete business.'));
    }
  }

  $effect(() => {
    void params.id;
    loadBusiness();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if loadError}
  <p><em>Error: {loadError}</em></p>
{:else if business}
  <CustomerHeader name={business.business_name} defaultContact={business.default_contact} {financials} />
  <BusinessDetail
    {business}
    {invoices}
    {purchaseOrders}
    {history}
    onEdit={() => push(`/businesses/${params.id}/edit`)}
    onDelete={handleDelete}
    onInvoicePageChange={loadInvoices}
    onPOPageChange={loadPOs}
    onAddNote={handleAddNote}
  />

  <div class="page-body">
  {#if deleteConfirm}
    <p>
      <strong>Are you sure?</strong> This business is associated with:
      {deleteConfirm.jobs} job(s),
      {deleteConfirm.purchase_orders} PO(s),
      {deleteConfirm.bills} bill(s),
      {deleteConfirm.contacts} contact(s).
      <button onclick={handleDelete}>Yes, delete</button>
      <button onclick={() => { deleteConfirm = null; }}>Cancel</button>
    </p>
  {/if}

  <p><a href="#/businesses">Back to list</a></p>
  </div>
{/if}
