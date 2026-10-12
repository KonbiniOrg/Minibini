<script>
  // BusinessDetail — the body of /businesses/:id (contacts UI redesign,
  // 2026-10-10): identity panels (Contact / Billing / Tags) on the left,
  // CustomerActivity (Contacts → Recent Jobs → Open Invoices → POs → History)
  // on the right. The banner and its modals (edit / delete / New Job) are the
  // page's; this component hosts only the New Contact modal.
  import ContactFormModal from './ContactFormModal.svelte';
  import CustomerActivity from './CustomerActivity.svelte';
  import TagEditor from '../TagEditor.svelte';
  import { canManageJobs } from '../../stores/permissions.js';

  const {
    business,
    invoices = [],
    purchaseOrders = [],
    history = null,
    onAddNote = null,
    onSetDefault = null,
    onNewJobFor = null,
  } = $props();

  let newContactOpen = $state(false);

  const href = (url) => (/^https?:\/\//i.test(url) ? url : `https://${url}`);
  const hostOf = (url) => url.replace(/^https?:\/\//i, '').replace(/\/$/, '');
</script>

<div class="page-body customer-body">
  <aside class="identity">
    <div class="panel">
      <div class="panel-head">Contact</div>
      <dl class="facts">
        {#each business.phones || [] as p}<dt>{p.label || 'Phone'}</dt><dd>{p.number}</dd>{/each}
        {#if business.website}<dt>Web</dt><dd><a href={href(business.website)} target="_blank" rel="noopener">{hostOf(business.website)}</a></dd>{/if}
        {#if business.business_address}<dt>Address</dt><dd class="preserve-breaks">{business.business_address}</dd>{/if}
        {#if !(business.phones?.length) && !business.website && !business.business_address}
          <dd class="muted empty">No contact details.</dd>
        {/if}
      </dl>
    </div>
    <div class="panel">
      <div class="panel-head">Billing</div>
      <dl class="facts">
        {#if business.our_reference_code}<dt>Ref</dt><dd>{business.our_reference_code}</dd>{/if}
        <dt>Terms</dt><dd>{business.terms_name || 'None'}</dd>
        <dt>Tax</dt><dd>{business.tax_exemption_number ? `Exempt · ${business.tax_exemption_number}` : 'Not exempt'}</dd>
        <dt>Multiplier</dt><dd>{business.tax_multiplier ?? 'full rate'}</dd>
      </dl>
    </div>
    <div class="panel">
      <div class="panel-head">Tags</div>
      <TagEditor endpoint="/api/businesses/{business.business_id}" initialTags={business.tags || []}
        readonly={!$canManageJobs} />
    </div>
  </aside>

  <CustomerActivity
    jobs={business.jobs || []}
    {invoices}
    {purchaseOrders}
    contacts={business.contacts || []}
    defaultContactId={business.default_contact?.contact_id ?? null}
    showContactColumn={true}
    newPOHref="#/purchase-orders/new?business={business.business_id}"
    {history}
    {onAddNote}
    onNewContact={() => { newContactOpen = true; }}
    {onNewJobFor}
    {onSetDefault}
  />
</div>

<ContactFormModal open={newContactOpen} defaultBusinessId={business.business_id}
  onClose={() => { newContactOpen = false; }} />

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
  .facts .empty { grid-column: 1 / -1; }
  .muted { color: #64748b; }
  @media (max-width: 720px) {
    .customer-body { grid-template-columns: 1fr; }
  }
</style>
