<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import FormMessage from '../../components/FormMessage.svelte';
  import { showError, showSuccess } from '../../stores/messages.js';
  import { canManageJobs } from '../../stores/permissions.js';
  import { canDeleteBusiness } from '../../lib/customerActivity.js';
  import BusinessDetail from '../../components/contacts/BusinessDetail.svelte';
  import BusinessFormModal from '../../components/contacts/BusinessFormModal.svelte';
  import CustomerHeader from '../../components/contacts/CustomerHeader.svelte';
  import JobCreateModal from '../../components/jobs/JobCreateModal.svelte';
  import Modal from '../../components/Modal.svelte';
  import { push } from 'svelte-spa-router';
  import LoadState from '../../components/LoadState.svelte';

  const { params = {} } = $props();

  let business = $state(null);
  let invoices = $state([]);
  let purchaseOrders = $state([]);
  let history = $state(null);
  let financials = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let editOpen = $state(false);
  // Contact id the New Job modal opens for (header → default contact; a
  // Contacts row → that contact). null = closed.
  let newJobFor = $state(null);
  // Two-phase delete: the first DELETE's impact payload opens the confirm modal.
  let deleteImpact = $state(null);
  let deleting = $state(false);
  let actionError = $state('');
  // Deactivating a business cascades to its contacts, so it alone confirms
  // (modal fed by the deactivate-impact endpoint). Reactivate is direct.
  let deactivateImpact = $state(null);
  let deactivating = $state(false);

  // The tables show everything (closed rows behind the show-N toggle), so
  // the lists are fetched whole; 100 is the documented ceiling.
  const asList = (r) => (r?.results ?? r ?? []);

  async function loadBusiness() {
    loading = true;
    loadError = null;
    try {
      business = await api.get(`/api/businesses/${params.id}/`);
      const [inv, pos, fin, hist] = await Promise.all([
        // status=all: the list endpoint defaults to the 'open' preset, which
        // would drop the paid rows behind "show N paid".
        api.get(`/api/invoices/?business=${params.id}&status=all&summary=true&page_size=100`),
        api.get(`/api/purchase-orders/?business=${params.id}&page_size=100`),
        api.get(`/api/businesses/${params.id}/financials/`),
        api.get(`/api/businesses/${params.id}/history/`),
      ]);
      invoices = asList(inv);
      purchaseOrders = asList(pos);
      financials = fin;
      history = hist;
    } catch (e) {
      loadError = errorMessage(e, 'Could not load business.');
    } finally {
      loading = false;
    }
  }

  async function handleAddNote(text) {
    try {
      await api.post(`/api/businesses/${params.id}/notes/`, { text });
      history = await api.get(`/api/businesses/${params.id}/history/`);
    } catch (e) {
      showError(errorMessage(e, 'Could not add note.'));
    }
  }

  // Reversible (pick the previous default again), so no confirm.
  async function handleSetDefault(contactId) {
    try {
      await api.patch(`/api/businesses/${params.id}/`, { default_contact_id: contactId });
      await loadBusiness();
    } catch (e) {
      showError(errorMessage(e, 'Could not change the default contact.'));
    }
  }

  async function requestDeactivate() {
    actionError = '';
    try {
      const impact = await api.get(`/api/businesses/${params.id}/deactivate-impact/`);
      if (impact.blockers?.length) {
        actionError = `Cannot deactivate ${business.business_name}: ${impact.blockers.join('; ')}.`;
        return;
      }
      deactivateImpact = impact;
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) showError(t.overlay); else actionError = t.message;
    }
  }

  async function confirmDeactivate() {
    deactivating = true;
    try {
      await api.post(`/api/businesses/${params.id}/deactivate/`, {});
      deactivateImpact = null;
      await loadBusiness();
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) showError(t.overlay); else actionError = t.message;
      deactivateImpact = null;
    } finally {
      deactivating = false;
    }
  }

  async function reactivate() {
    actionError = '';
    try {
      await api.post(`/api/businesses/${params.id}/reactivate/`, {});
      await loadBusiness();
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) showError(t.overlay); else actionError = t.message;
    }
  }

  async function requestDelete() {
    try {
      const result = await api.delete(`/api/businesses/${params.id}/`);
      if (result && result.confirm_required) {
        deleteImpact = result.impact || {};
      } else {
        showSuccess(result?.message || 'Business deleted.');
        push('/contacts');
      }
    } catch (e) {
      showError(errorMessage(e, 'Could not delete business.'));
    }
  }

  async function confirmDelete() {
    deleting = true;
    try {
      const result = await api.delete(`/api/businesses/${params.id}/?confirm=true`);
      deleteImpact = null;
      showSuccess(result.message || 'Business deleted.');
      push('/contacts');
    } catch (e) {
      showError(errorMessage(e, 'Could not delete business.'));
    } finally {
      deleting = false;
    }
  }

  let active = $derived(business?.is_active !== false);
  let canDelete = $derived(business
    ? canDeleteBusiness({ jobs: business.jobs, poCount: purchaseOrders.length, contacts: business.contacts })
    : false);

  $effect(() => {
    void params.id;
    loadBusiness();
  });
</script>

<LoadState {loading} error={loadError}>
{#if business}
  <CustomerHeader
    name={business.business_name}
    defaultContact={business.default_contact}
    contactCount={business.contacts?.length ?? null}
    terms={business.terms_name}
    inactive={!active}
    {financials}
  >
    {#snippet actions()}
      {#if $canManageJobs}
        {#if active}
          {#if business.default_contact}
            <button type="button" class="banner-btn" onclick={() => { newJobFor = business.default_contact.contact_id; }}>New Job</button>
          {/if}
          <button type="button" class="edit-link header-action" onclick={() => { editOpen = true; }}>Edit</button>
          <button type="button" class="edit-link header-action" onclick={requestDeactivate}>Deactivate</button>
        {:else}
          <button type="button" class="edit-link header-action" onclick={reactivate}>Reactivate</button>
        {/if}
        {#if canDelete}
          <button type="button" class="edit-link header-action danger" onclick={requestDelete}>Delete…</button>
        {/if}
        <FormMessage error={actionError} />
      {/if}
    {/snippet}
  </CustomerHeader>

  <BusinessDetail
    {business}
    {invoices}
    {purchaseOrders}
    {history}
    onAddNote={handleAddNote}
    onSetDefault={handleSetDefault}
    onNewJobFor={(id) => { newJobFor = id; }}
    readonly={!active}
  />

  <BusinessFormModal
    open={editOpen}
    {business}
    onSaved={() => { editOpen = false; loadBusiness(); }}
    onClose={() => { editOpen = false; }}
  />
  <JobCreateModal open={newJobFor != null} defaultContactId={newJobFor} onClose={() => { newJobFor = null; }} />

  <Modal open={deactivateImpact != null} onSave={confirmDeactivate} onCancel={() => { deactivateImpact = null; }}
    busy={deactivating} maxWidth="480px" label="Deactivate business">
    <h3>Deactivate {business.business_name}?</h3>
    <p>This will deactivate <strong>{business.business_name}</strong> and its {deactivateImpact?.contact_count} contact(s)
      ({deactivateImpact?.contact_names?.join(', ')}). They will be hidden from choosers and any records on them frozen until reactivated. Continue?</p>
    <div class="modal-actions">
      <button type="button" onclick={() => { deactivateImpact = null; }} disabled={deactivating}>Cancel</button>
      <button type="button" onclick={confirmDeactivate} disabled={deactivating}>{deactivating ? 'Deactivating…' : 'Continue'}</button>
    </div>
  </Modal>

  <Modal open={deleteImpact != null} onSave={confirmDelete} onCancel={() => { deleteImpact = null; }}
    busy={deleting} maxWidth="480px" label="Delete business">
    <h3>Delete {business.business_name}?</h3>
    <p>This cannot be undone. Deleting the business also removes everything attached to it:</p>
    <ul class="impact">
      <li>{deleteImpact?.contacts ?? 0} contact(s)</li>
      <li>{deleteImpact?.jobs ?? 0} job(s)</li>
      <li>{deleteImpact?.purchase_orders ?? 0} purchase order(s)</li>
    </ul>
    <div class="modal-actions">
      <button type="button" onclick={() => { deleteImpact = null; }} disabled={deleting}>Cancel</button>
      <button type="button" class="danger" onclick={confirmDelete} disabled={deleting}>{deleting ? 'Deleting…' : 'Delete business'}</button>
    </div>
  </Modal>
{/if}
</LoadState>

<style>
  .impact { margin: 8px 0 14px; padding: 10px 12px 10px 28px; background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; font-size: 13px; color: #7f1d1d; }
  .modal-actions { display: flex; gap: 8px; justify-content: flex-end; }
  .modal-actions .danger { background: #b91c1c; border-color: #b91c1c; color: #fff; font-weight: 600; }
</style>
