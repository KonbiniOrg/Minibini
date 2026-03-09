<script>
  import { api } from '$shared/lib/api.js';
  import ContactForm from '$shared/components/contacts/ContactForm.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();
  const isEdit = $derived(!!params.id);

  let contact = $state(null);
  let businesses = $state([]);
  let loading = $state(true);
  let errors = $state(null);

  async function load() {
    loading = true;
    try {
      const bizData = await api.get('/api/businesses/?page_size=100');
      businesses = bizData.results;

      if (isEdit) {
        contact = await api.get(`/api/contacts/${params.id}/`);
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
        await api.patch(`/api/contacts/${params.id}/`, data);
        push(`/contacts/${params.id}`);
      } else {
        const created = await api.post('/api/contacts/', data);
        push(`/contacts/${created.contact_id}`);
      }
    } catch (e) {
      errors = e.data ? JSON.stringify(e.data) : e.message;
    }
  }

  function handleCancel() {
    if (isEdit) {
      push(`/contacts/${params.id}`);
    } else {
      push('/contacts');
    }
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

<h2>{isEdit ? 'Edit Contact' : 'New Contact'}</h2>

{#if loading}
  <p>Loading...</p>
{:else}
  <ContactForm
    {contact}
    {businesses}
    {errors}
    onSubmit={handleSubmit}
    onCancel={handleCancel}
  />
{/if}
