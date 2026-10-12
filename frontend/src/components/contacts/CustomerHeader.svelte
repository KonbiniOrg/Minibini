<script>
  // Full-bleed banner for the contact/business detail pages, peered with
  // JobHeader — rendered by the route ABOVE the page-body wrapper so it runs
  // edge to edge (contacts UI redesign, 2026-10-10).
  //
  // Left: name, subtitle (counterpart link — the contact's business or the
  // business's default contact — plus the "default contact" chip / contact
  // count), then the action row the page supplies via the `actions` snippet
  // (New Job button, Edit, Deactivate/Reactivate, Delete…). Right: the facts line
  // ("Customer since … · Last job started … · Net 30") over the numbers box
  // (open jobs / outstanding / invoiced / profit) — all from the financials
  // endpoint's rollup; see lib/customerActivity.js for the facts rule.
  import { customerFacts } from '../../lib/customerActivity.js';
  import { formatMoney } from '../../lib/format.js';

  const {
    name,
    kind = 'business',
    business = null,
    defaultContact = null,
    isDefaultContact = false,
    contactCount = null,
    terms = null,
    financials = null,
    actions = null,
    inactive = false,
  } = $props();

  const money = (v) => (v == null || v === '' ? '$—' : formatMoney(v));

  let profitNum = $derived(financials?.profit == null ? null : Number(financials.profit));
  let facts = $derived(customerFacts(financials, { kind, terms }));
</script>

<div class="customer-header">
  <div class="titleblock">
    <h2 class="ch-name" title={name}>{name}</h2>
    {#if inactive}<span class="status-badge status-inactive">inactive</span>{/if}
    {#if business}
      <p class="ch-subtitle">
        at <a href="#/businesses/{business.business_id}">{business.business_name}</a>
        {#if isDefaultContact}<span class="ch-chip">default contact</span>{/if}
      </p>
    {:else if kind === 'contact'}
      <p class="ch-subtitle">(individual)</p>
    {:else if defaultContact}
      <p class="ch-subtitle">
        default contact: <a href="#/contacts/{defaultContact.contact_id}">{defaultContact.name}</a>
        {#if contactCount != null} · {contactCount} {contactCount === 1 ? 'contact' : 'contacts'}{/if}
      </p>
    {/if}
    {#if actions}
      <div class="ch-actions">{@render actions()}</div>
    {/if}
  </div>
  <div class="factblock">
    {#if facts}<div class="facts-line">{facts}</div>{/if}
    {#if financials}
      <div class="ch-numbers">
        <div class="ch-item">
          <div class="ch-label">Open jobs</div>
          <div class="ch-value">{financials.open_jobs ?? '—'}</div>
        </div>
        <div class="ch-item">
          <div class="ch-label">Outstanding</div>
          <div class="ch-value ch-owed">{money(financials.outstanding)}</div>
        </div>
        <div class="ch-item">
          <div class="ch-label">Invoiced</div>
          <div class="ch-value ch-invoiced">{money(financials.invoiced)}</div>
        </div>
        <div class="ch-item">
          <div class="ch-label">Profit</div>
          <div class="ch-value" class:ch-profit-pos={profitNum != null && profitNum >= 0} class:ch-profit-neg={profitNum != null && profitNum < 0}>{money(financials.profit)}</div>
        </div>
      </div>
    {/if}
  </div>
</div>

<style>
  .customer-header {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 24px;
    align-items: center;
    /* Darkest red in the app's palette family (the job header is gray-800
       #1f2937; this is red-950). Each area gets its own header color. */
    background: #450a0a;
    color: #fff;
    padding: 14px 24px;
  }
  .titleblock { padding-left: 52px; min-width: 0; }
  .ch-name {
    font-size: 22px; font-weight: 700; color: #fff; margin: 0;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .ch-subtitle { font-size: 13px; opacity: 0.85; color: #fff; margin: 2px 0 0; }
  .ch-subtitle a { color: #fff; text-decoration: underline; }
  .ch-chip {
    display: inline-block; margin-left: 6px; padding: 1px 8px; border-radius: 999px;
    font-size: 11px; font-weight: 600; background: #fde68a; color: #78350f;
  }
  /* The action row. The page's snippet supplies: one `.banner-btn` (New Job)
     and quiet `.edit-link .header-action` buttons (Edit, Deactivate/Reactivate, Delete…). */
  .ch-actions { margin-top: 10px; display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
  .ch-actions :global(.banner-btn) {
    font: inherit; font-size: 13px; font-weight: 600;
    padding: 6px 16px; border-radius: 5px; cursor: pointer;
    background: #fff; color: #450a0a; border: 1px solid #fff;
  }
  .ch-actions :global(.banner-btn:hover) { background: #fee2e2; }
  .ch-actions :global(.edit-link) { margin-left: 0; }
  .ch-actions :global(.edit-link.danger) { color: #fecaca; }
  .ch-actions :global(.edit-link:disabled) { cursor: default; opacity: 0.45; text-decoration: none; }

  .factblock { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
  .facts-line { font-size: 13px; opacity: 0.9; white-space: nowrap; }
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
  .ch-owed { color: #fcd34d; }
  .ch-invoiced { color: #86efac; }
  .ch-profit-pos { color: #86efac; }
  .ch-profit-neg { color: #fca5a5; }

  @media (max-width: 720px) {
    .customer-header { grid-template-columns: 1fr; }
    .titleblock { padding-left: 0; }
    .ch-name { white-space: normal; }
    .factblock { align-items: flex-start; }
    .facts-line { white-space: normal; }
    .ch-numbers { flex-wrap: wrap; gap: 12px; }
  }
</style>
