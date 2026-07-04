<script>
  import { api, errorMessage } from '../lib/api.js';
  import Modal from './Modal.svelte';
  import { getPaymentAccounts } from '../lib/paymentAccounts.js';
  import PaymentAccountSelect from './qbo/PaymentAccountSelect.svelte';
  let { open = false, billId, defaultAmount = '', onSaved = () => {}, onClose = () => {} } = $props();

  let amount = $state('');
  let paymentAccountId = $state('');
  let reference = $state('');
  let paymentDate = $state(new Date().toISOString().slice(0, 10));
  let error = $state('');
  let busy = $state(false);

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
    busy = true;
    try {
      const payment = await api.post(`/api/bills/${billId}/payments/`, {
        amount, payment_account_id: paymentAccountId, reference,
        payment_date: new Date(paymentDate).toISOString(),
      });
      onSaved(payment);
    } catch (e) {
      error = errorMessage(e, 'Could not record payment.');
    } finally {
      busy = false;
    }
  }
</script>

<Modal {open} onSave={save} {busy} onCancel={onClose} maxWidth="600px">
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
        <button onclick={save} disabled={busy}>Save</button>
        <button onclick={onClose}>Cancel</button>
      </div>
    {/if}
</Modal>


<style>
  .error { color: #b00; }
  .modal label { display: block; margin-bottom: 10px; }
  .actions { display: flex; gap: 8px; margin-top: 12px; }
</style>
