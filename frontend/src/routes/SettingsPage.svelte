<script>
  import QBOConnectionCard from '../components/QBOConnectionCard.svelte';
  import QBOSyncFailures from '../components/qbo/QBOSyncFailures.svelte';
  import AccountingCategories from '../components/settings/AccountingCategories.svelte';
  import UnitsManager from '../components/UnitsManager.svelte';
  import RateSchemeManager from '../components/RateSchemeManager.svelte';
  import EmailAccountSettings from '../components/settings/EmailAccountSettings.svelte';
  import ScheduleSettings from '../components/settings/ScheduleSettings.svelte';
  import EmailTemplates from '../components/settings/EmailTemplates.svelte';
  import BusinessSettings from '../components/settings/BusinessSettings.svelte';
  import GeneralSettings from '../components/settings/GeneralSettings.svelte';
  import MaterialMarkupSetting from '../components/settings/MaterialMarkupSetting.svelte';
  import DefaultMaterialCategorySetting from '../components/settings/DefaultMaterialCategorySetting.svelte';
  import DefaultDepositCategorySetting from '../components/settings/DefaultDepositCategorySetting.svelte';
  import FallbackAccountingCategorySetting from '../components/settings/FallbackAccountingCategorySetting.svelte';
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

<div class="page-body">
<h2>Settings</h2>

<nav class="page-tabs">
  <button class:active={tab === 'accounting'} onclick={() => tab = 'accounting'}>Accounting</button>
  <button class:active={tab === 'setup'} onclick={() => tab = 'setup'}>Setup</button>
  <button class:active={tab === 'pricing'} onclick={() => tab = 'pricing'}>Pricing</button>
  <button class:active={tab === 'schedule'} onclick={() => tab = 'schedule'}>Schedule</button>
  <button class:active={tab === 'email'} onclick={() => tab = 'email'}>Email</button>
  <button class:active={tab === 'business'} onclick={() => tab = 'business'}>Business</button>
</nav>

{#if tab === 'accounting'}
  <QBOConnectionCard />

  <QBOSyncFailures />

  <AccountingCategories />

  <DefaultMaterialCategorySetting />

  <DefaultDepositCategorySetting />

  <FallbackAccountingCategorySetting />

  <h3>Payment accounts</h3>
<p>
  <button type="button" onclick={refreshFromQBO} disabled={loadingQBO}>
    {loadingQBO ? 'Loading...' : 'Refresh from QBO'}
  </button>
  {#if qboError}<em>{qboError}</em>{/if}
</p>

  {#if qboAccounts.length > 0}
    <table class="data-table">
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
  <p><em>Taxation is handled by QuickBooks — there are no app-side tax settings.</em></p>

{:else if tab === 'setup'}
  <GeneralSettings />

  <UnitsManager />

{:else if tab === 'pricing'}
  <MaterialMarkupSetting />

  <DefaultMaterialCategorySetting />

  <RateSchemeManager />

{:else if tab === 'schedule'}
  <ScheduleSettings />

{:else if tab === 'email'}
  <EmailAccountSettings />

  <EmailTemplates />
{:else if tab === 'business'}
  <BusinessSettings />
{/if}
</div>

<style>
  /* Tab strip is the shared .page-tabs (app.css). */
</style>
