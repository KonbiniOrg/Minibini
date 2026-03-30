<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';

  let categories = $state([]);
  let qboAccounts = $state(null);
  let loading = $state(true);
  let saving = $state(null);
  let error = $state(null);
  let success = $state(null);

  async function loadData() {
    loading = true;
    error = null;
    try {
      const [catData, acctData] = await Promise.all([
        api.get('/api/accounting-categories/'),
        api.get('/api/qbo/accounts/').catch(() => null),
      ]);
      categories = catData.results || catData;
      qboAccounts = acctData;
    } catch (e) {
      if (e.status === 403) {
        categories = [];
        return;
      }
      error = e.message || 'Failed to load data';
    } finally {
      loading = false;
    }
  }

  async function saveMapping(category, field, value) {
    saving = category.id;
    error = null;
    success = null;
    try {
      await api.patch(`/api/accounting-categories/${category.id}/`, {
        [field]: value,
      });
      success = `Updated ${category.name}`;
      setTimeout(() => success = null, 3000);
    } catch (e) {
      error = e.message || 'Failed to save';
    } finally {
      saving = null;
    }
  }

  onMount(() => {
    loadData();
  });
</script>

{#if loading}
  <p>Loading accounting categories...</p>
{:else if categories.length === 0}
  <!-- No permission or no categories -->
{:else}
  <fieldset>
    <legend><strong>Accounting Category Mappings</strong></legend>

    {#if error}
      <p><strong>Error:</strong> {error}</p>
    {/if}
    {#if success}
      <p><strong>{success}</strong></p>
    {/if}

    {#if !qboAccounts}
      <p>Connect to QuickBooks to map categories to QBO accounts.</p>
    {:else}
      <table border="1">
        <thead>
          <tr>
            <th>Category</th>
            <th>Taxable</th>
            <th>QBO Item (Income)</th>
            <th>QBO Expense Account</th>
          </tr>
        </thead>
        <tbody>
          {#each categories as cat}
            <tr>
              <td><strong>{cat.name}</strong> ({cat.code})</td>
              <td>{cat.taxable ? 'Yes' : 'No'}</td>
              <td>
                <select
                  value={cat.qbo_item_id}
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
                  value={cat.qbo_expense_account_id}
                  onchange={(e) => saveMapping(cat, 'qbo_expense_account_id', e.target.value)}
                  disabled={saving === cat.id}
                >
                  <option value="">-- None --</option>
                  {#each qboAccounts.expense_accounts as acct}
                    <option value={acct.id}>{acct.name}</option>
                  {/each}
                </select>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </fieldset>
{/if}
