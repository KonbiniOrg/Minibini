<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { link } from 'svelte-spa-router';
  import { user as userStore } from '../../stores/auth.js';
  import ExpenseForm from '../expenses/ExpenseForm.svelte';
  import LoadState from '../LoadState.svelte';
  import DataTable from '../DataTable.svelte';

  let expenses = $state([]);
  let loading = $state(true);
  let showForm = $state(false);
  let loadError = $state('');

  async function load() {
    const uid = $userStore?.id;
    if (!uid) { loading = false; return; }
    loading = true;
    loadError = '';
    try {
      // Home card always scopes to the logged-in user, regardless of permissions.
      const data = await api.get(`/api/expenses/?purchased_by=${uid}&payment_method=personal&page_size=5`);
      expenses = data.results || data;
    } catch (err) {
      loadError = errorMessage(err, 'Could not load expenses.');
    } finally {
      loading = false;
    }
  }

  function onSaved(_exp) {
    showForm = false;
    load();
  }

  function statusLabel(s) {
    return {
      submitted: 'submitted',
      reimbursed: 'reimbursed',
      rejected: 'rejected',
    }[s] || s;
  }

  function syncBadge(qboSyncStatus) {
    if (qboSyncStatus === 'synced') return { text: 'synced', cls: 'synced-badge' };
    if (qboSyncStatus === 'sync_failed') return { text: 'sync failed', cls: 'sync-failed-badge' };
    return null;
  }

  load();
</script>

<section>
  <h3>My Expenses</h3>

  {#if !showForm}
    <p><button type="button" onclick={() => { showForm = true; }}>+ New expense</button></p>
  {/if}

  {#if showForm}
    <div style="border: 1px solid #ccc; padding: 10px; margin-bottom: 10px">
      <h4>Submit new expense</h4>
      <ExpenseForm
        lockPurchasedByToSelf={true}
        onSaved={onSaved}
        onCancel={() => { showForm = false; }}
      />
    </div>
  {/if}

  <LoadState {loading} error={loadError}>
  <DataTable
    rows={expenses}
    key={(e) => e.id}
    emptyText="No recent expenses."
    columns={[
      { id: 'date',        label: 'Date',        field: 'purchased_on' },
      { id: 'description', label: 'Description', cell: descriptionCell },
      { id: 'job',         label: 'Job',         cell: jobCell },
      { id: 'task',        label: 'Task',        cell: taskCell },
      { id: 'amount',      label: 'Amount',      cell: amountCell, align: 'right' },
      { id: 'status',      label: 'Status',      cell: statusCell },
      { id: 'reimbursed',  label: 'Reimbursed',  cell: reimbursedCell },
    ]}
  />
  </LoadState>
</section>


{#snippet descriptionCell(e)}<span class="preserve-breaks">{e.description || '—'}</span>{/snippet}
{#snippet jobCell(e)}
  {#if e.job_id}
    <a href="/jobs/{e.job_id}" use:link>{e.job_number}{e.job_name ? ' — ' + e.job_name : ''}</a>
  {:else}
    —
  {/if}
{/snippet}
{#snippet taskCell(e)}{e.task_name || '—'}{/snippet}
{#snippet amountCell(e)}${e.amount}{/snippet}
{#snippet statusCell(e)}
  <em>{statusLabel(e.status)}</em>
  {#if syncBadge(e.qbo_sync_status)}
    <span class={syncBadge(e.qbo_sync_status).cls}>{syncBadge(e.qbo_sync_status).text}</span>
  {/if}
{/snippet}
{#snippet reimbursedCell(e)}{e.reimbursement_paid_on || '—'}{/snippet}

<style>
  .synced-badge { font-size: 11px; color: #047857; font-weight: 600; }
  .sync-failed-badge { font-size: 11px; color: #b91c1c; font-weight: 600; }
</style>
