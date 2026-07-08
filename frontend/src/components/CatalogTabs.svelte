<script>
  import { link, location } from 'svelte-spa-router';

  const tabs = [
    { path: '/catalog', label: 'Inventory' },
    { path: '/catalog/service-items', label: 'Service Items' },
    { path: '/catalog/earmarks', label: 'Earmarks' },
  ];
</script>

<h2>Catalog</h2>

<nav class="page-tabs">
  {#each tabs as t (t.path)}
    <a href={t.path} use:link class:active={$location === t.path}>{t.label}</a>
  {/each}
</nav>

<!-- Tab strip is the shared .page-tabs (app.css) — real links, per-tab routes. -->

