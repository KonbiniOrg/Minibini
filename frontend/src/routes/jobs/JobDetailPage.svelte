<script>
  import { api } from '../../lib/api.js';
  import JobDetail from '../../components/jobs/JobDetail.svelte';

  const { params = {} } = $props();

  let job = $state(null);
  let contact = $state(null);
  let estimates = $state(null);
  let invoices = $state(null);
  let purchaseOrders = $state(null);
  let changeOrders = $state(null);
  let shipments = $state(null);
  let deliverableCount = $state(0);
  let overview = $state(null);
  // The overview clock: one instant per load, threaded into every block (the
  // jobOverview lib is pure and never reads Date.now()).
  let now = $state(new Date());
  let loading = $state(true);
  let loadError = $state(null);

  async function loadJob() {
    loading = true;
    loadError = null;
    try {
      job = await api.get(`/api/jobs/${params.id}/`);
      now = new Date();
      const [
        contactData, estimatesData, invoicesData, poData,
        changeOrderData, shipmentData, deliverableData, overviewData,
      ] = await Promise.all([
        api.get(`/api/contacts/${job.contact}/`),
        api.get(`/api/estimates/?job=${params.id}`),
        api.get(`/api/invoices/?job=${params.id}`),
        api.get(`/api/purchase-orders/?job=${params.id}`),
        api.get(`/api/change-orders/?job=${params.id}`),
        api.get(`/api/shipments/?job=${params.id}`),
        api.get(`/api/jobs/${params.id}/deliverables/`),
        api.get(`/api/jobs/${params.id}/overview/`),
      ]);
      contact = contactData;
      estimates = estimatesData;
      invoices = invoicesData;
      purchaseOrders = poData;
      changeOrders = changeOrderData;
      shipments = shipmentData;
      deliverableCount = (deliverableData?.results ?? deliverableData ?? []).length;
      overview = overviewData;
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    void params.id;
    loadJob();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if loadError}
  <p><em>Error: {loadError}</em></p>
{:else if job}
  <JobDetail
    {job}
    {contact}
    {estimates}
    {invoices}
    {purchaseOrders}
    {changeOrders}
    {shipments}
    {deliverableCount}
    {overview}
    {now}
    onStatusChange={loadJob}
  />
{/if}
