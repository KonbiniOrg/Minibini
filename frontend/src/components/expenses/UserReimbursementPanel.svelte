<script>
  import { api } from '../../lib/api.js';
  import { getPaymentAccounts } from '../../lib/paymentAccounts.js';

  let { user = null } = $props();  // { id, username, first_name, last_name } or similar

  let outstanding = $state([]);
  let history = $state([]);
  let rejected = $state([]);
  let showRejected = $state(false);
  let loading = $state(true);
  let error = $state('');

  // Batch creation state
  let selectedIds = $state(new Set());
  let showBatchForm = $state(false);
  let batchPaidOn = $state(new Date().toISOString().slice(0, 10));
  let batchAccountId = $state('');
  let batchRef = $state('');
  let batchNotes = $state('');
  let batchSaving = $state(false);
  let batchError = $state('');

  let paymentAccounts = $state([]);

  async function loadAll() {
    loading = true;
    error = '';
    try {
      const [out, hist, rej, accts] = await Promise.all([
        api.get(
          `/api/expenses/?purchased_by=${user.id}&status=submitted&payment_method=personal`
        ),
        api.get(`/api/reimbursements/?purchased_by=${user.id}`),
        api.get(
          `/api/expenses/?purchased_by=${user.id}&status=rejected&payment_method=personal`
        ),
        getPaymentAccounts(),
      ]);
      outstanding = out.results || out;
      history = hist.results || hist;
      rejected = rej.results || rej;
      paymentAccounts = accts;
      if (accts.length > 0 && !batchAccountId) {
        batchAccountId = accts[0].qbo_account_id;
      }
    } catch (err) {
      error = err.message || 'Could not load.';
    } finally {
      loading = false;
    }
  }

  function toggleSelect(id) {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selectedIds = next;
  }

  function selectAll() {
    selectedIds = new Set(outstanding.map(e => e.id));
  }

  function clearSelection() {
    selectedIds = new Set();
  }

  let selectedTotal = $derived(
    outstanding
      .filter(e => selectedIds.has(e.id))
      .reduce((sum, e) => sum + parseFloat(e.amount), 0)
      .toFixed(2)
  );

  async function submitBatch() {
    batchSaving = true;
    batchError = '';
    try {
      await api.post('/api/reimbursements/', {
        purchased_by: user.id,
        expense_ids: Array.from(selectedIds),
        paid_on: batchPaidOn,
        payment_account_id: batchAccountId,
        reference_number: batchRef,
        notes: batchNotes,
      });
      selectedIds = new Set();
      showBatchForm = false;
      batchRef = '';
      batchNotes = '';
      await loadAll();
    } catch (err) {
      if (err.data) {
        batchError = JSON.stringify(err.data);
      } else {
        batchError = err.message || 'Could not create batch.';
      }
    } finally {
      batchSaving = false;
    }
  }

  async function retryBatch(batch) {
    try {
      await api.post(`/api/reimbursements/${batch.id}/retry-sync/`);
      await loadAll();
    } catch (err) {
      error = err.message || 'Retry failed.';
    }
  }

  async function rejectExpense(exp) {
    if (!confirm('Reject this expense?')) return;
    try {
      await api.post(`/api/expenses/${exp.id}/reject/`);
      await loadAll();
    } catch (err) {
      error = err.message || 'Reject failed.';
    }
  }

  $effect(() => {
    if (user) loadAll();
  });
</script>

{#if loading}
  <p><em>Loading...</em></p>
{:else if error}
  <p><em>{error}</em></p>
{:else}
  <h3>Outstanding reimbursements</h3>
  {#if outstanding.length === 0}
    <p><em>No outstanding reimbursements.</em></p>
  {:else}
    <table class="data-table" style="width: 100%">
      <thead>
        <tr>
          <th style="width: 24px">
            <input
              type="checkbox"
              onclick={(e) => e.target.checked ? selectAll() : clearSelection()}
              title="Select all"
            >
          </th>
          <th>Date</th>
          <th>Description</th>
          <th>Category</th>
          <th style="text-align: right">Amount</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {#each outstanding as e (e.id)}
          <tr>
            <td><input
              type="checkbox"
              checked={selectedIds.has(e.id)}
              onchange={() => toggleSelect(e.id)}
            ></td>
            <td>{e.purchased_on}</td>
            <td class="preserve-breaks">{e.description || '—'}</td>
            <td>{e.accounting_category}</td>
            <td style="text-align: right">${e.amount}</td>
            <td>
              <button type="button" onclick={() => rejectExpense(e)}>reject</button>
            </td>
          </tr>
        {/each}
        <tr style="font-weight: bold; background: #f9f9f9">
          <td></td>
          <td colspan="3" style="text-align: right">Selected total:</td>
          <td style="text-align: right">${selectedTotal}</td>
          <td></td>
        </tr>
      </tbody>
    </table>

    {#if selectedIds.size > 0 && !showBatchForm}
      <p>
        <button type="button" onclick={() => { showBatchForm = true; }}>
          Reimburse selected (${selectedTotal})
        </button>
      </p>
    {/if}

    {#if showBatchForm}
      <div style="border: 2px dashed #d4a017; padding: 10px; background: #fffef0; margin-top: 8px">
        <h4>Create reimbursement</h4>
        <p>
          <label for="bf-paid">Paid on *</label><br>
          <input id="bf-paid" type="date" bind:value={batchPaidOn} required>
        </p>
        <p>
          <label for="bf-acct">Payment account *</label><br>
          <select id="bf-acct" bind:value={batchAccountId} required>
            {#each paymentAccounts as a (a.qbo_account_id)}
              <option value={a.qbo_account_id}>{a.display_name}</option>
            {/each}
          </select>
        </p>
        <p>
          <label for="bf-ref">Reference (check # optional)</label><br>
          <input id="bf-ref" type="text" bind:value={batchRef}>
        </p>
        <p>
          <label for="bf-notes">Notes</label><br>
          <input id="bf-notes" type="text" bind:value={batchNotes} style="width: 100%">
        </p>
        {#if batchError}<p><em>{batchError}</em></p>{/if}
        <p>
          <button type="button" onclick={submitBatch} disabled={batchSaving}>
            {batchSaving ? 'Saving...' : 'Confirm reimbursement'}
          </button>
          <button type="button" onclick={() => { showBatchForm = false; }}>
            Cancel
          </button>
        </p>
      </div>
    {/if}
  {/if}

  <h3>Past reimbursements</h3>
  {#if history.length === 0}
    <p><em>No past reimbursements.</em></p>
  {:else}
    <table class="data-table" style="width: 100%">
      <thead>
        <tr>
          <th>Paid on</th>
          <th># items</th>
          <th style="text-align: right">Total</th>
          <th>Ref</th>
          <th>QBO sync</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {#each history as b (b.id)}
          <tr>
            <td>{b.paid_on}</td>
            <td>{b.expense_count}</td>
            <td style="text-align: right">${b.total}</td>
            <td>{b.reference_number || '—'}</td>
            <td><em>{b.qbo_sync_status}</em></td>
            <td>
              {#if b.qbo_sync_status === 'sync_failed'}
                <button type="button" onclick={() => retryBatch(b)}>retry push</button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  <h3>
    <label>
      <input type="checkbox" bind:checked={showRejected}>
      Show rejected expenses ({rejected.length})
    </label>
  </h3>
  {#if showRejected && rejected.length > 0}
    <table class="data-table" style="width: 100%">
      <thead>
        <tr>
          <th>Date</th>
          <th>Description</th>
          <th style="text-align: right">Amount</th>
        </tr>
      </thead>
      <tbody>
        {#each rejected as e (e.id)}
          <tr>
            <td>{e.purchased_on}</td>
            <td class="preserve-breaks">{e.description || '—'}</td>
            <td style="text-align: right">${e.amount}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
{/if}
