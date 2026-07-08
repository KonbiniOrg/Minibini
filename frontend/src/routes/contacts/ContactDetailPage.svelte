<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { showError, showSuccess } from '../../stores/messages.js';
  import ContactDetail from '../../components/contacts/ContactDetail.svelte';
  import CustomerHeader from '../../components/contacts/CustomerHeader.svelte';
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
      showError(errorMessage(e, 'Could not add note.'));
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
        showError(errorMessage(e, 'Could not delete contact.'));
      }
      return;
    }

    deleteConfirm = null;
    try {
      const result = await api.delete(`/api/contacts/${params.id}/?confirm=true`);
      showSuccess(result.message || 'Contact deleted.');
      push('/contacts');
    } catch (e) {
      showError(errorMessage(e, 'Could not delete contact.'));
    }
  }

  $effect(() => {
    void params.id;
    loadContact();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if loadError}
  <p><em>Error: {loadError}</em></p>
{:else if contact}
  <CustomerHeader name={contact.name} {financials} />
  <ContactDetail
    {contact}
    {invoices}
    {purchaseOrders}
    {bills}
    {history}
    onEdit={() => push(`/contacts/${params.id}/edit`)}
    onDelete={handleDelete}
    onInvoicePageChange={loadInvoices}
    onPOPageChange={loadPOs}
    onBillPageChange={loadBills}
    onAddNote={handleAddNote}
  />

  <div class="page-body">
  {#if deleteConfirm}
    <p>
      <strong>Are you sure?</strong>
      This contact is associated with {deleteConfirm.jobs} job(s).
      <button onclick={handleDelete}>Yes, delete</button>
      <button onclick={() => { deleteConfirm = null; }}>Cancel</button>
    </p>
  {/if}

  <p><a href="#/contacts">Back to list</a></p>
  </div>
{/if}
