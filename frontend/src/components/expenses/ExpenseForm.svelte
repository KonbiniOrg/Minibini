<script>
  import { api } from '../../lib/api.js';
  import { user as currentUser } from '../../stores/auth.js';
  import { getPaymentAccounts } from '../../lib/paymentAccounts.js';
  import MaterialPicker from './MaterialPicker.svelte';

  let {
    // Optional: pass an existing expense to edit. If null, it's a create form.
    expense = null,
    // Called after a successful save/create. Parent decides what to do next.
    onSaved = (exp) => {},
    onCancel = () => {},
  } = $props();

  let isEdit = $derived(!!expense);

  // Form state
  let amount = $state(expense?.amount || '');
  let purchased_on = $state(expense?.purchased_on || new Date().toISOString().slice(0, 10));
  let description = $state(expense?.description || '');
  let accounting_category = $state(expense?.accounting_category || '');
  let payment_method = $state(expense?.payment_method || 'personal');
  let payment_account_id = $state(expense?.payment_account_id || '');
  let reference_number = $state(expense?.reference_number || '');
  let purchased_by = $state(expense?.purchased_by || $currentUser?.id || null);
  let material = $state(expense?.material || null);
  let newMaterial = $state(null);

  // Compound "paid by" select value: "personal" or "company:<account_id>"
  let paidByValue = $state(
    expense?.payment_method === 'company' && expense?.payment_account_id
      ? `company:${expense.payment_account_id}`
      : 'personal'
  );

  // Dropdown sources
  let categories = $state([]);
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
        material: material,
      };

      // If the user queued a new material, include it in the expense payload.
      // The backend creates both atomically.
      if (newMaterial) {
        payload.material = null;
        payload.new_material = {
          work_order_id: newMaterial.work_order_id,
          description: newMaterial.description || description,
          price: amount,
        };
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
    <select id="ef-cat" bind:value={accounting_category} required>
      <option value="">-- select --</option>
      {#each categories as c (c.id)}
        <option value={c.id}>{c.name}</option>
      {/each}
    </select>
  </p>
  {#each fieldErr('accounting_category') as msg}<p><em>{msg}</em></p>{/each}

  <p>
    <label for="ef-pm"><strong>Paid by *</strong></label><br>
    <select id="ef-pm" value={paidByValue} onchange={handlePaidByChange}>
      <option value="personal">Personal (reimbursement)</option>
      {#each paymentAccounts as a (a.qbo_account_id)}
        <option value="company:{a.qbo_account_id}">{a.display_name}</option>
      {/each}
    </select>
  </p>

  {#if payment_method === 'company'}
    <p>
      <label for="ef-ref">Reference / check number (optional)</label><br>
      <input id="ef-ref" type="text" bind:value={reference_number}>
    </p>
  {/if}

  {#if payment_method === 'personal'}
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

  <MaterialPicker bind:materialId={material} bind:newMaterial={newMaterial} defaultDescription={description} defaultAmount={amount} />

  {#each fieldErr('non_field_errors') as msg}<p><em>{msg}</em></p>{/each}

  <p>
    <button type="submit" disabled={saving}>
      {saving ? 'Saving...' : (isEdit ? 'Save changes' : 'Submit expense')}
    </button>
    <button type="button" onclick={onCancel}>Cancel</button>
  </p>
</form>
