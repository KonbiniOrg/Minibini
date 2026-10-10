<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { link, push } from 'svelte-spa-router';
  import ExpenseForm from '../../components/expenses/ExpenseForm.svelte';
  import LoadState from '../../components/LoadState.svelte';
  import DataTable from '../../components/DataTable.svelte';

  let expenses = $state([]);
  let outstanding = $state([]);
  let loading = $state(true);
  let showForm = $state(false);
  let editingExpense = $state(null);
  let error = $state('');

  // Filter state
  let filterStatus = $state('');
  let filterQboSyncStatus = $state('');
  let filterPaymentMethod = $state('');
  let filterFrom = $state('');
  let filterTo = $state('');

  async function load() {
    loading = true;
    error = '';
    try {
      const params = new URLSearchParams();
      if (filterStatus) params.set('status', filterStatus);
      if (filterQboSyncStatus) params.set('qbo_sync_status', filterQboSyncStatus);
      if (filterPaymentMethod) params.set('payment_method', filterPaymentMethod);
      if (filterFrom) params.set('from', filterFrom);
      if (filterTo) params.set('to', filterTo);
      params.set('page_size', '50');

      const [list, summary] = await Promise.all([
        api.get('/api/expenses/?' + params.toString()),
        api.get('/api/reimbursements/outstanding-summary/'),
      ]);
      expenses = list.results || list;
      outstanding = summary.users || [];
    } catch (err) {
      error = errorMessage(err, 'Could not load.');
    } finally {
      loading = false;
    }
  }

  function onSaved() {
    showForm = false;
    editingExpense = null;
    load();
  }

  function editExpense(exp) {
    editingExpense = exp;
    showForm = true;
  }

  async function retryPush(exp) {
    try {
      await api.post(`/api/expenses/${exp.id}/retry-sync/`);
      load();
    } catch (err) {
      error = errorMessage(err, 'Retry failed.');
    }
  }

  async function rejectExpense(exp) {
    if (!confirm('Reject this expense? It will not be reimbursed.')) return;
    try {
      await api.post(`/api/expenses/${exp.id}/reject/`);
      load();
    } catch (err) {
      error = errorMessage(err, 'Reject failed.');
    }
  }

  async function deleteExpense(exp) {
    if (!confirm('Delete this expense? If synced, the QBO Purchase is voided.')) return;
    try {
      await api.delete(`/api/expenses/${exp.id}/`);
      load();
    } catch (err) {
      error = errorMessage(err, 'Delete failed.');
    }
  }

  load();
</script>

<div class="page-body">
<h2>Expenses</h2>

{#snippet invoicedLink(inv)}
  <a class="badge-invoiced" href={`#/invoices/${inv.id}`} use:link
     title="Billed on this invoice">INVOICED · {inv.number}</a>
{/snippet}

{#if outstanding.length > 0}
  <section style="border: 1px solid #4a90e2; padding: 10px; margin-bottom: 12px">
    <h3 style="margin-top: 0">Outstanding reimbursements</h3>
    <DataTable
      rows={outstanding}
      key={(row) => row.purchased_by}
      columns={[
        { id: 'who',    label: 'Who',             cell: whoCell },
        { id: 'items',  label: 'Items',           cell: itemsCell },
        { id: 'total',  label: 'Total',           cell: outstandingTotalCell, align: 'right' },
        { id: 'oldest', label: 'Oldest purchase', cell: oldestCell },
      ]}
    />
  </section>
{/if}

<p>
  {#if !showForm}
    <button type="button" onclick={() => { editingExpense = null; showForm = true; }}>
      + New expense
    </button>
  {/if}
</p>

{#if showForm}
  <div style="border: 1px solid #ccc; padding: 10px; margin-bottom: 10px">
    <h3>{editingExpense ? 'Edit expense' : 'New expense'}</h3>
    <ExpenseForm
      expense={editingExpense}
      onSaved={onSaved}
      onCancel={() => { showForm = false; editingExpense = null; }}
    />
  </div>
{/if}

<fieldset style="margin-bottom: 10px">
  <legend>Filters</legend>
  <label>Status:
    <select bind:value={filterStatus} onchange={load}>
      <option value="">(any)</option>
      <option value="submitted">submitted</option>
      <option value="reimbursed">reimbursed</option>
      <option value="rejected">rejected</option>
    </select>
  </label>
  <label>QBO sync:
    <select bind:value={filterQboSyncStatus} onchange={load}>
      <option value="">(any)</option>
      <option value="pending">pending</option>
      <option value="synced">synced</option>
      <option value="sync_failed">sync failed</option>
    </select>
  </label>
  <label>Payment:
    <select bind:value={filterPaymentMethod} onchange={load}>
      <option value="">(any)</option>
      <option value="company">company</option>
      <option value="personal">personal</option>
    </select>
  </label>
  <label>From: <input type="date" bind:value={filterFrom} onchange={load}></label>
  <label>To: <input type="date" bind:value={filterTo} onchange={load}></label>
</fieldset>

<LoadState {loading} {error}>
<DataTable
  rows={expenses}
  key={(e) => e.id}
  emptyText="No expenses match."
  columns={[
    { id: 'date',        label: 'Date',               field: 'purchased_on' },
    { id: 'who',         label: 'Who (purchased by)', cell: purchasedByCell },
    { id: 'description', label: 'Description',        cell: descriptionCell },
    { id: 'job',         label: 'Job',                cell: jobCell },
    { id: 'task',        label: 'Task',               cell: taskCell },
    { id: 'category',    label: 'Category',           cell: categoryCell },
    { id: 'amount',      label: 'Amount',             cell: amountCell, align: 'right' },
    { id: 'paid',        label: 'Paid',               field: 'payment_method' },
    { id: 'status',      label: 'Status',             cell: statusCell },
    { id: 'actions',     label: 'Actions',            cell: actionsCell },
  ]}
/>
</LoadState>
</div>


{#snippet whoCell(row)}<a href="/reimbursements/{row.purchased_by}" use:link>{row.full_name || row.username}</a>{/snippet}
{#snippet itemsCell(row)}{row.count} items{/snippet}
{#snippet outstandingTotalCell(row)}${row.total}{/snippet}
{#snippet oldestCell(row)}{row.oldest_purchased_on || '—'}{/snippet}

{#snippet purchasedByCell(e)}
  {#if e.purchased_by}
    <a href="/reimbursements/{e.purchased_by}" use:link>{e.purchased_by_name || '—'}</a>
  {:else}
    —
  {/if}
{/snippet}
{#snippet descriptionCell(e)}<span class="preserve-breaks">{e.description || '—'}</span>{/snippet}
{#snippet jobCell(e)}
  {#if e.job_id}
    <a href="/jobs/{e.job_id}" use:link>{e.job_number}{e.job_name ? ' — ' + e.job_name : ''}</a>
  {:else}
    —
  {/if}
{/snippet}
{#snippet taskCell(e)}{e.task_name || '—'}{/snippet}
{#snippet categoryCell(e)}{e.accounting_category_name || '—'}{/snippet}
{#snippet amountCell(e)}${e.amount}{/snippet}
{#snippet statusCell(e)}
  <em>{e.status}</em>
  {#if e.qbo_sync_status === 'sync_failed'}
    <span class="sync-failed-badge">sync failed</span>
    <button type="button" onclick={() => retryPush(e)}>retry</button>
  {:else if e.qbo_sync_status === 'synced'}
    <span class="synced-badge">synced</span>
  {/if}
  {#if e.invoice}<br>{@render invoicedLink(e.invoice)}{/if}
{/snippet}
{#snippet actionsCell(e)}
  {#if e.invoice}
    <span class="locked-note">billed — locked</span>
  {:else}
    <button type="button" onclick={() => editExpense(e)}>edit</button>
    {#if e.payment_method === 'personal' && e.status === 'submitted'}
      <button type="button" onclick={() => rejectExpense(e)}>reject</button>
    {/if}
    <button type="button" onclick={() => deleteExpense(e)}>delete</button>
  {/if}
{/snippet}

<style>
  /* .badge-invoiced comes from app.css. */
  .locked-note { font-size: 11px; color: #888; font-style: italic; }
  .synced-badge { font-size: 11px; color: #047857; font-weight: 600; }
  .sync-failed-badge { font-size: 11px; color: #b91c1c; font-weight: 600; }
</style>
