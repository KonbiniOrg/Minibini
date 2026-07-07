<script>
  import { api } from '../../lib/api.js';
  import JobDetail from '../../components/jobs/JobDetail.svelte';

  const { params = {} } = $props();

  let job = $state(null);
  let contact = $state(null);
  let estimates = $state(null);
  let invoices = $state(null);
  let purchaseOrders = $state(null);
  let emails = $state(null);
  let expenses = $state(null);
  let loading = $state(true);
  let loadError = $state(null);

  async function loadJob() {
    loading = true;
    loadError = null;
    try {
      job = await api.get(`/api/jobs/${params.id}/`);
      const [contactData, estimatesData, invoicesData, poData, emailData, expenseData] = await Promise.all([
        api.get(`/api/contacts/${job.contact}/`),
        api.get(`/api/estimates/?job=${params.id}`),
        api.get(`/api/invoices/?job=${params.id}`),
        api.get(`/api/purchase-orders/?job=${params.id}`),
        api.get(`/api/emails/?job=${params.id}`),
        api.get(`/api/expenses/?job=${params.id}`),
      ]);
      contact = contactData;
      estimates = estimatesData;
      invoices = invoicesData;
      purchaseOrders = poData;
      emails = emailData;
      expenses = expenseData;
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
    {emails}
    {expenses}
    onStatusChange={loadJob}
  />
{/if}
