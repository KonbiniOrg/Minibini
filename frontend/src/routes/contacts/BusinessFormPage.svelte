<script>
  import { api } from '../../lib/api.js';
  import BusinessForm from '../../components/contacts/BusinessForm.svelte';
  import { canManageJobs } from '../../stores/permissions.js';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();
  const isEdit = $derived(!!params.id);

  let business = $state(null);
  let paymentTerms = $state([]);
  let loading = $state(true);
  let errors = $state(null);

  async function load() {
    loading = true;
    try {
      paymentTerms = await api.get('/api/payment-terms/');

      if (isEdit) {
        business = await api.get(`/api/businesses/${params.id}/`);
      }
    } catch (e) {
      errors = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleSubmit(data) {
    errors = null;
    try {
      if (isEdit) {
        await api.patch(`/api/businesses/${params.id}/`, data);
        push(`/businesses/${params.id}`);
      } else {
        const contactData = data._contact;
        delete data._contact;
        // Create the contact first
        const contact = await api.post('/api/contacts/', contactData);
        // Then create the business with default_contact_id
        data.default_contact_id = contact.contact_id;
        const created = await api.post('/api/businesses/', data);
        push(`/businesses/${created.business_id}`);
      }
    } catch (e) {
      errors = e.data ? JSON.stringify(e.data) : e.message;
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

<h2>{isEdit ? 'Edit Business' : 'New Business'}</h2>

{#if loading}
  <p>Loading...</p>
{:else if !$canManageJobs}
  <p>You do not have permission to manage businesses.</p>
{:else}
  <BusinessForm
    {business}
    {paymentTerms}
    {errors}
    onSubmit={handleSubmit}
    onCancel={handleCancel}
  />
{/if}
