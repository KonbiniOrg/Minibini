<script>
  import { api } from '../../lib/api.js';
  import { link, push } from 'svelte-spa-router';
  import ExpenseForm from '../../components/expenses/ExpenseForm.svelte';

  let expenses = $state([]);
  let outstanding = $state([]);
  let loading = $state(true);
  let showForm = $state(false);
  let editingExpense = $state(null);
  let error = $state('');

  // Filter state
  let filterStatus = $state('');
  let filterPaymentMethod = $state('');
  let filterFrom = $state('');
  let filterTo = $state('');

  async function load() {
    loading = true;
    error = '';
    try {
      const params = new URLSearchParams();
      if (filterStatus) params.set('status', filterStatus);
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
      error = err.message || 'Could not load.';
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
      error = err.message || 'Retry failed.';
    }
  }

  async function rejectExpense(exp) {
    if (!confirm('Reject this expense? It will not be reimbursed.')) return;
    try {
      await api.post(`/api/expenses/${exp.id}/reject/`);
      load();
    } catch (err) {
      error = err.message || 'Reject failed.';
    }
  }

  async function deleteExpense(exp) {
    if (!confirm('Delete this expense? If synced, the QBO Purchase is voided.')) return;
    try {
      await api.delete(`/api/expenses/${exp.id}/`);
      load();
    } catch (err) {
      error = err.message || 'Delete failed.';
    }
  }

  load();
</script>

<h2>Expenses</h2>

{#snippet invoicedLink(inv)}
  <a class="badge-invoiced" href={`#/invoices/${inv.id}`} use:link
     title="Billed on this invoice">INVOICED · {inv.number}</a>
{/snippet}

{#if outstanding.length > 0}
  <section style="border: 1px solid #4a90e2; padding: 10px; margin-bottom: 12px">
    <h3 style="margin-top: 0">Outstanding reimbursements</h3>
    <table style="width: 100%">
      <tbody>
        {#each outstanding as row (row.purchased_by)}
          <tr>
            <td><a href="/reimbursements/{row.purchased_by}" use:link>{row.full_name || row.username}</a></td>
            <td>{row.count} items</td>
            <td style="text-align: right">${row.total}</td>
            <td>oldest: {row.oldest_purchased_on || '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
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

{#if loading}
  <p><em>Loading...</em></p>
{:else if error}
  <p><em>{error}</em></p>
{:else if expenses.length === 0}
  <p><em>No expenses match.</em></p>
{:else}
  <table class="data-table" style="width: 100%">
    <thead>
      <tr>
        <th>Date</th>
        <th>Who (purchased by)</th>
        <th>Description</th>
        <th>Job</th>
        <th>Task</th>
        <th>Category</th>
        <th style="text-align: right">Amount</th>
        <th>Paid</th>
        <th>Status</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>
      {#each expenses as e (e.id)}
        <tr>
          <td>{e.purchased_on}</td>
          <td>
            {#if e.purchased_by}
              <a href="/reimbursements/{e.purchased_by}" use:link>{e.purchased_by_name || '—'}</a>
            {:else}
              —
            {/if}
          </td>
          <td class="preserve-breaks">{e.description || '—'}</td>
          <td>
            {#if e.job_id}
              <a href="/jobs/{e.job_id}" use:link>{e.job_number}{e.job_name ? ' — ' + e.job_name : ''}</a>
            {:else}
              —
            {/if}
          </td>
          <td>{e.task_name || '—'}</td>
          <td>{e.accounting_category_name || '—'}</td>
          <td style="text-align: right">${e.amount}</td>
          <td>{e.payment_method}</td>
          <td>
            <em>{e.status}</em>
            {#if e.status === 'sync_failed'}
              <button type="button" onclick={() => retryPush(e)}>retry</button>
            {/if}
            {#if e.invoice}<br>{@render invoicedLink(e.invoice)}{/if}
          </td>
          <td>
            {#if e.invoice}
              <span class="locked-note">billed — locked</span>
            {:else}
              <button type="button" onclick={() => editExpense(e)}>edit</button>
              {#if e.payment_method === 'personal' && e.status === 'submitted'}
                <button type="button" onclick={() => rejectExpense(e)}>reject</button>
              {/if}
              <button type="button" onclick={() => deleteExpense(e)}>delete</button>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}

<style>
  .badge-invoiced {
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.3px; color: #047857; text-decoration: none;
  }
  .badge-invoiced:hover { text-decoration: underline; }
  .locked-note { font-size: 11px; color: #888; font-style: italic; }
</style>
