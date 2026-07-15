<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import BusinessForm from '../../components/contacts/BusinessForm.svelte';
  import DuplicateContactModal from '../../components/contacts/DuplicateContactModal.svelte';
  import DuplicateBusinessModal from '../../components/contacts/DuplicateBusinessModal.svelte';
  import { canManageJobs } from '../../stores/permissions.js';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();
  const isEdit = $derived(!!params.id);

  let business = $state(null);
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

      if (isEdit) {
        business = await api.get(`/api/businesses/${params.id}/`);
      }
    } catch (e) {
      // Load failure has no form to land on — the global overlay is the venue.
      showError(errorMessage(e, 'Could not load.'));
    } finally {
      loading = false;
    }
  }

  async function handleSubmit(data) {
    formError = '';
    fieldErrs = {};
    duplicateContact = null;
    duplicateBusiness = null;
    try {
      if (isEdit) {
        await api.patch(`/api/businesses/${params.id}/`, data);
        push(`/businesses/${params.id}`);
      } else {
        // Check the business name for a conflict before creating anything —
        // otherwise a duplicate name fails only after the contact below has
        // already been committed, leaving it orphaned.
        const nameCheck = await api.get(`/api/businesses/check-name/?name=${encodeURIComponent(data.business_name)}`);
        if (nameCheck.exists) {
          duplicateBusiness = nameCheck.business;
          return;
        }

        const contactData = data._contact;
        delete data._contact;
        // Create the contact first. A field error from this call carries the
        // contact's payload keys (first_name, email, ...), which land on the
        // nested Default Contact inputs.
        const contact = await api.post('/api/contacts/', contactData);
        // Then create the business with default_contact_id
        data.default_contact_id = contact.contact_id;
        const created = await api.post('/api/businesses/', data);
        push(`/businesses/${created.business_id}`);
      }
    } catch (e) {
      if (!isEdit && e.status === 409 && e.data?.code === 'duplicate_email') {
        duplicateContact = e.data.existing_contact;
        return;
      }
      if (!isEdit && e.status === 409 && e.data?.code === 'duplicate_business_name') {
        duplicateBusiness = e.data.existing_business;
        return;
      }
      const t = triageError(e);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        formError = t.message;
        fieldErrs = t.fields;
      }
    }
  }

  function handleCancel() {
    if (isEdit) {
      push(`/businesses/${params.id}`);
    } else {
      push('/businesses');
    }
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

<div class="page-body">
<h2>{isEdit ? 'Edit Business' : 'New Business'}</h2>

{#if loading}
  <p>Loading...</p>
{:else if !$canManageJobs}
  <p>You do not have permission to manage businesses.</p>
{:else}
  <BusinessForm
    {business}
    {paymentTerms}
    errors={fieldErrs}
    {formError}
    onSubmit={handleSubmit}
    onCancel={handleCancel}
  />
  <DuplicateContactModal
    open={!!duplicateContact}
    contact={duplicateContact}
    onViewExisting={() => push(`/contacts/${duplicateContact.contact_id}`)}
    onClose={() => { duplicateContact = null; }}
  />
  <DuplicateBusinessModal
    open={!!duplicateBusiness}
    business={duplicateBusiness}
    onViewExisting={() => push(`/businesses/${duplicateBusiness.business_id}`)}
    onClose={() => { duplicateBusiness = null; }}
  />
{/if}
</div>
