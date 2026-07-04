<script>
  import { api } from '../lib/api.js';
  import Modal from './Modal.svelte';

  let {
    open = false,
    mode = 'create', // 'create' | 'edit'
    fee = null,
    jobId = null,
    taskId = null,
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
  let error = $state('');
  let confirmDelete = $state(false);

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
      error = '';
      confirmDelete = false;
    }
  });

  // Clear stale error when the user edits any field.
  $effect(() => {
    description; quantity; unitRate; accountingCategory;
    error = '';
  });

  async function save() {
    busy = true;
    error = '';
    const payload = {
      description,
      quantity: quantity !== '' ? Number(quantity) : 1,
      unit_rate: unitRate !== '' ? Number(unitRate) : 0,
      accounting_category: accountingCategory !== '' ? Number(accountingCategory) : null,
    };
    try {
      if (mode === 'edit' && fee) {
        await api.patch(`/api/jobs/${jobId}/fees/${fee.fee_id}/`, payload);
      } else {
        await api.post(`/api/jobs/${jobId}/fees/`, { ...payload, task: taskId || null });
      }
      onSaved();
    } catch (e) {
      if (e.data && typeof e.data === 'object' && !e.data.detail) {
        error = Object.entries(e.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        error = e.message || e.data?.detail || 'Could not save fee.';
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
    error = '';
    try {
      await api.delete(`/api/jobs/${jobId}/fees/${fee.fee_id}/`);
      onSaved();
    } catch (e) {
      error = e.message || e.data?.detail || 'Could not delete fee.';
      confirmDelete = false;
    } finally {
      busy = false;
    }
  }
</script>

<Modal {open} {busy} onSave={() => { if (!confirmDelete) save(); }} onCancel={() => { if (confirmDelete) confirmDelete = false; else onClose(); }} maxWidth="720px">
      <h3>{mode === 'edit' ? 'Edit Fee' : 'Add Fee'}</h3>

      <p>
        <label><strong>Description</strong><br>
          <input type="text" bind:value={description} style="width:100%;box-sizing:border-box;">
        </label>
      </p>

      <p>
        <label><strong>Quantity</strong><br>
          <input type="number" step="0.01" bind:value={quantity}>
        </label>
      </p>

      <p>
        <label><strong>Unit Rate</strong><br>
          <input type="number" step="0.01" bind:value={unitRate}>
        </label>
      </p>

      <p>
        <label><strong>Accounting Category</strong><br>
          <select bind:value={accountingCategory}>
            <option value="">-- None --</option>
            {#each categories as cat}
              <option value={cat.id}>{cat.code} - {cat.name}</option>
            {/each}
          </select>
        </label>
      </p>

      <div class="buttons">
        <button type="button" onclick={save} disabled={busy}>Save</button>
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
      {#if error}<p class="error">{error}</p>{/if}
</Modal>


<style>
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
  .btn-danger { background: #fee2e2; color: #991b1b; border-color: #fca5a5; }
  .btn-danger:hover:not(:disabled) { background: #fecaca; }
</style>
