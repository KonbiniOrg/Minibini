<script>
  // Old top-level /change-orders/:id links now resolve the CO's job and redirect
  // into the job-scoped route, so change orders live inside the job workspace.
  import { push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';

  let { params = {} } = $props();

  $effect(() => {
    (async () => {
      try {
        const co = await api.get(`/api/change-orders/${params.id}/`);
        push(`/jobs/${co.job}/change-order/${co.change_order_id}`);
      } catch (_) {
        push('/');
      }
    })();
  });
</script>

<p>Loading…</p>
