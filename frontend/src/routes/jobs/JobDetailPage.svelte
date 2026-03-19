<script>
  import { api } from '../../lib/api.js';
  import JobDetail from '../../components/jobs/JobDetail.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();

  let job = $state(null);
  let contact = $state(null);
  let estimates = $state(null);
  let worksheets = $state(null);
  let workOrders = $state(null);
  let invoices = $state(null);
  let history = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let error = $state(null);

  async function loadJob() {
    loading = true;
    loadError = null;
    try {
      job = await api.get(`/api/jobs/${params.id}/`);
      const [contactData, estimatesData, worksheetsData, workOrdersData, invoicesData, historyData] = await Promise.all([
        api.get(`/api/contacts/${job.contact}/`),
        api.get(`/api/estimates/?job=${params.id}`),
        api.get(`/api/est-worksheets/?job=${params.id}`),
        api.get(`/api/work-orders/?job=${params.id}`),
        api.get(`/api/invoices/?job=${params.id}`),
        api.get(`/api/jobs/${params.id}/history/`),
      ]);
      contact = contactData;
      estimates = estimatesData;
      worksheets = worksheetsData;
      workOrders = workOrdersData;
      invoices = invoicesData;
      history = historyData;
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleAddNote(text) {
    try {
      await api.post(`/api/jobs/${params.id}/notes/`, { text });
      history = await api.get(`/api/jobs/${params.id}/history/`);
    } catch (e) {
      error = e.message;
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
  <h2>{job.job_number} - {job.name}</h2>
  <JobDetail
    {job}
    {contact}
    {estimates}
    {worksheets}
    {workOrders}
    {invoices}
    {history}
    onAddNote={handleAddNote}
  />

  <p><a href="#/jobs">Back to list</a></p>
{/if}
