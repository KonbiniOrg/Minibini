<script>
  import { api } from '$shared/lib/api.js';
  import BusinessDetail from '$shared/components/contacts/BusinessDetail.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();

  let business = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let error = $state(null);
  let success = $state(null);
  let deleteConfirm = $state(null);

  async function loadBusiness() {
    loading = true;
    loadError = null;
    try {
      business = await api.get(`/api/businesses/${params.id}/`);
    } catch (e) {
      loadError = e.message;
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

    deleteConfirm = null;
    try {
      const result = await api.delete(`/api/businesses/${params.id}/?confirm=true`);
      success = result.message || 'Business deleted.';
    } catch (e) {
      error = e.message;
    }
  }

  $effect(() => {
    void params.id;
    loadBusiness();
  });
</script>

{#if success}
  <div class="success-overlay">
    <div class="success-overlay-content">
      <button class="success-overlay-close" onclick={() => push('/businesses')}>&times;</button>
      <p>{success}</p>
    </div>
  </div>
{/if}

{#if error}
  <div class="error-overlay">
    <div class="error-overlay-content">
      <button class="error-overlay-close" onclick={() => { error = null; }}>&times;</button>
      <p><strong>Error:</strong> {error}</p>
    </div>
  </div>
{/if}

{#if loading}
  <p>Loading...</p>
{:else if loadError}
  <p>Error: {loadError}</p>
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
