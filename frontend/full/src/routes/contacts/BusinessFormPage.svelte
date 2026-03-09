<script>
  import { api } from '$shared/lib/api.js';
  import BusinessForm from '$shared/components/contacts/BusinessForm.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();
  const isEdit = $derived(!!params.id);

  let business = $state(null);
  let paymentTerms = $state([]);
  let contacts = $state([]);
  let loading = $state(true);
  let errors = $state(null);

  async function load() {
    loading = true;
    try {
      const [termsData, contactsData] = await Promise.all([
        api.get('/api/payment-terms/'),
        api.get('/api/contacts/?page_size=100'),
      ]);
      paymentTerms = termsData;
      contacts = contactsData.results;

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
    load();
  });
</script>

<h2>{isEdit ? 'Edit Business' : 'New Business'}</h2>

{#if loading}
  <p>Loading...</p>
{:else}
  <BusinessForm
    {business}
    {paymentTerms}
    {contacts}
    {errors}
    onSubmit={handleSubmit}
    onCancel={handleCancel}
  />
{/if}
