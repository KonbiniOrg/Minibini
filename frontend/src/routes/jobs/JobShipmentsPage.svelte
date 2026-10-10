<script>
  import { api, errorMessage } from '../../lib/api.js';
  import JobShell from '../../components/jobs/JobShell.svelte';
  import ShipmentsPanel from '../../components/shipments/ShipmentsPanel.svelte';
  import LoadState from '../../components/LoadState.svelte';
  let { params = {} } = $props();
  let job = $state(null);
  let contact = $state(null);
  let error = $state('');
  async function loadJob() {
    try {
      job = await api.get(`/api/jobs/${params.jobId}/`);
      contact = job?.contact ? await api.get(`/api/contacts/${job.contact}/`).catch(() => null) : null;
    } catch (e) { error = errorMessage(e, 'Could not load job.'); }
  }
  $effect(() => { if (params.jobId) loadJob(); });
</script>

<LoadState loading={!job && !error} {error}>
{#if job}
  <JobShell {job} {contact} current="shipments" colorway="cw-neutral" onJobChange={loadJob}>
    <ShipmentsPanel {job} onJobChange={loadJob} />
  </JobShell>
{/if}
</LoadState>
