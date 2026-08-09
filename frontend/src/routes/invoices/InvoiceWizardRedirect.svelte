<script>
  // Legacy /invoices/:id/wizard route. Reconcile is now a mode of the invoice
  // panel, not a route: remember 'edit' for this doc, then bounce to the
  // job-scoped invoice URL where the panel opens in edit mode.
  import { api } from '../../lib/api.js';
  import { rememberMode } from '../../stores/jobWorkspace.js';
  let { params = {} } = $props();
  $effect(() => {
    if (params.id) {
      api.get(`/api/invoices/${params.id}/`)
        .then((inv) => {
          rememberMode(inv.job, `inv:${inv.invoice_id}`, 'edit');
          window.location.replace(`#/jobs/${inv.job}/invoice/${inv.invoice_id}`);
        })
        .catch(() => { window.location.replace('#/jobs'); });
    }
  });
</script>
<p>Loading…</p>
