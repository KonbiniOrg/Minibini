<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { showError, showSuccess } from '../../stores/messages.js';
  import { canManageJobs } from '../../stores/permissions.js';
  import { canDeleteContact } from '../../lib/customerActivity.js';
  import ContactDetail from '../../components/contacts/ContactDetail.svelte';
  import ContactFormModal from '../../components/contacts/ContactFormModal.svelte';
  import CustomerHeader from '../../components/contacts/CustomerHeader.svelte';
  import JobCreateModal from '../../components/jobs/JobCreateModal.svelte';
  import Modal from '../../components/Modal.svelte';
  import { push } from 'svelte-spa-router';
  import LoadState from '../../components/LoadState.svelte';

  const { params = {} } = $props();

  let contact = $state(null);
  // The contact's business DETAIL payload (contacts[] + jobs[]) for the
  // "Also here" list; null for individuals.
  let business = $state(null);
  let invoices = $state([]);
  let purchaseOrders = $state([]);
  let history = $state(null);
  let financials = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let editOpen = $state(false);
  let newJobOpen = $state(false);
  let deleteImpact = $state(null);
  let deleting = $state(false);

  const asList = (r) => (r?.results ?? r ?? []);

  async function loadContact() {
    loading = true;
    loadError = null;
    try {
      contact = await api.get(`/api/contacts/${params.id}/`);
      const [biz, inv, pos, fin, hist] = await Promise.all([
        contact.business ? api.get(`/api/businesses/${contact.business.business_id}/`) : Promise.resolve(null),
        // status=all: the list endpoint defaults to the 'open' preset, which
        // would drop the paid rows behind "show N paid".
        api.get(`/api/invoices/?contact=${params.id}&status=all&summary=true&page_size=100`),
        api.get(`/api/purchase-orders/?contact=${params.id}&page_size=100`),
        api.get(`/api/contacts/${params.id}/financials/`),
        api.get(`/api/contacts/${params.id}/history/`),
      ]);
      business = biz;
      invoices = asList(inv);
      purchaseOrders = asList(pos);
      financials = fin;
      history = hist;
    } catch (e) {
      loadError = errorMessage(e, 'Could not load contact.');
    } finally {
      loading = false;
    }
  }

  async function handleAddNote(text) {
    try {
      await api.post(`/api/contacts/${params.id}/notes/`, { text });
      history = await api.get(`/api/contacts/${params.id}/history/`);
    } catch (e) {
      showError(errorMessage(e, 'Could not add note.'));
    }
  }

  async function requestDelete() {
    try {
      const result = await api.delete(`/api/contacts/${params.id}/`);
      if (result && result.confirm_required) {
        deleteImpact = result.impact || {};
      } else {
        showSuccess(result?.message || 'Contact deleted.');
        push('/contacts');
      }
    } catch (e) {
      showError(errorMessage(e, 'Could not delete contact.'));
    }
  }

  async function confirmDelete() {
    deleting = true;
    try {
      const result = await api.delete(`/api/contacts/${params.id}/?confirm=true`);
      deleteImpact = null;
      showSuccess(result.message || 'Contact deleted.');
      push('/contacts');
    } catch (e) {
      showError(errorMessage(e, 'Could not delete contact.'));
    } finally {
      deleting = false;
    }
  }

  let isDefaultContact = $derived(
    !!contact?.business && contact.business.default_contact?.contact_id === contact.contact_id
  );
  let canDelete = $derived(contact
    ? canDeleteContact({
        jobs: contact.jobs,
        hasBusiness: !!contact.business,
        siblingCount: business?.contacts ? business.contacts.length - 1 : 0,
      })
    : false);

  $effect(() => {
    void params.id;
    loadContact();
  });
</script>

<LoadState {loading} error={loadError}>
{#if contact}
  <CustomerHeader
    name={contact.name}
    kind="contact"
    business={contact.business}
    {isDefaultContact}
    {financials}
  >
    {#snippet actions()}
      {#if $canManageJobs}
        <button type="button" class="banner-btn" onclick={() => { newJobOpen = true; }}>New Job</button>
        <button type="button" class="edit-link header-action" onclick={() => { editOpen = true; }}>Edit</button>
        {#if canDelete}
          <button type="button" class="edit-link header-action danger" onclick={requestDelete}>Delete…</button>
        {:else}
          <!-- Placeholder: the active flag + Reactivate path ship separately (external tracker). -->
          <button type="button" class="edit-link header-action danger" disabled title="Not available yet">Deactivate</button>
        {/if}
      {/if}
    {/snippet}
  </CustomerHeader>

  <ContactDetail
    {contact}
    {business}
    {invoices}
    {purchaseOrders}
    {history}
    onAddNote={handleAddNote}
  />

  <ContactFormModal
    open={editOpen}
    {contact}
    onSaved={() => { editOpen = false; loadContact(); }}
    onClose={() => { editOpen = false; }}
  />
  <JobCreateModal open={newJobOpen} defaultContactId={contact.contact_id} onClose={() => { newJobOpen = false; }} />

  <Modal open={deleteImpact != null} onSave={confirmDelete} onCancel={() => { deleteImpact = null; }}
    busy={deleting} maxWidth="480px" label="Delete contact">
    <h3>Delete {contact.name}?</h3>
    <p>This cannot be undone.</p>
    <ul class="impact">
      <li>{deleteImpact?.jobs ?? 0} job(s)</li>
    </ul>
    <div class="modal-actions">
      <button type="button" onclick={() => { deleteImpact = null; }} disabled={deleting}>Cancel</button>
      <button type="button" class="danger" onclick={confirmDelete} disabled={deleting}>{deleting ? 'Deleting…' : 'Delete contact'}</button>
    </div>
  </Modal>
{/if}
</LoadState>

<style>
  .impact { margin: 8px 0 14px; padding: 10px 12px 10px 28px; background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; font-size: 13px; color: #7f1d1d; }
  .modal-actions { display: flex; gap: 8px; justify-content: flex-end; }
  .modal-actions .danger { background: #b91c1c; border-color: #b91c1c; color: #fff; font-weight: 600; }
</style>
