<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';

  let categories = $state([]);
  let fallbackAccountingCategoryId = $state('');
  let error = $state('');
  let success = $state('');
  let saving = $state(false);
  let loading = $state(true);

  async function load() {
    loading = true;
    try {
      const [catData, settings] = await Promise.all([
        api.get('/api/accounting-categories/'),
        api.get('/api/settings/'),
      ]);
      categories = catData.results || catData;
      fallbackAccountingCategoryId = settings.fallback_accounting_category || '';
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
        fallback_accounting_category: fallbackAccountingCategoryId,
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
    <legend><strong>Fallback Accounting Category</strong></legend>
    <p>
      <label for="fallback-accounting-category"><strong>Fallback accounting category</strong></label><br>
      <select id="fallback-accounting-category" bind:value={fallbackAccountingCategoryId}>
        <option value="">-- None --</option>
        {#each categories as cat (cat.id)}
          <option value={String(cat.id)}>{cat.name}</option>
        {/each}
      </select>
      {#if error}<strong>Error:</strong> {error}{/if}
      {#if success}<em>{success}</em>{/if}
    </p>
    <p><small>Applied to uncategorized invoice lines.</small></p>
    <p>
      <button type="button" onclick={save} disabled={saving}>
        {saving ? 'Saving...' : 'Save'}
      </button>
    </p>
  </fieldset>
{/if}
