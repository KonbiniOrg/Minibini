<!-- Modal for adding/editing a Change Order line item.
     action: 'add' | 'remove' | 'replace'
     For remove/replace, the user picks a target estimate line item. -->
<script>
  import { api } from '../../lib/api.js';
  import UnitsSelect from '../UnitsSelect.svelte';
  import { modalKeys } from '../../lib/modalKeys.js';

  let {
    open = false,
    mode = 'create',   // 'create' | 'edit'
    coId = null,
    item = null,       // existing CO line item when editing
    estimateLines = [],  // EstimateLineItem list for target picking
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let action = $state('add');
  let targetLineItem = $state('');
  let description = $state('');
  let qty = $state('');
  let units = $state('none');
  let price = $state('');
  let busy = $state(false);
  let error = $state('');

  // Whether description/qty/units/price fields are needed (not for plain 'remove')
  let needsLineFields = $derived(action !== 'remove');

  $effect(() => {
    if (open) {
      if (mode === 'edit' && item) {
        action = item.action || 'add';
        targetLineItem = item.target_line_item ? String(item.target_line_item) : '';
        description = item.description || '';
        qty = item.qty ?? '';
        units = item.units || 'none';
        price = item.price ?? '';
      } else {
        action = 'add';
        targetLineItem = '';
        description = '';
        qty = '';
        units = 'none';
        price = '';
      }
      error = '';
    }
  });

  async function save() {
    busy = true;
    error = '';
    const payload = {
      action,
      target_line_item: (action === 'remove' || action === 'replace') && targetLineItem
        ? Number(targetLineItem)
        : null,
    };
    if (needsLineFields) {
      payload.description = description;
      payload.qty = qty || '0';
      payload.units = units;
      payload.price = price || '0';
    }
    try {
      if (mode === 'edit' && item) {
        await api.patch(`/api/change-orders/${coId}/line-items/${item.id}/`, payload);
      } else {
        await api.post(`/api/change-orders/${coId}/line-items/`, payload);
      }
      onSaved();
    } catch (e) {
      if (e.data && typeof e.data === 'object' && !e.data.detail) {
        error = Object.entries(e.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        error = e.message || 'Could not save line item.';
      }
    } finally {
      busy = false;
    }
  }
</script>

{#if open}
  <div class="overlay" use:modalKeys={{ onSave: () => { if (!busy) save(); }, onCancel: onClose }}>
    <div class="modal">
      <h3>{mode === 'edit' ? 'Edit Change Order Line' : 'Add Change Order Line'}</h3>

      <p>
        <label><strong>Action *</strong><br>
          <select bind:value={action}>
            <option value="add">Add — new line item to be added</option>
            <option value="remove">Remove — remove an existing estimate line</option>
            <option value="replace">Replace — replace an existing estimate line</option>
          </select>
        </label>
      </p>

      {#if action === 'remove' || action === 'replace'}
        <p>
          <label><strong>Target estimate line *</strong><br>
            <select bind:value={targetLineItem}>
              <option value="">-- Select estimate line --</option>
              {#each estimateLines as li}
                <option value={String(li.line_item_id)}>
                  #{li.line_number} — {li.description || '(no description)'} (${Number(li.price ?? 0).toFixed(2)} × {li.qty ?? 0} {li.units || ''})
                </option>
              {/each}
            </select>
          </label>
        </p>
      {/if}

      {#if needsLineFields}
        <p>
          <label><strong>Description *</strong><br>
            <input type="text" bind:value={description} style="width:100%;box-sizing:border-box;">
          </label>
        </p>

        <p>
          <label><strong>Quantity</strong><br>
            <input type="number" step="0.01" bind:value={qty}>
          </label>
        </p>

        <p>
          <label><strong>Units</strong><br>
            <UnitsSelect bind:value={units} />
          </label>
        </p>

        <p>
          <label><strong>Price</strong><br>
            <input type="number" step="0.01" bind:value={price}>
          </label>
        </p>
      {/if}

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
  .modal { background: white; padding: 16px; max-width: 520px; width: 90%; border: 1px solid #ccc; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
