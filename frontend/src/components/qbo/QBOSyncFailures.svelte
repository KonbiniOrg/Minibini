<script>
  import { onMount } from 'svelte';
  import { api, errorMessage } from '../../lib/api.js';

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

  {#if loading}
    <p>Loading…</p>
  {:else if loadError}
    <p class="error">{loadError}</p>
  {:else if failures.length === 0}
    <p>No QBO sync failures.</p>
  {:else}
    <p>
      <button type="button" onclick={retryAll}>Retry all</button>
      {#if retryAllResult}<em class="success">{retryAllResult}</em>{/if}
      {#if retryAllError}<em class="error">{retryAllError}</em>{/if}
    </p>
    <table class="data-table">
      <thead>
        <tr>
          <th>Entity</th>
          <th>Op</th>
          <th class="text-right">Amount</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {#each failures as failure (failure.entity_type + '-' + failure.id)}
          {@const rowKey = failure.id + failure.entity_type}
          <tr>
            <td title={failure.qbo_sync_error}>{failure.label}</td>
            <td><span class="op-badge">{failure.qbo_pending_op}</span></td>
            <td class="text-right">${Number(failure.amount).toFixed(2)}</td>
            <td>
              <button type="button" class="retry-row" onclick={() => retryRow(failure)}>Retry</button>
              {#if rowErrors[rowKey]}
                <em class="error">{rowErrors[rowKey]}</em>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

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
