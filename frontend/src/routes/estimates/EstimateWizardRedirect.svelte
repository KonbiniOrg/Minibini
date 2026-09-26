<script>
  // Legacy /estimates/:id/wizard route. Reconcile is now a mode of the estimate
  // panel, not a route: remember 'edit' for this doc, then bounce to the
  // job-scoped estimate URL where the panel opens in edit mode.
  import { api } from '../../lib/api.js';
  import { rememberMode } from '../../stores/jobWorkspace.js';
  let { params = {} } = $props();
  $effect(() => {
    if (params.id) {
      api.get(`/api/estimates/${params.id}/`)
        .then((est) => {
          rememberMode(est.job, `est:${est.estimate_id}`, 'edit');
          window.location.replace(`#/jobs/${est.job}/estimate/${est.estimate_id}`);
        })
        .catch(() => { window.location.replace('#/jobs'); });
    }
  });
</script>
<p>Loading…</p>
