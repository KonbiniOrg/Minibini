<script>
  import { link, location } from 'svelte-spa-router';

  const tabs = [
    { path: '/catalog', label: 'Inventory' },
    { path: '/catalog/service-items', label: 'Service Items' },
    { path: '/catalog/earmarks', label: 'Earmarks' },
  ];
</script>

<h2>Catalog</h2>

<nav class="catalog-tabs">
  {#each tabs as t (t.path)}
    <a href={t.path} use:link class:active={$location === t.path}>{t.label}</a>
  {/each}
</nav>

<style>
  /* Same visual vocabulary as .settings-tabs, but real links (per-tab routes). */
  .catalog-tabs {
    display: flex;
    gap: 0;
    border-bottom: 2px solid #ccc;
    margin-bottom: 1em;
  }
  .catalog-tabs a {
    padding: 0.4em 1.2em;
    border: 2px solid #ccc;
    border-bottom: none;
    background: #f5f5f5;
    color: inherit;
    text-decoration: none;
    margin-bottom: -2px;
  }
  .catalog-tabs a.active {
    background: white;
    border-bottom: 2px solid white;
    font-weight: bold;
  }
</style>
