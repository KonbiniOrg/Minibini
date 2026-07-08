<script>
  // Full-bleed banner for the contact/business detail pages, peered with
  // JobHeader — rendered by the route ABOVE the page-body wrapper so it runs
  // edge to edge. `name` is the contact name or business name.
  const { name, financials = null } = $props();

  function formatAmount(v) {
    if (v == null || v === '') return '$—';
    return Number(v).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  }

  let profitNum = $derived(financials?.profit == null ? null : Number(financials.profit));
</script>

<div class="customer-header">
  <h2 class="ch-name">{name}</h2>
  {#if financials}
    <div class="ch-numbers">
      <div class="ch-item">
        <div class="ch-label">Total Invoiced</div>
        <div class="ch-value ch-invoiced">{formatAmount(financials.invoiced)}</div>
      </div>
      <div class="ch-item">
        <div class="ch-label">Total Profit</div>
        <div class="ch-value" class:ch-profit-pos={profitNum != null && profitNum >= 0} class:ch-profit-neg={profitNum != null && profitNum < 0}>{formatAmount(financials.profit)}</div>
      </div>
    </div>
  {/if}
</div>

<style>
  .customer-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    /* Darkest red in the app's palette family (the job header is gray-800
       #1f2937; this is red-950). Each area gets its own header color. */
    background: #450a0a;
    padding: 14px 24px;
    margin-bottom: 16px;
  }
  .ch-name { font-size: 22px; font-weight: 700; color: #fff; margin: 0; padding-left: 52px; }
  .ch-numbers { display: flex; gap: 22px; }
  .ch-item { text-align: right; }
  .ch-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.6px; color: rgba(255,255,255,0.65); }
  .ch-value { font-size: 18px; font-weight: 700; margin-top: 2px; font-variant-numeric: tabular-nums; color: #fff; }
  .ch-invoiced { color: #86efac; }
  .ch-profit-pos { color: #86efac; }
  .ch-profit-neg { color: #fca5a5; }
</style>
