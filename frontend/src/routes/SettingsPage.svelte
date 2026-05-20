<script>
  import QBOConnectionCard from '../components/QBOConnectionCard.svelte';
  import AccountingCategories from '../components/settings/AccountingCategories.svelte';
  import UnitsManager from '../components/UnitsManager.svelte';
  import RateSchemeManager from '../components/RateSchemeManager.svelte';
  import TaskTemplateManager from '../components/TaskTemplateManager.svelte';
  import ScheduleSettings from '../components/settings/ScheduleSettings.svelte';
  import { fetchFromQBO, savePaymentAccounts, getPaymentAccounts } from '../lib/paymentAccounts.js';

  let tab = $state('accounting');

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

<nav class="settings-tabs">
  <button class:active={tab === 'accounting'} onclick={() => tab = 'accounting'}>Accounting</button>
  <button class:active={tab === 'setup'} onclick={() => tab = 'setup'}>Setup</button>
  <button class:active={tab === 'catalog'} onclick={() => tab = 'catalog'}>Catalog</button>
  <button class:active={tab === 'schedule'} onclick={() => tab = 'schedule'}>Schedule</button>
</nav>

{#if tab === 'accounting'}
  <QBOConnectionCard />

  <AccountingCategories />

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

  <h3>Tax settings</h3>
  <p><em>Not yet implemented in Svelte. <a href="/settings/tax/">Edit tax settings (legacy)</a></em></p>

{:else if tab === 'setup'}
  <UnitsManager />

  <RateSchemeManager />

{:else if tab === 'catalog'}
  <TaskTemplateManager />

  <h3>Work templates</h3>
  <p><em>Not yet implemented in Svelte. <a href="/estimates/templates/">Work templates (legacy)</a></em></p>

  <h3>Price list items</h3>
  <p><em>Not yet implemented in Svelte. <a href="/inventory/price-list-items/">Price list items (legacy)</a></em></p>

{:else if tab === 'schedule'}
  <ScheduleSettings />
{/if}

<style>
  .settings-tabs {
    display: flex;
    gap: 0;
    border-bottom: 2px solid #ccc;
    margin-bottom: 1em;
  }
  .settings-tabs button {
    padding: 0.4em 1.2em;
    border: 2px solid #ccc;
    border-bottom: none;
    background: #f5f5f5;
    cursor: pointer;
    margin-bottom: -2px;
  }
  .settings-tabs button.active {
    background: white;
    border-bottom: 2px solid white;
    font-weight: bold;
  }
</style>
