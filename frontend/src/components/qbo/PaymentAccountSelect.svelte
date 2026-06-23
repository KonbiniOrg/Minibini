<script>
  import { getPaymentAccounts } from '../../lib/paymentAccounts.js';
  let { value = $bindable(''), required = false, id = 'payment-account' } = $props();
  let accounts = $state([]);
  let loaded = $state(false);
  $effect(() => {
    getPaymentAccounts().then(a => {
      accounts = a;
      loaded = true;
    });
  });
</script>

{#if loaded}
  {#if accounts.length === 0}
    <select {id} disabled><option>No payment accounts configured</option></select>
  {:else}
    <select {id} bind:value {required}>
      <option value="">— select account —</option>
      {#each accounts as a (a.qbo_account_id)}
        <option value={a.qbo_account_id}>{a.display_name}</option>
      {/each}
    </select>
  {/if}
{/if}
