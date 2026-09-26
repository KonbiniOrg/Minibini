<script>
  import { api } from '../../lib/api.js';
  import JobShell from '../../components/jobs/JobShell.svelte';
  import POPanel from '../../components/purchaseorders/POPanel.svelte';

  let { params = {} } = $props();
  const jobId = $derived(params.jobId);

  let job = $state(null);
  let contact = $state(null);
  let error = $state('');

  async function loadJob() {
    try {
      job = await api.get(`/api/jobs/${jobId}/`);
      contact = job?.contact ? await api.get(`/api/contacts/${job.contact}/`).catch(() => null) : null;
    } catch (e) { error = e.message || 'Could not load job.'; }
  }

  $effect(() => { if (jobId) loadJob(); });
</script>

{#if error}<p class="error">{error}</p>
{:else if job}
  <JobShell {job} {contact} current="pos" colorway="cw-neutral" onJobChange={loadJob}>
    <POPanel {job} />
  </JobShell>
{:else}<p>Loading…</p>{/if}

<style>
  .error { color: #a8071a; }
</style>
