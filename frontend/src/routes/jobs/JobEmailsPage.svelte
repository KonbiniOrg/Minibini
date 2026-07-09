<script>
  // v1 scope: hosts the existing EmailPanel full-width, no redesign of the
  // email surface itself. The page owns the /api/emails/?job= fetch — the
  // panel is a dumb renderer of whatever { results } it's handed.
  import { api } from '../../lib/api.js';
  import JobShell from '../../components/jobs/JobShell.svelte';
  import EmailPanel from '../../components/EmailPanel.svelte';

  let { params = {} } = $props();
  const jobId = $derived(params.jobId);

  let job = $state(null);
  let contact = $state(null);
  let emails = $state(null);
  let error = $state('');

  async function loadJob() {
    try {
      job = await api.get(`/api/jobs/${jobId}/`);
      contact = job?.contact ? await api.get(`/api/contacts/${job.contact}/`).catch(() => null) : null;
    } catch (e) { error = e.message || 'Could not load job.'; }
  }

  async function loadEmails() {
    try {
      emails = await api.get(`/api/emails/?job=${jobId}`);
    } catch (_) {
      emails = { results: [] };
    }
  }

  $effect(() => {
    if (jobId) {
      loadJob();
      loadEmails();
    }
  });
</script>

{#if error}<p class="error">{error}</p>
{:else if job}
  <JobShell {job} {contact} current="emails" onJobChange={loadJob}>
    <div class="page-body">
      <EmailPanel {emails} />
    </div>
  </JobShell>
{:else}<p>Loading…</p>{/if}

<style>
  .error { color: #a8071a; }
</style>
