<script>
  import { api } from '../../lib/api.js';
  import UnitsSelect from '../UnitsSelect.svelte';

  let { item = null, onSaved = () => {}, onCancel = () => {} } = $props();

  const editing = $derived(!!item);

  let code = $state(item?.code ?? '');
  let description = $state(item?.description ?? '');
  let units = $state(item?.units ?? 'none');
  let purchasePrice = $state(item?.purchase_price ?? '');
  let sellPrice = $state(item?.selling_price ?? '');
  let isCatalog = $state(item ? item.is_catalog : true);
  let isActive = $state(item ? item.is_active : true);
  let accountingCategory = $state(item?.accounting_category ?? '');

  let categories = $state([]);
  let error = $state('');
  let fieldErrors = $state({});
  let saving = $state(false);

  async function loadCategories() {
    try {
      const data = await api.get('/api/accounting-categories/');
      categories = data.results || data;
    } catch (err) {
      error = err.message || 'Could not load categories.';
    }
  }
  loadCategories();

  function fieldErr(name) {
    const e = fieldErrors[name];
    return Array.isArray(e) ? e.join(' ') : e;
  }

  async function save() {
    error = '';
    fieldErrors = {};
    saving = true;
    try {
      const payload = {
        code,
        description,
        units,
        purchase_price: purchasePrice === '' ? '0.00' : purchasePrice,
        is_catalog: isCatalog,
        accounting_category: accountingCategory,
      };
      // Only send selling_price when the user set one. On create, leaving it
      // blank lets the server apply the markup default; on edit we keep the
      // existing value untouched unless changed.
      if (sellPrice !== '' && sellPrice !== null) {
        payload.selling_price = sellPrice;
      }
      if (editing) {
        payload.is_active = isActive;
        await api.patch(`/api/inventory/${item.inventory_item_id}/`, payload);
      } else {
        await api.post('/api/inventory/', payload);
      }
      onSaved();
    } catch (err) {
      if (err.data && typeof err.data === 'object') {
        fieldErrors = err.data;
        error = err.data.detail || 'Please fix the errors below.';
      } else {
        error = err.message || 'Save failed.';
      }
    } finally {
      saving = false;
    }
  }
</script>

<form onsubmit={(e) => { e.preventDefault(); save(); }}>
  {#if error}<p class="form-error">{error}</p>{/if}

  <p><label><strong>Code *</strong></label><br>
    <input type="text" bind:value={code} required>
    {#if fieldErr('code')}<br><span class="form-error">{fieldErr('code')}</span>{/if}</p>

  <p><label><strong>Description</strong></label><br>
    <textarea bind:value={description} rows="2"></textarea></p>

  <p><label><strong>Units</strong></label><br>
    <UnitsSelect bind:value={units} /></p>

  <p><label><strong>Purchase price</strong></label><br>
    <input type="number" step="0.01" min="0" bind:value={purchasePrice}></p>

  <p><label><strong>Selling price</strong></label><br>
    <input type="number" step="0.01" min="0" bind:value={sellPrice}
      placeholder={editing ? '' : 'blank = apply markup'}></p>

  <p><label><input type="checkbox" bind:checked={isCatalog}>
    <strong>Catalog item</strong> (reorderable type; survives at zero stock)</label></p>

  {#if editing}
    <p><label><input type="checkbox" bind:checked={isActive}>
      <strong>Active</strong></label></p>
  {/if}

  <p><label><strong>Accounting category *</strong></label><br>
    <select bind:value={accountingCategory} required>
      <option value="">-- select --</option>
      {#each categories as c (c.id)}
        <option value={c.id}>{c.code} — {c.name}</option>
      {/each}
    </select>
    {#if fieldErr('accounting_category')}<br><span class="form-error">{fieldErr('accounting_category')}</span>{/if}</p>

  <p>
    <button type="submit" disabled={saving}>{editing ? 'Save' : 'Create'}</button>
    <button type="button" onclick={onCancel}>Cancel</button>
  </p>
</form>

<style>
  .form-error { color: #c00; }
</style>
