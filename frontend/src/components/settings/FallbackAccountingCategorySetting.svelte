<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';

  let categories = $state([]);
  let fallbackCategoryId = $state('');
  let error = $state('');
  let success = $state('');
  let saving = $state(false);
  let loading = $state(true);

  // A deposit category can never be the fallback (deposits have special
  // semantics — see AccountingCategory.clean). include_fallback=true so
  // the currently designated category still shows in its own picker even
  // though normal pickers exclude it.
  let eligibleCategories = $derived(
    categories.filter(c => c.is_active && !c.is_deposit));

  async function load() {
    loading = true;
    try {
      const [catData, settings] = await Promise.all([
        api.get('/api/accounting-categories/?include_fallback=true'),
        api.get('/api/settings/'),
      ]);
      categories = catData.results || catData;
      fallbackCategoryId = settings.fallback_accounting_category || '';
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
        fallback_accounting_category: fallbackCategoryId,
      });
      success = 'Fallback accounting category saved.';
      setTimeout(() => success = '', 3000);
    } catch (e) {
      const t = triageError(e);
      error = t.fields.fallback_accounting_category
        || t.message || t.overlay || 'Failed to save';
    } finally {
      saving = false;
    }
  }

  onMount(() => { load(); });
</script>

{#if !loading}
  <fieldset>
    <legend><strong>Uncategorized lines</strong></legend>
    <p>
      <label for="fallback-accounting-category"><strong>Fallback accounting category</strong></label><br>
      <select id="fallback-accounting-category" bind:value={fallbackCategoryId}>
        <option value="">-- None --</option>
        {#each eligibleCategories as cat (cat.id)}
          <option value={String(cat.id)}>{cat.name}</option>
        {/each}
      </select>
      {#if error}<strong>Error:</strong> {error}{/if}
      {#if success}<em>{success}</em>{/if}
    </p>
    <p><small>Used when a task with no accounting category is composed onto
    an invoice — the line is stamped with this category instead of being
    blocked. Excluded from normal category pickers once designated.</small></p>
    <p>
      <button type="button" onclick={save} disabled={saving}>
        {saving ? 'Saving...' : 'Save'}
      </button>
    </p>
  </fieldset>
{/if}
