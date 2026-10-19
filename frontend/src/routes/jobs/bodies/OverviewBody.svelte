<script>
  // Overview section body. Job + contact owned by JobWorkspace; this body owns
  // the overview aggregate (estimates, invoices, POs, change orders, shipments,
  // deliverables, overview) and the one-instant clock, then renders JobDetail
  // chromeless inside the workspace's shell. Ported from JobDetailPage (minus
  // the job + contact fetch, which the workspace now owns once per job).
  import { api, errorMessage } from '../../../lib/api.js';
  import JobDetail from '../../../components/jobs/JobDetail.svelte';
  import LoadState from '../../../components/LoadState.svelte';

  let { job, contact = null, onJobChange = () => {} } = $props();
  const jobId = $derived(job?.job_id);

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

  // `loading` is first-load only: a job-driven reload keeps the blocks on
  // screen until the new aggregates land (no placeholder flash).
  async function loadAggregate() {
    loadError = null;
    try {
      now = new Date();
      const [
        estimatesData, invoicesData, poData,
        changeOrderData, shipmentData, deliverableData, overviewData,
      ] = await Promise.all([
        api.get(`/api/estimates/?job=${jobId}`),
        api.get(`/api/invoices/?job=${jobId}`),
        api.get(`/api/purchase-orders/?job=${jobId}`),
        api.get(`/api/change-orders/?job=${jobId}`),
        api.get(`/api/shipments/?job=${jobId}`),
        api.get(`/api/jobs/${jobId}/deliverables/`),
        api.get(`/api/jobs/${jobId}/overview/`),
      ]);
      estimates = estimatesData;
      invoices = invoicesData;
      purchaseOrders = poData;
      changeOrders = changeOrderData;
      shipments = shipmentData;
      deliverableCount = (deliverableData?.results ?? deliverableData ?? []).length;
      overview = overviewData;
    } catch (e) {
      loadError = errorMessage(e, 'Could not load job.');
    } finally {
      loading = false;
    }
  }

  // Keyed on the job object's identity, not its id: onJobChange makes the
  // workspace refetch the job and hand back a new object, and the blocks'
  // aggregates must follow it (the props-down/callback-up refresh chain
  // every section panel uses; JobDetailPage.loadJob refetched these too).
  $effect(() => {
    if (job) loadAggregate();
  });
</script>

<LoadState {loading} error={loadError}>
  <JobDetail
    chromeless
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
    onStatusChange={onJobChange}
  />
</LoadState>
