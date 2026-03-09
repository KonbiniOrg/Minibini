<script>
  import { api } from '$shared/lib/api.js';
  import ContactDetail from '$shared/components/contacts/ContactDetail.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();

  let contact = $state(null);
  let loading = $state(true);
  let error = $state(null);
  let deleteConfirm = $state(null);

  async function loadContact() {
    loading = true;
    error = null;
    try {
      contact = await api.get(`/api/contacts/${params.id}/`);
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
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
        error = e.message;
      }
      return;
    }

    try {
      await api.delete(`/api/contacts/${params.id}/?confirm=true`);
      push('/contacts');
    } catch (e) {
      error = e.message;
    }
  }

  $effect(() => {
    loadContact();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else if contact}
  <h2>{contact.name}</h2>
  <ContactDetail
    {contact}
    onEdit={() => push(`/contacts/${params.id}/edit`)}
    onDelete={handleDelete}
  />

  {#if deleteConfirm}
    <p>
      <strong>Are you sure?</strong>
      This contact is associated with {deleteConfirm.jobs} job(s).
      <button onclick={handleDelete}>Yes, delete</button>
      <button onclick={() => { deleteConfirm = null; }}>Cancel</button>
    </p>
  {/if}

  <p><a href="#/contacts">Back to list</a></p>
{/if}
