<script>
  import FullOnly from '../FullOnly.svelte';
  import DataTable from '../DataTable.svelte';
  import HistoryPanel from '../HistoryPanel.svelte';
  import TagEditor from '../TagEditor.svelte';
  import { canManageJobs, canManageFinancials } from '../../stores/permissions.js';
  import { viewMode } from '../../stores/viewMode.js';
  import { pageFromUrl, pageRange } from '../../lib/pagination.js';
  const {
    contact,
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
    contact.jobs
      ? $viewMode === 'full'
        ? contact.jobs
        : contact.jobs.filter(j => !closedJobStatuses.includes(j.status))
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
  <dt>Name</dt>
  <dd>{contact.name}</dd>

  <dt>Email</dt>
  <dd>{contact.email}</dd>

  {#if contact.work_number}
    <dt>Work</dt>
    <dd>{contact.work_number}</dd>
  {/if}

  {#if contact.mobile_number}
    <dt>Mobile</dt>
    <dd>{contact.mobile_number}</dd>
  {/if}

  {#if contact.home_number}
    <dt>Home</dt>
    <dd>{contact.home_number}</dd>
  {/if}

  {#if contact.addr1}
    <dt>Address</dt>
    <dd>
      {contact.addr1}
      {#if contact.addr2}<br>{contact.addr2}{/if}
      {#if contact.addr3}<br>{contact.addr3}{/if}
      {#if contact.city}<br>{contact.city}{/if}
      {#if contact.municipality}, {contact.municipality}{/if}
      {#if contact.postal_code} {contact.postal_code}{/if}
      {#if contact.country_code}<br>{contact.country_code}{/if}
    </dd>
  {/if}

  <dt>Business</dt>
  <dd>
    {#if contact.business}
      <a href="#/businesses/{contact.business.business_id}">{contact.business.business_name}</a>
    {:else}
      None
    {/if}
  </dd>
</dl>

{#if contact.business}
  <FullOnly>
    <h3>Business Details</h3>
    <dl>
      <dt>Phone</dt>
      <dd>{contact.business.business_phone}</dd>

      <dt>Address</dt>
      <dd class="preserve-breaks">{contact.business.business_address}</dd>

      <dt>Website</dt>
      <dd>{contact.business.website || ''}</dd>

      <dt>Tax Exemption</dt>
      <dd>{contact.business.tax_exemption_number || "(Not exempt)"}</dd>

      <dt>Payment Terms</dt>
      <dd>{contact.business.terms || 'None'}</dd>

      <dt>Default Contact</dt>
      <dd>
        {#if contact.business.default_contact}
          <a href="#/contacts/{contact.business.default_contact.contact_id}">{contact.business.default_contact.name}</a>
        {:else}
          None
        {/if}
      </dd>
    </dl>
  </FullOnly>
{/if}

<h3>Tags</h3>
<TagEditor endpoint="/api/contacts/{contact.contact_id}" initialTags={contact.tags || []}
  readonly={!$canManageJobs} />

<h3>Jobs
  {#if $canManageJobs}
    — <a href="#/jobs/new?contact={contact.contact_id}">New Job</a>
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
  {#if $canManageFinancials && contact.business}
    — <a href="#/purchase-orders/new?business={contact.business.business_id}&contact={contact.contact_id}">New Purchase Order</a>
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

<style>
</style>
