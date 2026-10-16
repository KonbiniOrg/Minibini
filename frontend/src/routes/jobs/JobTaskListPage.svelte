<script>
  import { api, errorMessage } from '../../lib/api.js';
  import JobShell from '../../components/jobs/JobShell.svelte';
  import TasksPanel from '../../components/tasks/TasksPanel.svelte';
  import LoadState from '../../components/LoadState.svelte';

  let { params = {} } = $props();

  const jobId = $derived(params.jobId ?? params.id);

  let job = $state(null);
  let contact = $state(null);
  let error = $state('');

  async function loadJob() {
    try {
      job = await api.get(`/api/jobs/${jobId}/`);
      contact = job?.contact ? await api.get(`/api/contacts/${job.contact}/`).catch(() => null) : null;
    } catch (e) {
      error = errorMessage(e, 'Could not load job.');
    }
  }

  $effect(() => { if (jobId) loadJob(); });
</script>

<LoadState loading={!job && !error} {error}>
{#if job}
  <JobShell {job} {contact} current="tasks" colorway="cw-tasks" onJobChange={loadJob}>
    <TasksPanel {job} onJobChange={loadJob} />
  </JobShell>
{/if}
</LoadState>

<style>
</style>
