<script>
  import { api } from '../../lib/api.js';
  import { link } from 'svelte-spa-router';
  import { user as userStore } from '../../stores/auth.js';
  import ExpenseForm from '../expenses/ExpenseForm.svelte';

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
      const data = await api.get(`/api/expenses/?purchased_by=${uid}&page_size=5`);
      expenses = data.results || data;
    } catch (err) {
      loadError = err.message || 'Could not load expenses.';
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
      synced: 'synced',
      sync_failed: 'sync failed',
    }[s] || s;
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

  {#if loading}
    <p><em>Loading...</em></p>
  {:else if loadError}
    <p><em>{loadError}</em></p>
  {:else if expenses.length === 0}
    <p><em>No recent expenses.</em></p>
  {:else}
    <table border="1" style="width: 100%">
      <thead>
        <tr>
          <th>Date</th>
          <th>Description</th>
          <th>Job</th>
          <th>Task</th>
          <th style="text-align: right">Amount</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {#each expenses as e (e.id)}
          <tr>
            <td>{e.purchased_on}</td>
            <td>{e.description || '—'}</td>
            <td>
              {#if e.job_id}
                <a href="/jobs/{e.job_id}" use:link>{e.job_number}{e.job_name ? ' — ' + e.job_name : ''}</a>
              {:else}
                —
              {/if}
            </td>
            <td>{e.task_name || '—'}</td>
            <td style="text-align: right">${e.amount}</td>
            <td><em>{statusLabel(e.status)}</em></td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>
