<script>
  import { api } from '../lib/api.js';

  let {
    open = false,
    mode = 'create', // 'create' | 'edit'
    bundle = null,
    worksheetId = null,
    categories = [],
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let name = $state('');
  let accountingCategory = $state('');
  let busy = $state(false);
  let error = $state('');

  $effect(() => {
    if (open) {
      if (mode === 'edit' && bundle) {
        name = bundle.name || '';
        accountingCategory = bundle.accounting_category ?? '';
      } else {
        name = '';
        accountingCategory = '';
      }
      error = '';
    }
  });

  async function save() {
    busy = true;
    error = '';
    const payload = {
      name,
      accounting_category: accountingCategory || null,
    };
    try {
      if (mode === 'edit' && bundle) {
        await api.patch(`/api/est-worksheets/${worksheetId}/bundles/${bundle.plan_bundle_id}/`, payload);
      } else {
        await api.post(`/api/est-worksheets/${worksheetId}/bundles/`, payload);
      }
      onSaved();
    } catch (e) {
      if (e.data && typeof e.data === 'object' && !e.data.detail) {
        error = Object.entries(e.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        error = e.message || 'Could not save bundle.';
      }
    } finally {
      busy = false;
    }
  }
</script>

{#if open}
  <div class="overlay">
    <div class="modal">
      <h3>{mode === 'edit' ? 'Edit Bundle' : 'Create Bundle'}</h3>

      <p>
        <label><strong>Description *</strong><br>
          <input type="text" bind:value={name} placeholder="Appears as the estimate line item description" style="width:100%;box-sizing:border-box;">
        </label>
      </p>

      <p>
        <label><strong>Accounting Category</strong><br>
          <select bind:value={accountingCategory}>
            <option value="">-- None --</option>
            {#each categories as cat}
              <option value={cat.id}>{cat.code} — {cat.name}</option>
            {/each}
          </select>
        </label>
      </p>

      <div class="buttons">
        <button type="button" onclick={save} disabled={busy}>Save</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.4);
    display: flex; align-items: center; justify-content: center; z-index: 200;
  }
  .modal { background: white; padding: 16px; max-width: 500px; width: 90%; border: 1px solid #ccc; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
