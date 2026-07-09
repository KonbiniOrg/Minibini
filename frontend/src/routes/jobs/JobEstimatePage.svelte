<script>
  import { api } from '../../lib/api.js';
  import JobShell from '../../components/jobs/JobShell.svelte';
  import EstimatePanel from '../../components/estimates/EstimatePanel.svelte';
  import { getJobWs, rememberSection } from '../../stores/jobWorkspace.js';

  let { params = {} } = $props();
  let job = $state(null);
  let contact = $state(null);
  let estimates = $state([]);
  let error = $state('');

  async function loadJob() {
    try {
      job = await api.get(`/api/jobs/${params.jobId}/`);
      contact = job?.contact ? await api.get(`/api/contacts/${job.contact}/`).catch(() => null) : null;
    } catch (e) { error = e.message || 'Could not load job.'; }
  }

  async function loadEstimates() {
    try {
      const resp = await api.get(`/api/estimates/?job=${params.jobId}`);
      estimates = (resp?.results || resp || []).slice().sort((a, b) => a.version - b.version);
    } catch (_) {
      estimates = [];
    }
  }

  $effect(() => {
    if (params.jobId) {
      loadJob();
      loadEstimates();
    }
  });

  // docId precedence: URL param → remembered → latest version.
  const docId = $derived.by(() => {
    if (params.docId) return String(params.docId);
    const remembered = getJobWs(params.jobId).sections.estimate;
    if (remembered && estimates.some((e) => String(e.estimate_id) === remembered)) return remembered;
    return estimates.length ? String(estimates[estimates.length - 1].estimate_id) : null;
  });

  // Whenever a document renders, remember it AND normalize the URL (replace, no reload):
  $effect(() => {
    if (docId && params.jobId) {
      rememberSection(params.jobId, 'estimate', docId);
      const want = `#/jobs/${params.jobId}/estimate/${docId}`;
      if (window.location.hash !== want) window.history.replaceState(null, '', want);
    }
  });
</script>

{#if error}<p class="error">{error}</p>
{:else if job}
  <JobShell {job} {contact} current="estimate" onJobChange={loadJob}>
    <EstimatePanel {job} estimateId={docId} onJobChange={loadJob} />
  </JobShell>
{:else}<p>Loading…</p>{/if}
