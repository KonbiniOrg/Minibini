<script>
  // Task 11: Edit/Duplicate became header modals, so the old standalone
  // /jobs/:id/edit and /jobs/:id/duplicate pages are gone. Deep links to
  // either now land here and bounce straight to the job overview, where the
  // header's Edit / Duplicate… buttons cover the same actions as modals.
  let { params = {} } = $props();
  $effect(() => {
    if (params.id) window.location.replace(`#/jobs/${params.id}`);
  });
</script>
<p>Redirecting…</p>
