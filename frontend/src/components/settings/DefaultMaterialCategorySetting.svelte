<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';

  let categories = $state([]);
  let defaultMaterialCategoryId = $state('');
  let error = $state('');
  let success = $state('');
  let saving = $state(false);
  let loading = $state(true);

  let activeCategories = $derived(categories.filter(c => c.is_active));

  async function load() {
    loading = true;
    try {
      const [catData, settings] = await Promise.all([
        api.get('/api/accounting-categories/'),
        api.get('/api/settings/'),
      ]);
      categories = catData.results || catData;
      defaultMaterialCategoryId = settings.default_material_accounting_category || '';
    } catch (_) {
      // Best-effort: the picker just stays blank.
    } finally {
      loading = false;
    }
  }

  async function save() {
    saving = true;
    error = '';
    success = '';
    try {
      await api.patch('/api/settings/', {
        default_material_accounting_category: defaultMaterialCategoryId,
      });
      success = 'Default material category saved.';
      setTimeout(() => success = '', 3000);
    } catch (e) {
      const t = triageError(e);
      error = t.fields.default_material_accounting_category
        || t.message || t.overlay || 'Failed to save';
    } finally {
      saving = false;
    }
  }

  onMount(() => { load(); });
</script>

{#if !loading}
  <fieldset>
    <legend><strong>Materials</strong></legend>
    <p>
      <label for="default-material-category"><strong>Default material category</strong></label><br>
      <select id="default-material-category" bind:value={defaultMaterialCategoryId}>
        <option value="">-- None --</option>
        {#each activeCategories as cat (cat.id)}
          <option value={String(cat.id)}>{cat.name}</option>
        {/each}
      </select>
      {#if error}<strong>Error:</strong> {error}{/if}
      {#if success}<em>{success}</em>{/if}
    </p>
    <p><small>Accounting category applied by default to materials on estimate acceptance.</small></p>
    <p>
      <button type="button" onclick={save} disabled={saving}>
        {saving ? 'Saving...' : 'Save'}
      </button>
    </p>
  </fieldset>
{/if}
