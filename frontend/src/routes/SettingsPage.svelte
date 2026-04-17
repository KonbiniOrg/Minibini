<script>
  import QBOConnectionCard from '../components/QBOConnectionCard.svelte';
  import AccountingCategoryMapping from '../components/AccountingCategoryMapping.svelte';
  import UnitsManager from '../components/UnitsManager.svelte';
  import RateSchemeManager from '../components/RateSchemeManager.svelte';
  import TaskTemplateManager from '../components/TaskTemplateManager.svelte';
  import { fetchFromQBO, savePaymentAccounts, getPaymentAccounts } from '../lib/paymentAccounts.js';

  let qboAccounts = $state([]);
  let enabled = $state([]);
  let loadingQBO = $state(false);
  let qboError = $state('');
  let saveMessage = $state('');

  async function loadSaved() {
    try {
      enabled = await getPaymentAccounts();
    } catch (_) {}
  }

  async function refreshFromQBO() {
    loadingQBO = true;
    qboError = '';
    try {
      qboAccounts = await fetchFromQBO();
      const enabledIds = new Set(enabled.map(a => a.qbo_account_id));
      qboAccounts = qboAccounts.map(a => ({
        ...a,
        _checked: enabledIds.has(a.qbo_account_id),
      }));
    } catch (err) {
      qboError = err.message || 'Could not fetch payment accounts from QBO.';
    } finally {
      loadingQBO = false;
    }
  }

  async function saveAccounts() {
    const toSave = qboAccounts
      .filter(a => a._checked)
      .map(({ _checked, ...rest }) => rest);
    await savePaymentAccounts(toSave);
    enabled = toSave;
    saveMessage = 'Payment accounts saved.';
  }

  loadSaved();
</script>

<h2>Settings</h2>

<QBOConnectionCard />

<AccountingCategoryMapping />

<UnitsManager />

<RateSchemeManager />

<TaskTemplateManager />

<h3>Payment accounts</h3>
<p>
  <button type="button" onclick={refreshFromQBO} disabled={loadingQBO}>
    {loadingQBO ? 'Loading...' : 'Refresh from QBO'}
  </button>
  {#if qboError}<em>{qboError}</em>{/if}
</p>

{#if qboAccounts.length > 0}
  <table border="1">
    <thead>
      <tr><th>Enabled</th><th>Name</th><th>Type</th></tr>
    </thead>
    <tbody>
      {#each qboAccounts as acct (acct.qbo_account_id)}
        <tr>
          <td><input type="checkbox" bind:checked={acct._checked}></td>
          <td><input type="text" bind:value={acct.display_name}></td>
          <td>{acct.account_type}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  <p><button type="button" onclick={saveAccounts}>Save</button>
  {#if saveMessage}<em>{saveMessage}</em>{/if}</p>
{:else if enabled.length > 0}
  <p>Currently configured:</p>
  <ul>
    {#each enabled as a (a.qbo_account_id)}
      <li>{a.display_name} ({a.account_type})</li>
    {/each}
  </ul>
{/if}
