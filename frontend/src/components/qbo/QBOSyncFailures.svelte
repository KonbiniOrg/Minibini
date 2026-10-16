<script>
  import { onMount } from 'svelte';
  import { api, errorMessage } from '../../lib/api.js';
  import LoadState from '../LoadState.svelte';
  import DataTable from '../DataTable.svelte';

  let failures = $state([]);
  let loading = $state(true);
  let loadError = $state('');
  let retryAllResult = $state('');
  let retryAllError = $state('');
  let rowErrors = $state({});

  async function load() {
    loading = true;
    loadError = '';
    try {
      const data = await api.get('/api/qbo/sync-failures/');
      failures = data.failures || [];
    } catch (err) {
      loadError = errorMessage(err, 'Could not load QBO sync failures.');
    } finally {
      loading = false;
    }
  }

  async function retryRow(failure) {
    rowErrors = { ...rowErrors, [failure.id + failure.entity_type]: '' };
    try {
      await api.post(failure.retry_url);
      await load();
    } catch (err) {
      rowErrors = {
        ...rowErrors,
        [failure.id + failure.entity_type]: errorMessage(err, 'Retry failed.'),
      };
    }
  }

  async function retryAll() {
    retryAllResult = '';
    retryAllError = '';
    try {
      const result = await api.post('/api/qbo/sync-failures/retry-all/');
      retryAllResult = `Retried ${result.retried}; still failing: ${result.still_failing}`;
      await load();
    } catch (err) {
      retryAllError = errorMessage(err, 'Retry all failed.');
    }
  }

  onMount(load);
</script>

<section class="qbo-sync-failures">
  <h3>QBO Sync Failures</h3>

  <LoadState {loading} error={loadError}>
  {#if failures.length === 0}
    <p>No QBO sync failures.</p>
  {:else}
    <p>
      <button type="button" onclick={retryAll}>Retry all</button>
      {#if retryAllResult}<em class="success">{retryAllResult}</em>{/if}
      {#if retryAllError}<em class="error">{retryAllError}</em>{/if}
    </p>
    <DataTable
      rows={failures}
      key={(failure) => failure.entity_type + '-' + failure.id}
      columns={[
        { id: 'entity',  label: 'Entity', cell: entityCell },
        { id: 'op',      label: 'Op',     cell: opCell },
        { id: 'amount',  label: 'Amount', cell: amountCell, align: 'right' },
        { id: 'actions', label: '',       cell: actionsCell },
      ]}
    />
  {/if}
  </LoadState>
</section>


{#snippet entityCell(failure)}<span title={failure.qbo_sync_error}>{failure.label}</span>{/snippet}
{#snippet opCell(failure)}<span class="op-badge">{failure.qbo_pending_op}</span>{/snippet}
{#snippet amountCell(failure)}${Number(failure.amount).toFixed(2)}{/snippet}
{#snippet actionsCell(failure)}
  <button type="button" class="retry-row" onclick={() => retryRow(failure)}>Retry</button>
  {#if rowErrors[failure.id + failure.entity_type]}
    <em class="error">{rowErrors[failure.id + failure.entity_type]}</em>
  {/if}
{/snippet}

<style>
  .qbo-sync-failures { margin-top: 1.5em; }
  .op-badge {
    display: inline-block;
    font-size: 0.75em;
    padding: 1px 6px;
    border-radius: 3px;
    background: #eee;
    border: 1px solid #ccc;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  .error { color: #a8071a; }
  .success { color: #237804; }
</style>
