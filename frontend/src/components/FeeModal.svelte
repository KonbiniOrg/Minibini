<script>
  import { api, errorMessage } from '../lib/api.js';
  import { triageError } from '../lib/errorTriage.js';
  import { showError } from '../stores/messages.js';
  import Modal from './Modal.svelte';
  import FieldError from './FieldError.svelte';
  import FormMessage from './FormMessage.svelte';

  let {
    open = false,
    mode = 'create', // 'create' | 'edit'
    fee = null,
    jobId = null,
    categories = [],
    presetDescription = '',
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let description = $state('');
  let quantity = $state('1');
  let unitRate = $state('');
  let accountingCategory = $state('');
  let busy = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});
  let confirmDelete = $state(false);

  // Fee.unit_rate is signed: negative = credit. Echo that back so the user
  // sees it coming before they save — mirrors the wording used on the
  // Estimate/CO Fee-Credit hand-line forms.
  const isCredit = $derived(
    unitRate !== '' && !Number.isNaN(Number(unitRate)) && Number(unitRate) < 0
  );

  $effect(() => {
    if (open) {
      if (mode === 'edit' && fee) {
        description = fee.description || '';
        quantity = fee.quantity != null ? String(fee.quantity) : '1';
        unitRate = fee.unit_rate != null ? String(fee.unit_rate) : '';
        // Keep numeric: the AC <option value={cat.id}> is numeric and
        // Svelte 5 matches with strict === — String() here shows no selection.
        accountingCategory = fee.accounting_category ?? '';
      } else {
        description = (mode === 'edit' && fee) ? (fee.description || '') : (presetDescription || '');
        quantity = '1';
        unitRate = '';
        accountingCategory = '';
      }
      formError = '';
      fieldErrs = {};
      confirmDelete = false;
    }
  });

  // Clear stale errors when the user edits any field. Don't read
  // `formError`/`fieldErrs` here — that would track them as dependencies
  // and re-clear the instant the catch block sets them.
  $effect(() => {
    description; quantity; unitRate; accountingCategory;
    formError = '';
    fieldErrs = {};
  });

  async function save() {
    busy = true;
    formError = '';
    fieldErrs = {};
    const payload = {
      description,
      quantity: quantity !== '' ? Number(quantity) : 1,
      unit_rate: unitRate !== '' ? Number(unitRate) : 0,
      accounting_category: accountingCategory !== '' ? Number(accountingCategory) : null,
    };
    // A Fee with unit_rate=0 charges nothing — meaningless. Mirrors
    // FeeService._reject_zero_unit_rate server-side (apps/jobs/services.py);
    // caught here too so the user doesn't need a round trip to find out.
    if (payload.unit_rate === 0) {
      fieldErrs = { unit_rate: ['unit_rate must not be zero.'] };
      busy = false;
      return;
    }
    try {
      if (mode === 'edit' && fee) {
        await api.patch(`/api/jobs/${jobId}/fees/${fee.fee_id}/`, payload);
      } else {
        await api.post(`/api/jobs/${jobId}/fees/`, payload);
      }
      onSaved();
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        formError = t.message;
        fieldErrs = t.fields;
      }
    } finally {
      busy = false;
    }
  }

  async function deleteFee() {
    if (!confirmDelete) {
      confirmDelete = true;
      return;
    }
    busy = true;
    formError = '';
    fieldErrs = {};
    try {
      await api.delete(`/api/jobs/${jobId}/fees/${fee.fee_id}/`);
      onSaved();
    } catch (e) {
      // Non-form action: the global overlay is the venue.
      showError(errorMessage(e, 'Could not delete fee.'));
      confirmDelete = false;
    } finally {
      busy = false;
    }
  }
</script>

<Modal {open} onCancel={() => { if (confirmDelete) confirmDelete = false; else onClose(); }} maxWidth="720px">
<form onsubmit={(e) => { e.preventDefault(); if (!busy && !confirmDelete) save(); }}>
      <h3>{mode === 'edit' ? 'Edit Fee / Credit' : 'Add Fee / Credit'}</h3>

      <p>
        <label><strong>Description</strong><br>
          <input type="text" bind:value={description} style="width:100%;box-sizing:border-box;">
        </label>
        <FieldError errors={fieldErrs} field="description" />
      </p>

      <p>
        <label><strong>Quantity</strong><br>
          <input type="number" step="0.01" bind:value={quantity}>
        </label>
        <FieldError errors={fieldErrs} field="quantity" />
      </p>

      <p>
        <label><strong>Unit Rate</strong><br>
          <input type="number" step="0.01" bind:value={unitRate}>
        </label>
        <FieldError errors={fieldErrs} field="unit_rate" />
      </p>
      {#if isCredit}<p class="credit-note">This will appear as a credit.</p>{/if}

      <p>
        <label><strong>Accounting Category</strong><br>
          <select bind:value={accountingCategory}>
            <option value="">-- None --</option>
            {#each categories as cat}
              <option value={cat.id}>{cat.code} - {cat.name}</option>
            {/each}
          </select>
        </label>
        <FieldError errors={fieldErrs} field="accounting_category" />
      </p>

      <div class="buttons">
        <button type="submit" disabled={busy}>Save</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
        {#if mode === 'edit' && fee}
          {#if confirmDelete}
            <button type="button" class="btn-danger" onclick={deleteFee} disabled={busy}>Confirm delete</button>
            <button type="button" onclick={() => { confirmDelete = false; }} disabled={busy}>Keep</button>
          {:else}
            <button type="button" class="btn-danger" onclick={deleteFee} disabled={busy}>Delete</button>
          {/if}
        {/if}
      </div>
      <FormMessage error={formError} />
</form>
</Modal>


<style>
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .btn-danger { background: #fee2e2; color: #991b1b; border-color: #fca5a5; }
  .btn-danger:hover:not(:disabled) { background: #fecaca; }
  .credit-note { color: #9a3412; font-style: italic; }
</style>
