<script>
  import { api, errorMessage } from '../lib/api.js';
  import { getPaymentAccounts } from '../lib/paymentAccounts.js';
  import PaymentAccountSelect from './qbo/PaymentAccountSelect.svelte';
  let { open = false, billId, defaultAmount = '', onSaved = () => {}, onClose = () => {} } = $props();

  let amount = $state('');
  let paymentAccountId = $state('');
  let reference = $state('');
  let paymentDate = $state(new Date().toISOString().slice(0, 10));
  let error = $state('');

  // A payment account is necessary info — if none are configured we can't record
  // a payment, so the modal explains that instead of showing the form.
  let accounts = $state([]);
  let accountsLoaded = $state(false);

  $effect(() => { amount = defaultAmount; });
  $effect(() => {
    if (open && !accountsLoaded) {
      getPaymentAccounts().then((a) => {
        accounts = a;
        if (a.length > 0 && !paymentAccountId) paymentAccountId = a[0].qbo_account_id;
        accountsLoaded = true;
      });
    }
  });

  async function save() {
    error = '';
    if (!amount || Number(amount) <= 0) { error = 'Amount must be greater than zero.'; return; }
    if (!paymentAccountId) { error = 'Choose a payment account.'; return; }
    try {
      const payment = await api.post(`/api/bills/${billId}/payments/`, {
        amount, payment_account_id: paymentAccountId, reference,
        payment_date: new Date(paymentDate).toISOString(),
      });
      onSaved(payment);
    } catch (e) {
      error = errorMessage(e, 'Could not record payment.');
    }
  }
</script>

{#if open}
<div class="modal-backdrop">
  <div class="modal">
    <h3>Record Payment</h3>
    {#if error}<p class="error">{error}</p>{/if}
    {#if accountsLoaded && accounts.length === 0}
      <p>No payment accounts are configured. Set them up in
        <strong>Settings → QuickBooks</strong> before recording payments.</p>
      <div class="actions">
        <button onclick={onClose}>Close</button>
      </div>
    {:else}
      <label>Amount<input bind:value={amount} type="text" inputmode="decimal" /></label>
      <label>Payment Account
        <PaymentAccountSelect bind:value={paymentAccountId} required={true} />
      </label>
      <label>Reference<input bind:value={reference} /></label>
      <label>Date<input bind:value={paymentDate} type="date" /></label>
      <div class="actions">
        <button onclick={save}>Save</button>
        <button onclick={onClose}>Cancel</button>
      </div>
    {/if}
  </div>
</div>
{/if}

<style>
  .error { color: #b00; }
  .modal-backdrop {
    position: fixed; inset: 0; background: rgba(0,0,0,0.4);
    display: flex; align-items: center; justify-content: center; z-index: var(--z-modal, 100);
  }
  .modal { background: white; padding: 16px; max-width: 400px; width: 90%; border: 1px solid #ccc; }
  .modal label { display: block; margin-bottom: 10px; }
  .actions { display: flex; gap: 8px; margin-top: 12px; }
</style>
