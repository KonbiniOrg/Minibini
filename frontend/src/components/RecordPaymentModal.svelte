<script>
  import { api } from '../lib/api.js';
  import PaymentAccountSelect from './qbo/PaymentAccountSelect.svelte';
  let { open = false, billId, defaultAmount = '', onSaved = () => {}, onClose = () => {} } = $props();

  let amount = $state('');
  let paymentAccountId = $state('');
  let reference = $state('');
  let paymentDate = $state(new Date().toISOString().slice(0, 10));
  let error = $state('');

  $effect(() => { amount = defaultAmount; });

  async function save() {
    error = '';
    if (!amount || Number(amount) <= 0) { error = 'Amount must be greater than zero.'; return; }
    try {
      const payment = await api.post(`/api/bills/${billId}/payments/`, {
        amount, payment_account_id: paymentAccountId, reference,
        payment_date: new Date(paymentDate).toISOString(),
      });
      onSaved(payment);
    } catch (e) {
      error = e?.data?.detail || 'Could not record payment.';
    }
  }
</script>

{#if open}
<div class="modal-backdrop">
  <div class="modal">
    <h3>Record Payment</h3>
    {#if error}<p class="error">{error}</p>{/if}
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
