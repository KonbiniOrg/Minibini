<script>
  // Thin host for the change-order document surface inside the job
  // workspace — same shape as JobEstimatePage/JobInvoicePage: load the job,
  // render JobShell, hand the document work to ChangeOrderPanel. No docId
  // resolution here: this route always carries :coId (the estimate section's
  // bare route handles "which document" defaulting).
  import { api } from '../../lib/api.js';
  import JobShell from '../../components/jobs/JobShell.svelte';
  import ChangeOrderPanel from '../../components/changeorders/ChangeOrderPanel.svelte';

  let { params = {} } = $props();
  let job = $state(null);
  let contact = $state(null);
  let error = $state('');

  // Value-keyed: svelte-spa-router hands this still-mounted component a new
  // `params` object on every subnav navigation, even when only :coId changed.
  // Deriving jobId memoizes on the value so the job only reloads when the job
  // actually changes; the panel re-keys itself on coId.
  const jobId = $derived(params.jobId);
  const coId = $derived(params.coId);

  async function loadJob() {
    try {
      job = await api.get(`/api/jobs/${jobId}/`);
      contact = job?.contact ? await api.get(`/api/contacts/${job.contact}/`).catch(() => null) : null;
    } catch (e) { error = e.message || 'Could not load job.'; }
  }

  $effect(() => {
    if (jobId) loadJob();
  });
</script>

{#if error}<p class="error">{error}</p>
{:else if job}
  <JobShell {job} {contact} current="estimate" colorway="cw-estimate" onJobChange={loadJob}>
    <ChangeOrderPanel {job} {coId} onJobChange={loadJob} />
  </JobShell>
{:else}<p>Loading…</p>{/if}
