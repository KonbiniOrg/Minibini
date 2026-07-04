<!-- Modal for adding/editing a Change Order line item.
     action: 'add' | 'remove' | 'replace'
     For remove/replace, the user picks a target estimate line item.
     initialAction/initialTarget/initialDescription/initialQty/initialUnits/initialPrice
     allow callers to pre-seed the form (e.g. opening "Change" on an estimate line). -->
<script>
  import { api } from '../../lib/api.js';
  import UnitsSelect from '../UnitsSelect.svelte';
  import Modal from '../Modal.svelte';

  let {
    open = false,
    mode = 'create',   // 'create' | 'edit'
    coId = null,
    item = null,       // existing CO line item when editing
    estimateLines = [],  // EstimateLineItem list for target picking
    categories = [],     // AccountingCategory list for the add-line AC select
    // Pre-seed props (used when opening from an estimate row)
    initialAction = null,        // 'add' | 'replace' | 'remove' — overrides default
    initialTarget = null,        // target_line_item id (number) to pre-select
    initialDescription = null,
    initialQty = null,
    initialUnits = null,
    initialPrice = null,
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let action = $state('add');
  let targetLineItem = $state('');
  let description = $state('');
  let qty = $state('');
  let units = $state('none');
  let price = $state('');
  let accountingCategory = $state('');
  let busy = $state(false);
  let error = $state('');

  // Whether description/qty/units/price fields are needed (not for plain 'remove')
  let needsLineFields = $derived(action !== 'remove');
  // A bare add line crystallizes into a Fee at acceptance, so it needs an AC
  // before send; replace lines inherit from the atom they replace.
  let needsAccountingCategory = $derived(action === 'add');

  $effect(() => {
    if (open) {
      if (mode === 'edit' && item) {
        action = item.action || 'add';
        targetLineItem = item.target_line_item ? String(item.target_line_item) : '';
        description = item.description || '';
        qty = item.qty ?? '';
        units = item.units || 'none';
        price = item.price ?? '';
        // Raw number so Svelte 5's strict-=== select matching finds the option.
        accountingCategory = item.accounting_category ?? '';
      } else {
        // Apply initial props if provided, otherwise use defaults
        action = initialAction ?? 'add';
        targetLineItem = initialTarget != null ? String(initialTarget) : '';
        description = initialDescription ?? '';
        qty = initialQty ?? '';
        units = initialUnits ?? 'none';
        price = initialPrice ?? '';
        accountingCategory = '';
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
    if (needsAccountingCategory) {
      // Bare add lines need an AC to send (they crystallize into Fees);
      // material lines get the config default server-side.
      if (!accountingCategory && !item?.is_material) {
        error = 'Accounting Category is required.';
        busy = false;
        return;
      }
      payload.accounting_category = accountingCategory ? Number(accountingCategory) : null;
    }
    try {
      if (mode === 'edit' && item) {
        await api.patch(`/api/change-orders/${coId}/line-items/${item.line_item_id}/`, payload);
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

<Modal {open} onCancel={onClose} maxWidth="780px">
<form onsubmit={(e) => { e.preventDefault(); if (!busy) save(); }}>
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

        {#if needsAccountingCategory}
          <p>
            <label><strong>Accounting Category{item?.is_material ? '' : ' *'}</strong><br>
              <select bind:value={accountingCategory}>
                <option value="">-- Select --</option>
                {#each categories as cat}
                  <option value={cat.id}>{cat.code} - {cat.name}</option>
                {/each}
              </select>
            </label>
          </p>
        {/if}
      {/if}

      <div class="buttons">
        <button type="submit" disabled={busy}>Save</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
</form>
</Modal>


<style>
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
