<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';

  let categories = $state([]);
  let qboAccounts = $state(null);
  let loadingCategories = $state(true);
  let loadingQBO = $state(true);
  let error = $state('');
  let success = $state('');
  let saving = $state(null);
  let showInactive = $state(false);
  let editing = $state(null);
  let adding = $state(false);

  let defaultMaterialCategoryId = $state('');
  let materialCategoryError = $state('');
  let savingMaterialCategory = $state(false);

  let activeCategories = $derived(categories.filter(c => c.is_active));

  const emptyForm = { code: '', name: '', taxable: true, default_description: '', is_active: true };
  let form = $state({ ...emptyForm });

  let visibleCategories = $derived(
    showInactive ? categories : categories.filter(c => c.is_active)
  );

  async function loadCategories() {
    loadingCategories = true;
    try {
      const catData = await api.get('/api/accounting-categories/');
      categories = catData.results || catData;
    } catch (e) {
      if (e.status !== 403) {
        error = e.message || 'Failed to load categories';
      }
    } finally {
      loadingCategories = false;
    }
  }

  async function loadQBOAccounts() {
    loadingQBO = true;
    try {
      qboAccounts = await api.get('/api/qbo/accounts/');
    } catch (_) {
      qboAccounts = null;
    } finally {
      loadingQBO = false;
    }
  }

  async function loadSettings() {
    try {
      const data = await api.get('/api/settings/');
      defaultMaterialCategoryId = data.default_material_accounting_category || '';
    } catch (_) {
      // Global settings load is best-effort here; the picker just stays blank.
    }
  }

  async function loadData() {
    await Promise.all([loadCategories(), loadQBOAccounts(), loadSettings()]);
  }

  function startAdd() {
    editing = null;
    form = { ...emptyForm };
    adding = true;
  }

  function startEdit(cat) {
    adding = false;
    editing = cat.id;
    form = {
      code: cat.code,
      name: cat.name,
      taxable: cat.taxable,
      default_description: cat.default_description || '',
      is_active: cat.is_active,
    };
  }

  function cancelForm() {
    adding = false;
    editing = null;
  }

  async function saveForm() {
    saving = editing || 'new';
    error = '';
    success = '';
    try {
      if (editing) {
        await api.patch(`/api/accounting-categories/${editing}/`, form);
        success = `Updated "${form.name}"`;
      } else {
        await api.post('/api/accounting-categories/', form);
        success = `Created "${form.name}"`;
      }
      adding = false;
      editing = null;
      await loadCategories();
      setTimeout(() => success = '', 3000);
    } catch (e) {
      error = e.message || 'Failed to save';
    } finally {
      saving = null;
    }
  }

  async function saveMapping(cat, field, value) {
    saving = cat.id;
    error = '';
    success = '';
    try {
      await api.patch(`/api/accounting-categories/${cat.id}/`, { [field]: value });
      success = `Updated ${cat.name}`;
      setTimeout(() => success = '', 3000);
    } catch (e) {
      error = e.message || 'Failed to save mapping';
    } finally {
      saving = null;
    }
  }

  async function saveDefaultMaterialCategory() {
    savingMaterialCategory = true;
    materialCategoryError = '';
    success = '';
    try {
      await api.patch('/api/settings/', {
        default_material_accounting_category: defaultMaterialCategoryId,
      });
      success = 'Default material category saved.';
      setTimeout(() => success = '', 3000);
    } catch (e) {
      const t = triageError(e);
      materialCategoryError =
        t.fields.default_material_accounting_category || t.message || t.overlay || 'Failed to save';
    } finally {
      savingMaterialCategory = false;
    }
  }

  onMount(() => {
    loadData();
  });
</script>

{#if loadingCategories}
  <p>Loading accounting categories...</p>
{:else if categories.length === 0 && !adding}
  <p>No accounting categories found. <button type="button" onclick={startAdd}>Add one</button></p>
{:else}
  <fieldset>
    <legend><strong>Accounting Categories</strong></legend>

    <table class="data-table">
      <thead>
        <tr>
          <th>Code</th>
          <th>Name</th>
          <th>Taxable</th>
          <th>Active</th>
          {#if qboAccounts || loadingQBO}
            <th>QBO Item (Income)</th>
            <th>QBO Expense Account</th>
          {/if}
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {#each visibleCategories as cat (cat.id)}
          <tr style={cat.is_active ? '' : 'opacity: 0.5'}>
            <td>{cat.code}</td>
            <td>{cat.name}</td>
            <td>{cat.taxable ? 'Yes' : 'No'}</td>
            <td>{cat.is_active ? 'Yes' : 'No'}</td>
            {#if loadingQBO}
              <td>Loading...</td>
              <td>Loading...</td>
            {:else if qboAccounts}
              <td>
                <select
                  value={cat.qbo_item_id || ''}
                  onchange={(e) => saveMapping(cat, 'qbo_item_id', e.target.value)}
                  disabled={saving === cat.id}
                >
                  <option value="">-- None --</option>
                  {#each qboAccounts.income_items as item}
                    <option value={item.id}>{item.name}</option>
                  {/each}
                </select>
              </td>
              <td>
                <select
                  value={cat.qbo_expense_account_id || ''}
                  onchange={(e) => saveMapping(cat, 'qbo_expense_account_id', e.target.value)}
                  disabled={saving === cat.id}
                >
                  <option value="">-- None --</option>
                  {#each qboAccounts.expense_accounts as acct}
                    <option value={acct.id}>{acct.name}</option>
                  {/each}
                </select>
              </td>
            {/if}
            <td>
              <button type="button" onclick={() => startEdit(cat)} disabled={saving != null}>Edit</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>

    <p>
      <button type="button" onclick={startAdd} disabled={adding}>Add category</button>
      <label>
        <input type="checkbox" bind:checked={showInactive}> Show inactive
      </label>
      {#if error}<strong>Error:</strong> {error}{/if}
      {#if success}<em>{success}</em>{/if}
    </p>
  </fieldset>
{/if}

{#if !loadingCategories}
  <fieldset>
    <legend><strong>Materials</strong></legend>
    <p>
      <label for="default-material-category"><strong>Default material category</strong></label><br>
      <select id="default-material-category" bind:value={defaultMaterialCategoryId}>
        <option value="">-- None --</option>
        {#each activeCategories as cat}
          <option value={String(cat.id)}>{cat.name}</option>
        {/each}
      </select>
      {#if materialCategoryError}<strong>Error:</strong> {materialCategoryError}{/if}
    </p>
    <p><small>Accounting category applied by default to materials on estimate acceptance.</small></p>
    <p>
      <button type="button" onclick={saveDefaultMaterialCategory} disabled={savingMaterialCategory}>
        {savingMaterialCategory ? 'Saving...' : 'Save'}
      </button>
    </p>
  </fieldset>
{/if}

{#if adding || editing}
  <fieldset>
    <legend><strong>{editing ? 'Edit Category' : 'New Category'}</strong></legend>
    <p>
      <label for="cat-code"><strong>Code *</strong></label><br>
      <input type="text" id="cat-code" bind:value={form.code} maxlength="20" required>
    </p>
    <p>
      <label for="cat-name"><strong>Name *</strong></label><br>
      <input type="text" id="cat-name" bind:value={form.name} maxlength="100" required>
    </p>
    <p>
      <label>
        <input type="checkbox" bind:checked={form.taxable}> <strong>Taxable by default</strong>
      </label>
    </p>
    <p>
      <label for="cat-desc"><strong>Default description</strong></label><br>
      <textarea id="cat-desc" bind:value={form.default_description} rows="3"></textarea>
    </p>
    <p>
      <label>
        <input type="checkbox" bind:checked={form.is_active}> <strong>Active</strong>
      </label>
    </p>
    <p>
      <button type="button" onclick={saveForm} disabled={saving != null}>
        {saving ? 'Saving...' : (editing ? 'Save Changes' : 'Create')}
      </button>
      <button type="button" onclick={cancelForm}>Cancel</button>
    </p>
  </fieldset>
{/if}
