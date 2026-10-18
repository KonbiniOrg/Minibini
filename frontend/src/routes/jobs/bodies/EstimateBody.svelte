<script>
  // Estimate section body. Job owned by JobWorkspace. Ported from
  // JobEstimatePage: owns the estimates list + docId precedence (URL param →
  // remembered → latest version) and URL normalization. (Was JobEstimatePage.)
  import { api } from '../../../lib/api.js';
  import EstimatePanel from '../../../components/estimates/EstimatePanel.svelte';
  import { getJobWs, rememberSection } from '../../../stores/jobWorkspace.js';

  let { job, params = {}, onJobChange = () => {} } = $props();

  const jobId = $derived(String(params.jobId ?? job?.job_id));
  let estimates = $state([]);

  async function loadEstimates() {
    try {
      const resp = await api.get(`/api/estimates/?job=${jobId}`);
      estimates = (resp?.results || resp || []).slice().sort((a, b) => a.version - b.version);
    } catch (_) {
      estimates = [];
    }
  }

  // Follows the viewed document too (a new version is created-then-navigated-to).
  $effect(() => { void params.docId; if (jobId) loadEstimates(); });

  // docId precedence: URL param → remembered → latest version.
  const docId = $derived.by(() => {
    if (params.docId) return String(params.docId);
    const remembered = getJobWs(jobId).sections.estimate;
    if (remembered && estimates.some((e) => String(e.estimate_id) === remembered)) return remembered;
    return estimates.length ? String(estimates[estimates.length - 1].estimate_id) : null;
  });

  // Whenever a document renders, remember it AND normalize the URL (replace, no reload):
  $effect(() => {
    if (docId && jobId) {
      rememberSection(jobId, 'estimate', docId);
      const want = `#/jobs/${jobId}/estimate/${docId}`;
      if (window.location.hash !== want) window.history.replaceState(null, '', want);
    }
  });
</script>

<EstimatePanel {job} estimateId={docId} {onJobChange} />
