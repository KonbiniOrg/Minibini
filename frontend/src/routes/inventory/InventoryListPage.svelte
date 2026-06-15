<script>
  import { api } from '../../lib/api.js';
  import { canManageFinancials, canManageConfig } from '../../stores/permissions.js';

  // Write access: either the money role or the admin role.
  let canManage = $derived($canManageFinancials || $canManageConfig);

  let items = $state([]);
  let loading = $state(true);
  let error = $state('');

  // Filters
  let search = $state('');
  let includeFinished = $state(false);
  let activeOnly = $state(true);

  async function load() {
    loading = true;
    error = '';
    try {
      const params = new URLSearchParams();
      params.set('page_size', '200');
      if (activeOnly) params.set('is_active', 'true');
      if (includeFinished) params.set('include_finished', 'true');
      const data = await api.get('/api/price-list-items/?' + params.toString());
      items = data.results || data;
    } catch (err) {
      error = err.message || 'Could not load inventory.';
    } finally {
      loading = false;
    }
  }

  // Client-side text filter over the loaded page.
  let shown = $derived(
    !search.trim()
      ? items
      : items.filter((it) => {
          const q = search.trim().toLowerCase();
          return (it.code || '').toLowerCase().includes(q)
            || (it.description || '').toLowerCase().includes(q);
        })
  );

  load();
</script>

<h2>Inventory</h2>

<fieldset style="margin-bottom: 10px">
  <legend>Filters</legend>
  <label>Search: <input type="search" bind:value={search} placeholder="code or description"></label>
  <label><input type="checkbox" bind:checked={activeOnly} onchange={load}> Active only</label>
  <label><input type="checkbox" bind:checked={includeFinished} onchange={load}> Show finished lots</label>
</fieldset>

{#if loading}
  <p><em>Loading...</em></p>
{:else if error}
  <p><em>{error}</em></p>
{:else if shown.length === 0}
  <p><em>No inventory items match.</em></p>
{:else}
  <table class="data-table" style="width: 100%">
    <thead>
      <tr>
        <th>Code</th>
        <th>Description</th>
        <th>Units</th>
        <th style="text-align: right">On hand</th>
        <th style="text-align: right">Earmarked</th>
        <th style="text-align: right">Available</th>
        <th>Kind</th>
        <th style="text-align: right">Cost</th>
        <th style="text-align: right">Sell</th>
      </tr>
    </thead>
    <tbody>
      {#each shown as it (it.price_list_item_id)}
        <tr class:finished={!it.is_catalog && Number(it.qty_on_hand) === 0 && Number(it.qty_earmarked) === 0}>
          <td>{it.code}</td>
          <td class="preserve-breaks">{it.description || '—'}</td>
          <td>{it.units}</td>
          <td style="text-align: right">{it.qty_on_hand}</td>
          <td style="text-align: right">{it.qty_earmarked}</td>
          <td style="text-align: right">{it.qty_available}</td>
          <td>{it.is_catalog ? 'catalog' : 'lot'}{!it.is_active ? ' · inactive' : ''}</td>
          <td style="text-align: right">${it.purchase_price}</td>
          <td style="text-align: right">${it.selling_price}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}

<style>
  .finished {
    color: #888;
    font-style: italic;
  }
</style>
