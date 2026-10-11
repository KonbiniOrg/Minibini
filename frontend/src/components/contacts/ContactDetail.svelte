<script>
  // ContactDetail — the body of /contacts/:id (contacts UI redesign,
  // 2026-10-10): identity panels (Contact / Business / Tags) on the left,
  // CustomerActivity (Recent Jobs → Open Invoices → POs → History) on the
  // right. `business` is the contact's business DETAIL payload (contacts[] +
  // jobs[]), fetched by the page so the "Also here" list can show job counts
  // without a new endpoint. The banner and its modals are the page's.
  import CustomerActivity from './CustomerActivity.svelte';
  import TagEditor from '../TagEditor.svelte';
  import { canManageJobs } from '../../stores/permissions.js';
  import { siblingJobCounts } from '../../lib/customerActivity.js';

  const {
    contact,
    business = null,
    invoices = [],
    purchaseOrders = [],
    history = null,
    onAddNote = null,
  } = $props();

  let siblings = $derived(siblingJobCounts(business, contact.contact_id));
  let hasAddress = $derived(!!(contact.addr1 || contact.city || contact.postal_code));
  // "City, Municipality Postal" — built here because whitespace at {#if}
  // block edges doesn't survive the template.
  let cityLine = $derived(
    [[contact.city, contact.municipality].filter(Boolean).join(', '), contact.postal_code]
      .filter(Boolean).join(' ')
  );
  let businessLine = $derived([
    business?.business_phone || null,
    business?.terms_name || null,
    business ? (business.tax_exemption_number ? 'tax exempt' : null) : null,
  ].filter(Boolean).join(' · '));

  let copied = $state(false);
  async function copyEmail() {
    try {
      await navigator.clipboard?.writeText(contact.email);
      copied = true;
      setTimeout(() => { copied = false; }, 1200);
    } catch { /* clipboard unavailable — the address is still selectable text */ }
  }
</script>

<div class="page-body customer-body">
  <aside class="identity">
    <div class="panel">
      <div class="panel-head">Contact</div>
      <dl class="facts">
        <dt>Email</dt>
        <dd>
          <a href="mailto:{contact.email}">{contact.email}</a>
          <button type="button" class="copy" onclick={copyEmail}>{copied ? 'copied' : 'copy'}</button>
        </dd>
        {#if contact.mobile_number}<dt>Mobile</dt><dd><a href="tel:{contact.mobile_number}">{contact.mobile_number}</a></dd>{/if}
        {#if contact.work_number}<dt>Work</dt><dd><a href="tel:{contact.work_number}">{contact.work_number}</a></dd>{/if}
        {#if contact.home_number}<dt>Home</dt><dd><a href="tel:{contact.home_number}">{contact.home_number}</a></dd>{/if}
        {#if hasAddress}
          <dt>Address</dt>
          <dd>
            {#if contact.addr1}{contact.addr1}<br>{/if}
            {#if contact.addr2}{contact.addr2}<br>{/if}
            {#if contact.addr3}{contact.addr3}<br>{/if}
            {#if cityLine}{cityLine}{/if}
            {#if contact.country_code}<br>{contact.country_code}{/if}
          </dd>
        {/if}
      </dl>
    </div>

    {#if contact.business}
      <div class="panel">
        <div class="panel-head">Business</div>
        <div class="business-card">
          <a class="name" href="#/businesses/{contact.business.business_id}">{contact.business.business_name}</a>
          {#if businessLine}<span class="line">{businessLine}</span>{/if}
          {#if siblings.length > 0}
            <div class="also">Also here</div>
            <ul class="siblings">
              {#each siblings as s (s.contact_id)}
                <li>
                  <a href="#/contacts/{s.contact_id}">{s.name}</a>
                  <small>{s.jobCount === 0 ? 'no jobs' : s.jobCount === 1 ? '1 job' : `${s.jobCount} jobs`}</small>
                </li>
              {/each}
            </ul>
          {/if}
        </div>
      </div>
    {/if}

    <div class="panel">
      <div class="panel-head">Tags</div>
      <TagEditor endpoint="/api/contacts/{contact.contact_id}" initialTags={contact.tags || []}
        readonly={!$canManageJobs} />
    </div>
  </aside>

  <CustomerActivity
    jobs={contact.jobs || []}
    {invoices}
    {purchaseOrders}
    newPOHref={contact.business ? `#/purchase-orders/new?business=${contact.business.business_id}&contact=${contact.contact_id}` : null}
    {history}
    {onAddNote}
  />
</div>

<style>
  .customer-body {
    padding-top: 16px;
    display: grid;
    grid-template-columns: 300px minmax(0, 1fr);
    gap: 18px;
    align-items: start;
  }
  .identity { display: grid; gap: 12px; }
  .facts { grid-template-columns: auto 1fr; gap: 6px 12px; margin: 0; font-size: 13px; }
  .facts dt { color: #64748b; font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; padding-top: 2px; }
  .facts dd { min-width: 0; overflow-wrap: anywhere; }
  .copy {
    font: inherit; font-size: 10px; border: 1px solid #d1d5db; background: #fff; border-radius: 3px;
    padding: 0 5px; margin-left: 6px; cursor: pointer; color: #64748b;
  }
  .copy:hover { background: #f3f4f6; }
  .business-card { display: grid; gap: 4px; font-size: 13px; }
  .business-card .name { font-weight: 700; font-size: 14px; }
  .business-card .line { color: #64748b; }
  .also { margin-top: 6px; padding-top: 8px; border-top: 1px dashed #e5e7eb; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: #888; }
  .siblings { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
  .siblings li { display: flex; justify-content: space-between; gap: 8px; }
  .siblings small { color: #94a3b8; }
  @media (max-width: 720px) {
    .customer-body { grid-template-columns: 1fr; }
  }
</style>
