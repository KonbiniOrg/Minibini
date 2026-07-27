<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';

  let categories = $state([]);
  let defaultDepositCategoryId = $state('');
  let error = $state('');
  let success = $state('');
  let saving = $state(false);
  let loading = $state(true);

  let depositCategories = $derived(categories.filter(c => c.is_active && c.is_deposit));

  async function load() {
    loading = true;
    try {
      const [catData, settings] = await Promise.all([
        api.get('/api/accounting-categories/'),
        api.get('/api/settings/'),
      ]);
      categories = catData.results || catData;
      defaultDepositCategoryId = settings.default_deposit_accounting_category || '';
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
        default_deposit_accounting_category: defaultDepositCategoryId,
      });
      success = 'Default deposit category saved.';
      setTimeout(() => success = '', 3000);
    } catch (e) {
      const t = triageError(e);
      error = t.fields.default_deposit_accounting_category
        || t.message || t.overlay || 'Failed to save';
    } finally {
      saving = false;
    }
  }

  onMount(() => { load(); });
</script>

{#if !loading}
  <fieldset>
    <legend><strong>Deposits</strong></legend>
    <p>
      <label for="default-deposit-category"><strong>Default deposit category</strong></label><br>
      <select id="default-deposit-category" bind:value={defaultDepositCategoryId}>
        <option value="">-- None --</option>
        {#each depositCategories as cat (cat.id)}
          <option value={String(cat.id)}>{cat.name}</option>
        {/each}
      </select>
      {#if error}<strong>Error:</strong> {error}{/if}
      {#if success}<em>{success}</em>{/if}
    </p>
    <p><small>Deposit lines are stamped with this category. Deposit
    categories are always non-taxable — deposits must not be taxed.</small></p>
    <p>
      <button type="button" onclick={save} disabled={saving}>
        {saving ? 'Saving...' : 'Save'}
      </button>
    </p>
  </fieldset>
{/if}
