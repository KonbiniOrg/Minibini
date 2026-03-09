<script>
  import { api } from '$shared/lib/api.js';
  import BusinessDetail from '$shared/components/contacts/BusinessDetail.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();

  let business = $state(null);
  let loading = $state(true);
  let error = $state(null);
  let deleteConfirm = $state(null);

  async function loadBusiness() {
    loading = true;
    error = null;
    try {
      business = await api.get(`/api/businesses/${params.id}/`);
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleDelete() {
    if (!deleteConfirm) {
      try {
        const result = await api.delete(`/api/businesses/${params.id}/`);
        if (result && result.confirm_required) {
          deleteConfirm = result.impact;
        }
      } catch (e) {
        error = e.message;
      }
      return;
    }

    try {
      await api.delete(`/api/businesses/${params.id}/?confirm=true`);
      push('/businesses');
    } catch (e) {
      error = e.message;
    }
  }

  $effect(() => {
    void params.id;
    loadBusiness();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else if business}
  <h2>{business.business_name}</h2>
  <BusinessDetail
    {business}
    onEdit={() => push(`/businesses/${params.id}/edit`)}
    onDelete={handleDelete}
  />

  {#if deleteConfirm}
    <p>
      <strong>Are you sure?</strong> This business is associated with:
      {deleteConfirm.jobs} job(s),
      {deleteConfirm.purchase_orders} PO(s),
      {deleteConfirm.bills} bill(s),
      {deleteConfirm.contacts} contact(s).
      <button onclick={handleDelete}>Yes, delete</button>
      <button onclick={() => { deleteConfirm = null; }}>Cancel</button>
    </p>
  {/if}

  <p><a href="#/businesses">Back to list</a></p>
{/if}
