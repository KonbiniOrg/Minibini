<script>
  import { api } from '../../lib/api.js';
  import { user as currentUser } from '../../stores/auth.js';
  import { canManageFinancials } from '../../stores/permissions.js';
  import { getPaymentAccounts } from '../../lib/paymentAccounts.js';
  import MaterialPicker from './MaterialPicker.svelte';
  import JobPicker from '../JobPicker.svelte';

  let {
    // Optional: pass an existing expense to edit. If null, it's a create form.
    expense = null,
    // Called after a successful save/create. Parent decides what to do next.
    onSaved = (exp) => {},
    onCancel = () => {},
    // When true, force purchased_by to the logged-in user and hide the picker.
    // Used by the Home-card "My Expenses" surface.
    lockPurchasedByToSelf = false,
    // Optional { job_id, job_number } to pre-anchor a new expense (e.g. opened
    // from a Task detail page). Ignored when editing an existing expense.
    initialJob = null,
    // Attach mode: an existing PENDING material this expense records the cost
    // of (supplies its cost + receives into its lot). When set, the job is
    // fixed to the material's job and the new-material picker is hidden.
    initialMaterial = null,
  } = $props();

  let isEdit = $derived(!!expense);

  // Form state
  // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
  let amount = $state(expense?.amount || '');
  // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
  let purchased_on = $state(expense?.purchased_on || new Date().toISOString().slice(0, 10));
  // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
  let description = $state(expense?.description || '');
  // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
  let accounting_category = $state(expense?.accounting_category || '');
  // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
  let payment_method = $state(expense?.payment_method || 'personal');
  // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
  let payment_account_id = $state(expense?.payment_account_id || '');
  // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
  let reference_number = $state(expense?.reference_number || '');
  // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
  let purchased_by = $state(expense?.purchased_by || $currentUser?.id || null);
  let newMaterial = $state(null);

  // Job is the cost anchor. jobId is the numeric id; jobRow is the full job
  // object fed as selectedItem to JobPicker for edit-mode / initialJob prefill.
  // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
  let jobId = $state(expense?.job ?? initialJob?.job_id ?? initialMaterial?.job ?? null);
  let jobRow = $state(
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    expense?.job
      // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
      ? { job_id: expense.job, job_number: expense.job_number, name: expense?.job_name }
      // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
      : (initialJob || null)
  );

  // Compound "paid by" select value: "personal" or "company:<account_id>"
  let paidByValue = $state(
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    expense?.payment_method === 'company' && expense?.payment_account_id
      // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
      ? `company:${expense.payment_account_id}`
      : 'personal'
  );

  // Dropdown sources
  let categories = $state([]);
  let linkedCategories = $derived(categories.filter(c => c.qbo_expense_account_id));
  let paymentAccounts = $state([]);
  let workers = $state([]);

  let saving = $state(false);
  let errors = $state({});

  async function loadDropdowns() {
    try {
      const catData = await api.get('/api/accounting-categories/');
      categories = catData.results || catData;
    } catch (_) { /* ignore */ }

    paymentAccounts = await getPaymentAccounts();

    // Load workers for purchased_by dropdown — optional; could default to self
    try {
      const users = await api.get('/api/users/');
      workers = users.results || users;
    } catch (_) { /* not everyone can hit /api/users/ */ }
  }

  loadDropdowns();

  function handlePaidByChange(e) {
    const val = e.target.value;
    paidByValue = val;
    if (val === 'personal') {
      payment_method = 'personal';
      payment_account_id = '';
    } else if (val.startsWith('company:')) {
      payment_method = 'company';
      payment_account_id = val.slice('company:'.length);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    errors = {};
    saving = true;

    try {
      const payload = {
        amount,
        purchased_on,
        description,
        accounting_category,
        payment_method,
        payment_account_id: payment_method === 'company' ? payment_account_id : '',
        reference_number,
        purchased_by: payment_method === 'personal' ? purchased_by : (purchased_by || null),
        job: jobId,
      };

      // Attach mode: link the cost to an existing pending material (mutually
      // exclusive with new_material). Otherwise, if the user queued a purchased
      // item, include it — the backend creates a consumable material, or a
      // stock receipt for an inventoried PLI.
      if (initialMaterial) {
        payload.material_id = initialMaterial.material_id;
      } else if (newMaterial) {
        payload.new_material = { ...newMaterial, job_id: jobId };
      }

      let saved;
      if (isEdit) {
        saved = await api.patch(`/api/expenses/${expense.id}/`, payload);
      } else {
        saved = await api.post('/api/expenses/', payload);
      }
      onSaved(saved);
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        errors = err.data;
      } else {
        errors = { non_field_errors: [err.message || 'Could not save.'] };
      }
    } finally {
      saving = false;
    }
  }

  function fieldErr(key) {
    return errors[key] ? (Array.isArray(errors[key]) ? errors[key] : [errors[key]]) : [];
  }
</script>

<form onsubmit={handleSubmit}>
  <p>
    <label for="ef-amount"><strong>Amount *</strong></label><br>
    <input id="ef-amount" type="number" min="0" step="0.01" bind:value={amount} required>
  </p>
  {#each fieldErr('amount') as msg}<p><em>{msg}</em></p>{/each}

  <p>
    <label for="ef-date"><strong>Purchased on *</strong></label><br>
    <input id="ef-date" type="date" bind:value={purchased_on} required>
  </p>
  {#each fieldErr('purchased_on') as msg}<p><em>{msg}</em></p>{/each}

  <p>
    <label for="ef-desc"><strong>Description</strong></label><br>
    <input id="ef-desc" type="text" bind:value={description} style="width: 100%">
  </p>

  <p>
    <label for="ef-cat"><strong>Category *</strong></label><br>
    {#if linkedCategories.length === 0}
      <em>No QuickBooks accounts linked — go to <a href="#/settings">Settings</a> and link them.</em>
    {:else}
      <select id="ef-cat" bind:value={accounting_category} required>
        <option value="">-- select --</option>
        {#each linkedCategories as c (c.id)}
          <option value={c.id}>{c.name}</option>
        {/each}
      </select>
    {/if}
  </p>
  {#each fieldErr('accounting_category') as msg}<p><em>{msg}</em></p>{/each}

  {#if !lockPurchasedByToSelf}
    <p>
      <label for="ef-pm"><strong>Paid by *</strong></label><br>
      <select id="ef-pm" value={paidByValue} onchange={handlePaidByChange}>
        <option value="personal">Personal (reimbursement)</option>
        {#each paymentAccounts as a (a.qbo_account_id)}
          <option value="company:{a.qbo_account_id}">{a.display_name}</option>
        {/each}
      </select>
      {#if paymentAccounts.length === 0}
        <br><em>Company-paid needs a payment account — configure one in
          Settings → QuickBooks.</em>
      {/if}
    </p>
  {/if}

  {#if payment_method === 'company'}
    <p>
      <label for="ef-ref">Reference / check number (optional)</label><br>
      <input id="ef-ref" type="text" bind:value={reference_number}>
    </p>
  {/if}

  {#if payment_method === 'personal' && !lockPurchasedByToSelf && $canManageFinancials}
    <p>
      <label for="ef-purchby"><strong>Purchased by *</strong></label><br>
      <select id="ef-purchby" bind:value={purchased_by}>
        {#each workers as w (w.id)}
          <option value={w.id}>{w.first_name} {w.last_name} ({w.username})</option>
        {/each}
      </select>
    </p>
    {#each fieldErr('purchased_by') as msg}<p><em>{msg}</em></p>{/each}
  {/if}

  <p>
    <label for="ef-job"><strong>Job</strong> (leave blank for overhead)</label><br>
    <JobPicker bind:value={jobId} selectedItem={jobRow} onSelect={(j) => { jobRow = j; }} />
  </p>
  {#each fieldErr('job') as msg}<p><em>{msg}</em></p>{/each}

  {#if initialMaterial}
    <p class="attach-note">Recording a cost against material:
      <strong>{initialMaterial.description || '(material)'}</strong></p>
  {:else}
    <MaterialPicker
      jobId={jobId}
      bind:newMaterial={newMaterial}
      defaultDescription={description}
      defaultAmount={amount}
    />
  {/if}
  {#each fieldErr('material') as msg}<p class="error"><em>{msg}</em></p>{/each}
  {#each fieldErr('material_id') as msg}<p class="error"><em>{msg}</em></p>{/each}

  {#each fieldErr('non_field_errors') as msg}<p class="error"><em>{msg}</em></p>{/each}
  {#each fieldErr('detail') as msg}<p class="error"><em>{msg}</em></p>{/each}

  <p>
    <button type="submit" disabled={saving}>
      {saving ? 'Saving...' : (isEdit ? 'Save changes' : 'Submit expense')}
    </button>
    <button type="button" onclick={onCancel}>Cancel</button>
  </p>
</form>
