<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import ContactForm from '../../components/contacts/ContactForm.svelte';
  import { canManageJobs } from '../../stores/permissions.js';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();
  const isEdit = $derived(!!params.id);

  let contact = $state(null);
  let businesses = $state([]);
  let loading = $state(true);
  let formError = $state('');
  let fieldErrs = $state({});

  async function load() {
    loading = true;
    try {
      const bizData = await api.get('/api/businesses/?page_size=100');
      businesses = bizData.results;

      if (isEdit) {
        contact = await api.get(`/api/contacts/${params.id}/`);
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
    try {
      if (isEdit) {
        await api.patch(`/api/contacts/${params.id}/`, data);
        push(`/contacts/${params.id}`);
      } else {
        const created = await api.post('/api/contacts/', data);
        push(`/contacts/${created.contact_id}`);
      }
    } catch (e) {
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

<div class="page-body">
<h2>{isEdit ? 'Edit Contact' : 'New Contact'}</h2>

{#if loading}
  <p>Loading...</p>
{:else if !$canManageJobs}
  <p>You do not have permission to manage contacts.</p>
{:else}
  <ContactForm
    {contact}
    {businesses}
    errors={fieldErrs}
    {formError}
    onSubmit={handleSubmit}
    onCancel={handleCancel}
  />
{/if}
</div>
