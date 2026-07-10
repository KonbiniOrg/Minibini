<script>
  import { api } from '../../lib/api.js';
  import JobShell from '../../components/jobs/JobShell.svelte';
  import ShipmentsPanel from '../../components/shipments/ShipmentsPanel.svelte';
  let { params = {} } = $props();
  let job = $state(null);
  let contact = $state(null);
  let error = $state('');
  async function loadJob() {
    try {
      job = await api.get(`/api/jobs/${params.jobId}/`);
      contact = job?.contact ? await api.get(`/api/contacts/${job.contact}/`).catch(() => null) : null;
    } catch (e) { error = e.message || 'Could not load job.'; }
  }
  $effect(() => { if (params.jobId) loadJob(); });
</script>

{#if error}<p class="error">{error}</p>
{:else if job}
  <JobShell {job} {contact} current="shipments" onJobChange={loadJob}>
    <ShipmentsPanel {job} onJobChange={loadJob} />
  </JobShell>
{:else}<p>Loading…</p>{/if}
