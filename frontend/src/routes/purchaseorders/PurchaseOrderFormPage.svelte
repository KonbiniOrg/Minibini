<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import PurchaseOrderForm from '../../components/purchaseorders/PurchaseOrderForm.svelte';
  import { push, querystring } from 'svelte-spa-router';
  import LoadState from '../../components/LoadState.svelte';

  const { params = {} } = $props();
  const isEdit = $derived(!!params.id);

  let po = $state(null);
  let businesses = $state([]);
  let loading = $state(true);
  let formError = $state('');
  let fieldErrs = $state({});

  // Context from query params (?business=…&contact=…).
  const initialParams = new URLSearchParams($querystring);
  const contextBusinessId = initialParams.get('business') ? Number(initialParams.get('business')) : null;
  const contextContactId = initialParams.get('contact') ? Number(initialParams.get('contact')) : null;

  async function load() {
    loading = true;
    try {
      const bizData = await api.get('/api/businesses/?page_size=100');
      businesses = bizData.results;

      if (isEdit) {
        po = await api.get(`/api/purchase-orders/${params.id}/`);
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
        push(`/purchase-orders/${created.po_id}`);
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

<div class="page-body">
<h2>{isEdit ? 'Edit Purchase Order' : 'New Purchase Order'}</h2>

<LoadState {loading}>
  <PurchaseOrderForm
    {po}
    {businesses}
    errors={fieldErrs}
    {formError}
    defaultBusinessId={contextBusinessId}
    defaultContactId={contextContactId}
    onSubmit={handleSubmit}
    onCancel={handleCancel}
  />
</LoadState>
</div>
