<script>
  // Full-bleed banner for the contact/business detail pages, peered with
  // JobHeader — rendered by the route ABOVE the page-body wrapper so it runs
  // edge to edge. `name` is the contact name or business name. The subtitle
  // slot holds the counterpart link: `business` on contact pages (falling
  // back to "(individual)" when kind==='contact' and there is none),
  // `defaultContact` on business pages.
  const { name, kind = 'business', business = null, defaultContact = null, financials = null } = $props();

  function formatAmount(v) {
    if (v == null || v === '') return '$—';
    return Number(v).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  }

  let profitNum = $derived(financials?.profit == null ? null : Number(financials.profit));
</script>

<div class="customer-header">
  <div class="titleblock">
    <h2 class="ch-name">{name}</h2>
    {#if business}
      <p class="ch-subtitle">at <a href="#/businesses/{business.business_id}">{business.business_name}</a></p>
    {:else if kind === 'contact'}
      <p class="ch-subtitle">(individual)</p>
    {:else if defaultContact}
      <p class="ch-subtitle">default contact: <a href="#/contacts/{defaultContact.contact_id}">{defaultContact.name}</a></p>
    {/if}
  </div>
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
  .titleblock { padding-left: 52px; min-width: 0; }
  .ch-name {
    font-size: 22px; font-weight: 700; color: #fff; margin: 0;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .ch-subtitle { font-size: 13px; opacity: 0.85; color: #fff; margin: 2px 0 0; }
  .ch-subtitle a { color: #fff; text-decoration: underline; }
  /* Same surround treatment as JobHeader's money grid. */
  .ch-numbers {
    display: flex;
    gap: 22px;
    background: rgba(255,255,255,0.06);
    padding: 8px 18px;
    border-radius: 8px;
    border: 1px solid rgba(255,255,255,0.08);
  }
  .ch-item { text-align: right; }
  .ch-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.6px; color: rgba(255,255,255,0.65); }
  .ch-value { font-size: 18px; font-weight: 700; margin-top: 2px; font-variant-numeric: tabular-nums; color: #fff; }
  .ch-invoiced { color: #86efac; }
  .ch-profit-pos { color: #86efac; }
  .ch-profit-neg { color: #fca5a5; }
</style>
