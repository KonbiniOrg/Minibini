<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { formatSessionDateTime } from '../../lib/format.js';
  import { shiftActivityVersion } from '../../stores/shift.js';
  import { blepActivityVersion } from '../../stores/blepActivity.js';
  import LoadState from '../LoadState.svelte';
  import DataTable from '../DataTable.svelte';

  let rows = $state([]);
  let loading = $state(true);
  let error = $state(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const [sh, bl] = await Promise.all([
        api.get('/api/shift-change-requests/?mine=true'),
        api.get('/api/blep-change-requests/?mine=true'),
      ]);
      const tag = (list, kind) => (list.results || list).map(r => ({ ...r, kind }));
      rows = [...tag(sh, 'Shift'), ...tag(bl, 'Time')]
        .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    } catch (e) {
      error = errorMessage(e, 'Could not load change requests.');
    } finally { loading = false; }
  }
  $effect(() => { load(); });
  let lastS = $state(0), lastB = $state(0);
  $effect(() => { const v = $shiftActivityVersion; if (v !== lastS) { lastS = v; load(); } });
  $effect(() => { const v = $blepActivityVersion; if (v !== lastB) { lastB = v; load(); } });
</script>

<section>
  <h3>My Change Requests</h3>
  <LoadState {loading} {error}>
  <DataTable
    rows={rows}
    key={(r) => r.kind + r.request_id}
    emptyText="No change requests."
    columns={[
      { id: 'type',      label: 'Type',      field: 'kind' },
      { id: 'requested', label: 'Requested', cell: requestedCell },
      { id: 'status',    label: 'Status',    cell: statusCell },
      { id: 'reason',    label: 'Reason',    field: 'reason' },
    ]}
  />
  </LoadState>
</section>

{#snippet requestedCell(r)}{formatSessionDateTime(r.requested_start)} → {r.requested_end ? formatSessionDateTime(r.requested_end) : '—'}{/snippet}
{#snippet statusCell(r)}{r.status}{#if r.has_known_conflict && r.status === 'pending'} ⚠{/if}{/snippet}
