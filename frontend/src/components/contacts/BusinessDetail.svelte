<script>
  import FullOnly from '../FullOnly.svelte';
  import DataTable from '../DataTable.svelte';
  import HistoryPanel from '../HistoryPanel.svelte';
  import TagEditor from '../TagEditor.svelte';
  import { canManageJobs, canManageFinancials } from '../../stores/permissions.js';
  import { viewMode } from '../../stores/viewMode.js';
  import { pageFromUrl, pageRange } from '../../lib/pagination.js';
  const {
    business,
    invoices = null,
    purchaseOrders = null,
    history = null,
    onEdit = null,
    onDelete = null,
    onInvoicePageChange = null,
    onPOPageChange = null,
    onAddNote = null,
  } = $props();

  const closedJobStatuses = ['completed', 'cancelled'];
  const closedInvoiceStatuses = ['paid', 'cancelled', 'superseded'];
  const closedPOStatuses = ['received_in_full', 'cancelled'];

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
  <h3>Contacts
    {#if $canManageJobs}
      — <a href="#/contacts/new?business={business.business_id}">New Contact</a>
    {/if}
  </h3>
  <DataTable
    rows={business.contacts || []}
    key={(contact) => contact.contact_id}
    emptyText="No contacts."
    columns={[
      { id: 'name',  label: 'Name',  cell: contactNameCell },
      { id: 'email', label: 'Email', field: 'email' },
      { id: 'phone', label: 'Phone', field: 'mobile_number' },
    ]}
  />
</FullOnly>

<h3>Jobs
  {#if $canManageJobs && business.default_contact}
    — <a href="#/jobs/new?contact={business.default_contact.contact_id}">New Job</a>
  {/if}
</h3>
<DataTable
  rows={visibleJobs}
  key={(job) => job.job_id}
  emptyText={`No ${$viewMode === 'lite' ? 'open ' : ''}jobs.`}
  columns={[
    { id: 'number', label: 'Job #',  cell: jobNumberCell },
    { id: 'name',   label: 'Name',   field: 'name' },
    { id: 'status', label: 'Status', field: 'status' },
  ]}
/>

<h3>Invoices</h3>
<DataTable
  rows={visibleInvoices}
  key={(inv) => inv.invoice_id}
  emptyText={`No ${$viewMode === 'lite' ? 'open ' : ''}invoices.`}
  columns={[
    { id: 'number',  label: 'Invoice #', cell: invNumberCell },
    { id: 'job',     label: 'Job',       cell: invJobCell },
    { id: 'status',  label: 'Status',    field: 'status' },
    { id: 'total',   label: 'Total',     cell: invTotalCell },
    { id: 'paid',    label: 'Paid',      cell: invPaidCell },
    { id: 'balance', label: 'Balance',   cell: invBalanceCell },
  ]}
/>
{#if visibleInvoices.length > 0}
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
{/if}

<h3>Purchase Orders
  {#if $canManageFinancials}
    — <a href="#/purchase-orders/new?business={business.business_id}">New Purchase Order</a>
  {/if}
</h3>
<DataTable
  rows={visiblePOs}
  key={(po) => po.po_id}
  emptyText={`No ${$viewMode === 'lite' ? 'open ' : ''}purchase orders.`}
  columns={[
    { id: 'number', label: 'PO #',   cell: poNumberCell },
    { id: 'status', label: 'Status', field: 'status' },
  ]}
/>
{#if visiblePOs.length > 0}
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


{#snippet jobNumberCell(job)}<a href="#/jobs/{job.job_id}">{job.job_number}</a>{/snippet}
{#snippet invNumberCell(inv)}<a href="#/invoices/{inv.invoice_id}">{inv.display_number}</a>{/snippet}
{#snippet invJobCell(inv)}<a href="#/jobs/{inv.job}">{inv.job_number}</a>{/snippet}
{#snippet invTotalCell(inv)}{formatAmount(inv.total)}{/snippet}
{#snippet invPaidCell(inv)}{formatAmount(inv.amount_paid)}{/snippet}
{#snippet invBalanceCell(inv)}{formatAmount(inv.balance)}{/snippet}
{#snippet poNumberCell(po)}<a href="#/purchase-orders/{po.po_id}">{po.po_number}</a>{/snippet}
{#snippet contactNameCell(contact)}
  <a href="#/contacts/{contact.contact_id}">{contact.name}</a>
  {#if business.default_contact && contact.contact_id === business.default_contact.contact_id}
    <strong>(default)</strong>
  {/if}
{/snippet}

<style>
</style>
