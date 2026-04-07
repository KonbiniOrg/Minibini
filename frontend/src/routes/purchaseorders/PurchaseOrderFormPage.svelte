<script>
  import { api } from '../../lib/api.js';
  import PurchaseOrderForm from '../../components/purchaseorders/PurchaseOrderForm.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();
  const isEdit = $derived(!!params.id);

  let po = $state(null);
  let businesses = $state([]);
  let loading = $state(true);
  let errors = $state(null);

  async function load() {
    loading = true;
    try {
      const bizData = await api.get('/api/businesses/?page_size=100');
      businesses = bizData.results;

      if (isEdit) {
        po = await api.get(`/api/purchase-orders/${params.id}/`);
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
        await api.patch(`/api/purchase-orders/${params.id}/`, data);
        push(`/purchase-orders/${params.id}`);
      } else {
        const created = await api.post('/api/purchase-orders/', data);
        push(`/purchase-orders/${created.po_id}`);
      }
    } catch (e) {
      errors = e.data ? JSON.stringify(e.data) : e.message;
    }
  }

  function handleCancel() {
    if (isEdit) {
      push(`/purchase-orders/${params.id}`);
    } else {
      push('/purchase-orders');
    }
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

<h2>{isEdit ? 'Edit Purchase Order' : 'New Purchase Order'}</h2>

{#if loading}
  <p>Loading...</p>
{:else}
  <PurchaseOrderForm
    {po}
    {businesses}
    {errors}
    onSubmit={handleSubmit}
    onCancel={handleCancel}
  />
{/if}
