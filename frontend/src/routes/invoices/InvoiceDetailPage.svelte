<script>
  import { api } from '../../lib/api.js';
  let { params = {} } = $props();
  $effect(() => {
    if (params.id) {
      api.get(`/api/invoices/${params.id}/`)
        .then((inv) => window.location.replace(`#/jobs/${inv.job}/invoice/${inv.invoice_id}`))
        .catch(() => { window.location.replace('#/jobs'); });
    }
  });
</script>
<p>Loading…</p>
