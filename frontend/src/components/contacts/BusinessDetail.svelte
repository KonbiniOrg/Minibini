<script>
  import FullOnly from '../FullOnly.svelte';
  import HistoryPanel from '../HistoryPanel.svelte';
  import TagEditor from '../TagEditor.svelte';
  import { canManageJobs } from '../../stores/permissions.js';
  import { viewMode } from '../../stores/viewMode.js';
  import { pageFromUrl, pageRange } from '../../lib/pagination.js';
  const {
    business,
    invoices = null,
    purchaseOrders = null,
    bills = null,
    history = null,
    onEdit = null,
    onDelete = null,
    onInvoicePageChange = null,
    onPOPageChange = null,
    onBillPageChange = null,
    onAddNote = null,
  } = $props();

  const closedJobStatuses = ['completed', 'cancelled'];
  const closedInvoiceStatuses = ['paid', 'cancelled', 'superseded'];
  const closedPOStatuses = ['received_in_full', 'cancelled'];
  const closedBillStatuses = ['paid_in_full', 'cancelled', 'refunded'];

  function formatAmount(v) {
    if (v == null || v === '') return '$—';
    return Number(v).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  }


  let visibleJobs = $derived(
    business.jobs
      ? $viewMode === 'full'
        ? business.jobs
        : business.jobs.filter(j => !closedJobStatuses.includes(j.status))
      : []
  );

  let visibleInvoices = $derived(
    invoices?.results
      ? $viewMode === 'full'
        ? invoices.results
        : invoices.results.filter(inv => !closedInvoiceStatuses.includes(inv.status))
      : []
  );

  let visiblePOs = $derived(
    purchaseOrders?.results
      ? $viewMode === 'full'
        ? purchaseOrders.results
        : purchaseOrders.results.filter(po => !closedPOStatuses.includes(po.status))
      : []
  );

  let visibleBills = $derived(
    bills?.results
      ? $viewMode === 'full'
        ? bills.results
        : bills.results.filter(b => !closedBillStatuses.includes(b.status))
      : []
  );


</script>

<div class="page-body">
<dl>
  <dt>Reference Code</dt>
  <dd>{business.our_reference_code}</dd>

  <dt>Name</dt>
  <dd>{business.business_name}</dd>

  <dt>Phone</dt>
  <dd>{business.business_phone}</dd>

  <dt>Address</dt>
  <dd class="preserve-breaks">{business.business_address}</dd>

  <dt>Website</dt>
  <dd>{business.website}</dd>

  <dt>Tax Exemption</dt>
  <dd>{business.tax_exemption_number || "(Not exempt)"}</dd>

  <dt>Tax Multiplier</dt>
  <dd>{business.tax_multiplier ?? '(full rate)'}</dd>

  <dt>Payment Terms</dt>
  <dd>{business.terms || 'None'}</dd>

  <dt>Default Contact</dt>
  <dd><a href="#/contacts/{business.default_contact.contact_id}">{business.default_contact.name}</a></dd>
</dl>

<h3>Tags</h3>
<TagEditor endpoint="/api/businesses/{business.business_id}" initialTags={business.tags || []}
  readonly={!$canManageJobs} />

<FullOnly>
  <h3>Contacts</h3>
  {#if business.contacts && business.contacts.length > 0}
    <table class="data-table">
      <thead>
        <tr><th>Name</th><th>Email</th><th>Phone</th></tr>
      </thead>
      <tbody>
        {#each business.contacts as contact}
          <tr>
            <td>
              <a href="#/contacts/{contact.contact_id}">{contact.name}</a>
              {#if business.default_contact && contact.contact_id === business.default_contact.contact_id}
                <strong>(default)</strong>
              {/if}
            </td>
            <td>{contact.email || ''}</td>
            <td>{contact.mobile_number || ''}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p>No contacts.</p>
  {/if}
</FullOnly>

<h3>Jobs</h3>
{#if visibleJobs.length > 0}
  <table class="data-table">
    <thead>
      <tr><th>Job #</th><th>Name</th><th>Status</th></tr>
    </thead>
    <tbody>
      {#each visibleJobs as job}
        <tr>
          <td><a href="#/jobs/{job.job_id}">{job.job_number}</a></td>
          <td>{job.name}</td>
          <td>{job.status}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{:else}
  <p>No {$viewMode === 'lite' ? 'open ' : ''}jobs.</p>
{/if}

<h3>Invoices</h3>
{#if visibleInvoices.length > 0}
  <table class="data-table">
    <thead>
      <tr><th>Invoice #</th><th>Job</th><th>Status</th><th>Total</th><th>Paid</th><th>Balance</th></tr>
    </thead>
    <tbody>
      {#each visibleInvoices as inv}
        <tr>
          <td><a href="#/invoices/{inv.invoice_id}">{inv.invoice_number}</a></td>
          <td><a href="#/jobs/{inv.job}">{inv.job_number}</a></td>
          <td>{inv.status}</td>
          <td>{formatAmount(inv.total)}</td>
          <td>{formatAmount(inv.amount_paid)}</td>
          <td>{formatAmount(inv.balance)}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if invoices}
    <p>
      {pageRange(invoices)}
      {#if invoices.previous}
        | <button type="button" onclick={() => onInvoicePageChange(pageFromUrl(invoices.previous))}>Previous</button>
      {/if}
      {#if invoices.next}
        | <button type="button" onclick={() => onInvoicePageChange(pageFromUrl(invoices.next))}>Next</button>
      {/if}
    </p>
  {/if}
{:else}
  <p>No {$viewMode === 'lite' ? 'open ' : ''}invoices.</p>
{/if}

<h3>Purchase Orders</h3>
{#if visiblePOs.length > 0}
  <table class="data-table">
    <thead>
      <tr><th>PO #</th><th>Status</th></tr>
    </thead>
    <tbody>
      {#each visiblePOs as po}
        <tr>
          <td><a href="#/purchase-orders/{po.po_id}">{po.po_number}</a></td>
          <td>{po.status}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if purchaseOrders}
    <p>
      {pageRange(purchaseOrders)}
      {#if purchaseOrders.previous}
        | <button type="button" onclick={() => onPOPageChange(pageFromUrl(purchaseOrders.previous))}>Previous</button>
      {/if}
      {#if purchaseOrders.next}
        | <button type="button" onclick={() => onPOPageChange(pageFromUrl(purchaseOrders.next))}>Next</button>
      {/if}
    </p>
  {/if}
{:else}
  <p>No {$viewMode === 'lite' ? 'open ' : ''}purchase orders.</p>
{/if}

<h3>Bills</h3>
{#if visibleBills.length > 0}
  <table class="data-table">
    <thead>
      <tr><th>Vendor Invoice</th><th>Status</th></tr>
    </thead>
    <tbody>
      {#each visibleBills as bill}
        <tr>
          <td><a href="#/bills/{bill.bill_id}">{bill.vendor_invoice_number || `Bill ${bill.bill_id}`}</a></td>
          <td>{bill.status}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if bills}
    <p>
      {pageRange(bills)}
      {#if bills.previous}
        | <button type="button" onclick={() => onBillPageChange(pageFromUrl(bills.previous))}>Previous</button>
      {/if}
      {#if bills.next}
        | <button type="button" onclick={() => onBillPageChange(pageFromUrl(bills.next))}>Next</button>
      {/if}
    </p>
  {/if}
{:else}
  <p>No {$viewMode === 'lite' ? 'open ' : ''}bills.</p>
{/if}

<HistoryPanel {history} {onAddNote} />

<p>
  {#if onEdit && $canManageJobs}
    <button onclick={onEdit}>Edit</button>
  {/if}
  {#if onDelete && $canManageJobs}
    <button onclick={onDelete}>Delete</button>
  {/if}
</p>
</div>

<style>
</style>
