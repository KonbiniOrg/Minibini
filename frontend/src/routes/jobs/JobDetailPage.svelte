<script>
  import { api } from '../../lib/api.js';
  import JobDetail from '../../components/jobs/JobDetail.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();

  let job = $state(null);
  let contact = $state(null);
  let estimates = $state(null);
  let worksheets = $state(null);
  let invoices = $state(null);
  let purchaseOrders = $state(null);
  let emails = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let error = $state(null);

  async function loadJob() {
    loading = true;
    loadError = null;
    try {
      job = await api.get(`/api/jobs/${params.id}/`);
      const [contactData, estimatesData, worksheetsData, invoicesData, poData, emailData] = await Promise.all([
        api.get(`/api/contacts/${job.contact}/`),
        api.get(`/api/estimates/?job=${params.id}`),
        api.get(`/api/est-worksheets/?job=${params.id}`),
        api.get(`/api/invoices/?job=${params.id}`),
        api.get(`/api/purchase-orders/?job=${params.id}`),
        api.get(`/api/emails/?job=${params.id}`),
      ]);
      contact = contactData;
      estimates = estimatesData;
      worksheets = worksheetsData;
      invoices = invoicesData;
      purchaseOrders = poData;
      emails = emailData;
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function startWizard() {
    try {
      const { invoice_id } = await api.post(`/api/jobs/${job.job_id}/start-invoice-wizard/`);
      push(`/invoices/${invoice_id}/wizard`);
    } catch (e) {
      error = e.message || 'Failed to start wizard';
    }
  }

  $effect(() => {
    void params.id;
    loadJob();
  });
</script>

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
{:else if job}
  <JobDetail
    {job}
    {contact}
    {estimates}
    {worksheets}
    {invoices}
    {purchaseOrders}
    {emails}
    onStatusChange={loadJob}
    onStartWizard={startWizard}
  />
{/if}
