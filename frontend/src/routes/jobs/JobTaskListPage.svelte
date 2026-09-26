<script>
  import { api } from '../../lib/api.js';
  import JobShell from '../../components/jobs/JobShell.svelte';
  import TasksPanel from '../../components/tasks/TasksPanel.svelte';

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
      error = e.message || 'Could not load job.';
    }
  }

  $effect(() => { if (jobId) loadJob(); });
</script>

{#if error}<p class="error">{error}</p>
{:else if job}
  <JobShell {job} {contact} current="tasks" colorway="cw-tasks" onJobChange={loadJob}>
    <TasksPanel {job} onJobChange={loadJob} />
  </JobShell>
{:else}<p>Loading…</p>{/if}

<style>
  .error { color: #a8071a; }
</style>
