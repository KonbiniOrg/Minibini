<script>
  import { link } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { canManageFinancials } from '../../stores/permissions.js';
  import CatalogTabs from '../../components/CatalogTabs.svelte';
  import StockOrderDialog from '../../components/inventory/StockOrderDialog.svelte';
  import { stockShortfall } from '../../lib/stockShortfall.js';
  import LoadState from '../../components/LoadState.svelte';
  import DataTable from '../../components/DataTable.svelte';

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
      error = errorMessage(e, 'Could not load earmarks.');
    } finally {
      loading = false;
    }
  }

  load();
</script>

<div class="page-body">
<CatalogTabs />

<LoadState {loading} {error}>
<DataTable
  rows={sorted}
  key={(r) => r.earmark_id}
  emptyText="No earmarks — nothing is committed right now."
  rowClass={(r) => (Number(stockShortfall(r)) > 0 ? 'short' : undefined)}
  columns={[
    { id: 'code',        label: 'Code',        field: 'item_code',    header: sortHeader, sortKey: 'item_code' },
    { id: 'description', label: 'Description', cell: descriptionCell, header: sortHeader, sortKey: 'item_description' },
    { id: 'units',       label: 'Units',       field: 'units',        header: sortHeader, sortKey: 'units' },
    { id: 'job',         label: 'Job',         cell: jobCell,         header: sortHeader, sortKey: 'job_number' },
    { id: 'earmarked',   label: 'Earmarked',   field: 'quantity',     header: sortHeader, sortKey: 'quantity',     align: 'right' },
    { id: 'onhand',      label: 'On hand',     field: 'qty_on_hand',  header: sortHeader, sortKey: 'qty_on_hand',  align: 'right' },
    { id: 'onorder',     label: 'On order',    field: 'qty_on_order', header: sortHeader, sortKey: 'qty_on_order', align: 'right' },
    { id: 'shortfall',   label: 'Shortfall',   cell: shortfallCell,   header: sortHeader, sortKey: 'shortfall',    align: 'right' },
    { id: 'pos',         label: 'POs',         cell: posCell },
    ...($canManageFinancials ? [{ id: 'actions', label: '', cell: actionsCell }] : []),
  ]}
/>
</LoadState>

{#if orderRow}
  <StockOrderDialog
    item={{ inventory_item_id: orderRow.inventory_item, code: orderRow.item_code }}
    prefillQty={stockShortfall(orderRow)}
    onDone={() => { orderRow = null; load(); }}
    onCancel={() => orderRow = null} />
{/if}
</div>


{#snippet sortHeader(col)}<button type="button" class="sort" onclick={() => setSort(col.sortKey)}>{col.label}</button>{/snippet}
{#snippet descriptionCell(r)}<span class="preserve-breaks">{r.item_description || '—'}</span>{/snippet}
{#snippet jobCell(r)}<a href={`/jobs/${r.job}`} use:link>{r.job_number}</a>{/snippet}
{#snippet shortfallCell(r)}{stockShortfall(r)}{/snippet}
{#snippet posCell(r)}
  {#if r.pos.length === 0}
    —
  {:else}
    {#each r.pos as po, i (po.po_id)}
      {#if i > 0},&nbsp;{/if}
      <a href={`/purchase-orders/${po.po_id}`} use:link>{po.po_number}</a>
    {/each}
  {/if}
{/snippet}
{#snippet actionsCell(r)}<button type="button" onclick={() => orderRow = r}>order</button>{/snippet}

<style>
  /* rows/headers come from DataTable (another component's scope) */
  :global(tr.short td) { background: #fff1f0; }
  :global(th) button.sort {
    background: none;
    border: none;
    padding: 0;
    font: inherit;
    font-weight: bold;
    cursor: pointer;
  }
</style>
