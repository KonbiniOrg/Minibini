<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { canManageFinancials } from '../../stores/permissions.js';
  import CatalogTabs from '../../components/CatalogTabs.svelte';
  import StockOrderDialog from '../../components/inventory/StockOrderDialog.svelte';
  import { stockShortfall } from '../../lib/stockShortfall.js';

  let rows = $state([]);
  let loading = $state(true);
  let error = $state('');
  let orderRow = $state(null);

  // Client-side sort. Earmarks stay small (spec) — the API is unpaginated
  // and the browser owns ordering.
  let sortKey = $state('item_code');
  let sortDir = $state(1);
  const NUMERIC = new Set(['quantity', 'qty_on_hand', 'qty_on_order', 'shortfall']);

  function setSort(key) {
    if (sortKey === key) { sortDir = -sortDir; }
    else { sortKey = key; sortDir = 1; }
  }

  function sortValue(r, key) {
    if (key === 'shortfall') return Number(stockShortfall(r));
    if (NUMERIC.has(key)) return Number(r[key]);
    return String(r[key] ?? '').toLowerCase();
  }

  let sorted = $derived(
    [...rows].sort((a, b) => {
      const va = sortValue(a, sortKey), vb = sortValue(b, sortKey);
      return (va < vb ? -1 : va > vb ? 1 : 0) * sortDir;
    })
  );

  async function load() {
    loading = true;
    error = '';
    try {
      rows = await api.get('/api/earmarks/');
    } catch (e) {
      error = e.message || 'Could not load earmarks.';
    } finally {
      loading = false;
    }
  }

  load();
</script>

<div class="page-body">
<CatalogTabs />

{#if loading}
  <p><em>Loading...</em></p>
{:else if error}
  <p><em>{error}</em></p>
{:else if rows.length === 0}
  <p><em>No earmarks — nothing is committed right now.</em></p>
{:else}
  <table class="data-table" style="width: 100%">
    <thead>
      <tr>
        <th><button type="button" class="sort" onclick={() => setSort('item_code')}>Code</button></th>
        <th><button type="button" class="sort" onclick={() => setSort('item_description')}>Description</button></th>
        <th><button type="button" class="sort" onclick={() => setSort('units')}>Units</button></th>
        <th><button type="button" class="sort" onclick={() => setSort('job_number')}>Job</button></th>
        <th style="text-align: right"><button type="button" class="sort" onclick={() => setSort('quantity')}>Earmarked</button></th>
        <th style="text-align: right"><button type="button" class="sort" onclick={() => setSort('qty_on_hand')}>On hand</button></th>
        <th style="text-align: right"><button type="button" class="sort" onclick={() => setSort('qty_on_order')}>On order</button></th>
        <th style="text-align: right"><button type="button" class="sort" onclick={() => setSort('shortfall')}>Shortfall</button></th>
        <th>POs</th>
        {#if $canManageFinancials}<th></th>{/if}
      </tr>
    </thead>
    <tbody>
      {#each sorted as r (r.earmark_id)}
        <tr class:short={Number(stockShortfall(r)) > 0}>
          <td>{r.item_code}</td>
          <td class="preserve-breaks">{r.item_description || '—'}</td>
          <td>{r.units}</td>
          <td><a href={`/jobs/${r.job}`} use:link>{r.job_number}</a></td>
          <td style="text-align: right">{r.quantity}</td>
          <td style="text-align: right">{r.qty_on_hand}</td>
          <td style="text-align: right">{r.qty_on_order}</td>
          <td style="text-align: right">{stockShortfall(r)}</td>
          <td>
            {#if r.pos.length === 0}
              —
            {:else}
              {#each r.pos as po, i (po.po_id)}
                {#if i > 0},&nbsp;{/if}
                <a href={`/purchase-orders/${po.po_id}`} use:link>{po.po_number}</a>
              {/each}
            {/if}
          </td>
          {#if $canManageFinancials}
            <td><button type="button" onclick={() => orderRow = r}>order</button></td>
          {/if}
        </tr>
      {/each}
    </tbody>
  </table>
{/if}

{#if orderRow}
  <StockOrderDialog
    item={{ inventory_item_id: orderRow.inventory_item, code: orderRow.item_code }}
    prefillQty={stockShortfall(orderRow)}
    onDone={() => { orderRow = null; load(); }}
    onCancel={() => orderRow = null} />
{/if}
</div>

<style>
  .short td { background: #fff1f0; }
  th button.sort {
    background: none;
    border: none;
    padding: 0;
    font: inherit;
    font-weight: bold;
    cursor: pointer;
  }
</style>
