<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import PurchaseOrderForm from '../../components/purchaseorders/PurchaseOrderForm.svelte';
  import { push, querystring } from 'svelte-spa-router';

  const { params = {} } = $props();
  const isEdit = $derived(!!params.id);

  let po = $state(null);
  let businesses = $state([]);
  let loading = $state(true);
  let formError = $state('');
  let fieldErrs = $state({});

  // Context from query params (?job=…&material=…).
  const initialParams = new URLSearchParams($querystring);
  const contextJobId = initialParams.get('job');
  const contextMaterialId = initialParams.get('material');
  let contextJob = $state(null);
  let contextMaterial = $state(null);

  async function load() {
    loading = true;
    try {
      const bizData = await api.get('/api/businesses/?page_size=100');
      businesses = bizData.results;

      if (isEdit) {
        po = await api.get(`/api/purchase-orders/${params.id}/`);
      }

      if (contextJobId) {
        try {
          contextJob = await api.get(`/api/jobs/${contextJobId}/`);
        } catch {
          contextJob = null;
        }
      }
      if (contextMaterialId) {
        try {
          contextMaterial = await api.get(`/api/materials/${contextMaterialId}/`);
        } catch {
          contextMaterial = null;
        }
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
        await api.patch(`/api/purchase-orders/${params.id}/`, data);
        push(`/purchase-orders/${params.id}`);
      } else {
        const created = await api.post('/api/purchase-orders/', data);
        // Forward context onto the detail page so the line-item form prefills.
        const qs = [];
        if (contextMaterial?.material_id) {
          qs.push(`prefill_material=${contextMaterial.material_id}`);
        }
        if (contextJob?.job_id) {
          qs.push(`default_job=${contextJob.job_id}`);
        }
        const suffix = qs.length ? `?${qs.join('&')}` : '';
        push(`/purchase-orders/${created.po_id}${suffix}`);
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
    errors={fieldErrs}
    {formError}
    {contextJob}
    onSubmit={handleSubmit}
    onCancel={handleCancel}
  />
{/if}
