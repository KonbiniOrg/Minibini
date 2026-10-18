<script>
  // Settings → QBO Log. Read-only, newest-first view of QBOSyncLog — every
  // push/update/void Minibini has sent to QuickBooks, success or failure —
  // for tracing "what did we send, and when" when QBO looks wrong. It is
  // NOT the retry surface; that is QBOSyncFailures on the Accounting tab.
  import { api, errorMessage } from '../../lib/api.js';
  import { pageRange } from '../../lib/pagination.js';
  import { formatSessionDateTime } from '../../lib/format.js';
  import LoadState from '../LoadState.svelte';
  import DataTable from '../DataTable.svelte';
  import Pager from '../Pager.svelte';

  // Entity types the log can carry; historical types stay selectable so old
  // rows remain traceable (docs/designs/quickbooks-integration.md §QBOSyncLog).
  const ENTITY_TYPES = [
    ['', 'All'],
    ['invoice', 'Invoice'],
    ['expense', 'Expense'],
    ['reimbursement', 'Reimbursement'],
    ['customer', 'Customer (business)'],
    ['contact_customer', 'Customer (contact)'],
    ['vendor', 'Vendor (historical)'],
    ['bill', 'Bill (historical)'],
    ['bill_payment', 'Bill payment (historical)'],
  ];

  let data = $state(null);
  let loading = $state(true);
  let error = $state('');
  let page = $state(1);
  let statusFilter = $state('');
  let entityFilter = $state('');

  async function load() {
    loading = true;
    error = '';
    try {
      const params = new URLSearchParams({ page: String(page) });
      if (statusFilter) params.set('status', statusFilter);
      if (entityFilter) params.set('entity_type', entityFilter);
      data = await api.get('/api/qbo/sync-log/?' + params.toString());
    } catch (err) {
      error = errorMessage(err, 'Could not load the QBO sync log.');
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    void page; void statusFilter; void entityFilter;
    load();
  });
</script>

<section class="qbo-sync-log">
  <h3>QBO Log</h3>
  <p class="hint">Every push Minibini has sent to QuickBooks, newest first. Failures that can be retried are on the Accounting tab.</p>

  <div class="filters">
    <label>Status
      <select bind:value={statusFilter} onchange={() => { page = 1; }}>
        <option value="">All</option>
        <option value="success">Success</option>
        <option value="failed">Failed</option>
      </select>
    </label>
    <label>Entity
      <select bind:value={entityFilter} onchange={() => { page = 1; }}>
        {#each ENTITY_TYPES as [value, label] (value)}
          <option {value}>{label}</option>
        {/each}
      </select>
    </label>
  </div>

  <LoadState {loading} {error}>
    <DataTable
      rows={data?.results ?? []}
      key={(row) => row.id}
      emptyText="No QBO sync activity yet."
      rowClass={(row) => row.status === 'failed' ? 'failed' : undefined}
      columns={[
        { id: 'when',   label: 'When',   cell: whenCell },
        { id: 'entity', label: 'Entity', cell: entityCell },
        { id: 'action', label: 'Action', field: 'action' },
        { id: 'status', label: 'Status', cell: statusCell },
        { id: 'qbo',    label: 'QBO',    cell: qboCell, lite: false },
        { id: 'by',     label: 'By',     cell: byCell, lite: false },
        { id: 'error',  label: 'Error',  cell: errorCell, phone: false },
      ]}
    />
    {#if data}
      <Pager {page} count={data.count} label={pageRange(data)} onPage={(n) => { page = n; }} />
    {/if}
  </LoadState>
</section>

{#snippet whenCell(row)}{formatSessionDateTime(row.synced_at)}{/snippet}
{#snippet entityCell(row)}{row.entity_type} #{row.entity_id}{/snippet}
{#snippet statusCell(row)}<span class="status-badge status-{row.status}">{row.status}</span>{/snippet}
{#snippet qboCell(row)}{row.qbo_entity_type}{row.qbo_entity_id ? ` ${row.qbo_entity_id}` : ''}{/snippet}
{#snippet byCell(row)}{row.triggered_by_name ?? '—'}{/snippet}
{#snippet errorCell(row)}{#if row.error_message}<span class="error-text">{row.error_message}</span>{/if}{/snippet}

<style>
  .hint { color: #555; margin-top: -0.5em; }
  .filters { display: flex; gap: 1.5em; flex-wrap: wrap; margin-bottom: 0.75em; }
  .filters label { display: inline-flex; gap: 0.4em; align-items: center; }
  .error-text { color: #a8071a; white-space: pre-wrap; word-break: break-word; }
</style>
