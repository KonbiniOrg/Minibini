<script>
  import { api } from '../../lib/api.js';
  let { params = {} } = $props();
  $effect(() => {
    if (params.id) {
      api.get(`/api/estimates/${params.id}/`)
        .then((est) => window.location.replace(`#/jobs/${est.job}/estimate/${est.estimate_id}`))
        .catch(() => { window.location.replace('#/jobs'); });
    }
  });
</script>
<p>Loading…</p>
