<script>
  // Route stub for pages that became modals (contact/business/job/user
  // create, email create-job/link, document send). A stale bookmark or
  // deep link lands here and bounces to the host page, where the button
  // that opens the modal lives. Mirrors routes/jobs/JobRedirectToOverview.
  //
  // `to` is a hash path; `:name` segments are filled from the route params
  // (svelte-spa-router passes `params` alongside wrap()'s `props`).
  let { params = {}, to = '/' } = $props();

  $effect(() => {
    const target = to.replace(/:([A-Za-z]+)/g, (_, key) => params?.[key] ?? '');
    window.location.replace(`#${target}`);
  });
</script>

<p>Redirecting…</p>
