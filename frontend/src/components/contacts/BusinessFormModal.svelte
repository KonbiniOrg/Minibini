<script>
  // Business create/edit in Modal (replaces routes/contacts/BusinessFormPage,
  // 2026-10-10). Create is the three-step dance from
  // contacts-and-businesses.md "Circular-dependency creation order":
  // check-name → create Contact → create Business with default_contact_id,
  // so a name collision never orphans a contact. Both duplicate prompts are
  // in-modal sub-states (form hidden, not unmounted; Escape backs out one
  // level before closing).
  import { push } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';
  import LoadState from '../LoadState.svelte';
  import BusinessForm from './BusinessForm.svelte';
  import DuplicateContactNotice from './DuplicateContactNotice.svelte';
  import DuplicateBusinessNotice from './DuplicateBusinessNotice.svelte';

  let {
    open = false,
    business = null,       // null → create; detail object → edit
    onSaved = () => {},    // edit only: (updatedBusiness)
    onClose = () => {},
  } = $props();

  const isEdit = $derived(!!business);

  let paymentTerms = $state([]);
  let loading = $state(true);
  let formError = $state('');
  let fieldErrs = $state({});
  let duplicateContact = $state(null);
  let duplicateBusiness = $state(null);

  async function load() {
    loading = true;
    try {
      paymentTerms = await api.get('/api/payment-terms/');
    } catch (e) {
      showError(errorMessage(e, 'Could not load payment terms.'));
      paymentTerms = [];
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (open) {
      formError = ''; fieldErrs = {}; duplicateContact = null; duplicateBusiness = null;
      load();
    }
  });

  async function handleSubmit(data) {
    formError = ''; fieldErrs = {}; duplicateContact = null; duplicateBusiness = null;
    try {
      if (isEdit) {
        const updated = await api.patch(`/api/businesses/${business.business_id}/`, data);
        onSaved(updated);
        return;
      }
      const nameCheck = await api.get(`/api/businesses/check-name/?name=${encodeURIComponent(data.business_name)}`);
      if (nameCheck.exists) { duplicateBusiness = nameCheck.business; return; }
      const contactData = data._contact;
      delete data._contact;
      // Contact first: a field error from this call carries the contact's
      // payload keys (first_name, email, ...), which land on the nested
      // Default Contact inputs.
      const contact = await api.post('/api/contacts/', contactData);
      data.default_contact_id = contact.contact_id;
      const created = await api.post('/api/businesses/', data);
      onClose();
      push(`/businesses/${created.business_id}`);
    } catch (e) {
      if (!isEdit && e.status === 409 && e.data?.code === 'duplicate_email') {
        duplicateContact = e.data.existing_contact; return;
      }
      if (!isEdit && e.status === 409 && e.data?.code === 'duplicate_business_name') {
        duplicateBusiness = e.data.existing_business; return;
      }
      const t = triageError(e);
      if (t.overlay) showError(t.overlay);
      else { formError = t.message; fieldErrs = t.fields; }
    }
  }

  const noticeShowing = $derived(!!duplicateContact || !!duplicateBusiness);

  function handleCancel() {
    if (noticeShowing) { duplicateContact = null; duplicateBusiness = null; }
    else onClose();
  }

  async function reactivateExisting() {
    const id = duplicateContact.contact_id;
    try {
      await api.post(`/api/contacts/${id}/reactivate/`, {});
      onClose();
      push(`/contacts/${id}`);
    } catch (e) {
      showError(errorMessage(e, 'Could not reactivate the contact.'));
    }
  }

  function go(path) { onClose(); push(path); }
</script>

<!-- Enter is owned by BusinessForm's native <form>; the shell only wires Escape. -->
<Modal {open} onCancel={handleCancel} maxWidth="680px" label={isEdit ? 'Edit business' : 'New business'}>
  <h3 class="modal-title">{isEdit ? 'Edit Business' : 'New Business'}</h3>

  {#if duplicateContact}
    <DuplicateContactNotice contact={duplicateContact}
      onViewExisting={() => go(`/contacts/${duplicateContact.contact_id}`)}
      onReactivate={reactivateExisting}
      onBack={() => { duplicateContact = null; }} />
  {:else if duplicateBusiness}
    <DuplicateBusinessNotice business={duplicateBusiness}
      onViewExisting={() => go(`/businesses/${duplicateBusiness.business_id}`)}
      onBack={() => { duplicateBusiness = null; }} />
  {/if}

  <!-- hidden, not {#if}: the form must survive the notice round-trip. -->
  <div hidden={noticeShowing}>
    <LoadState {loading}>
      <BusinessForm {business} {paymentTerms} errors={fieldErrs} {formError}
        onSubmit={handleSubmit} onCancel={onClose} />
    </LoadState>
  </div>
</Modal>

<style>
  .modal-title { margin: 0 0 12px; font-size: 16px; }
</style>
