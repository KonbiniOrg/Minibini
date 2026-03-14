<script>
  import FullOnly from '../FullOnly.svelte';
  import { viewMode } from '../../stores/viewMode.js';
  import { pageFromUrl, pageRange } from '../../lib/pagination.js';
  const {
    contact,
    purchaseOrders = null,
    bills = null,
    onEdit = null,
    onDelete = null,
    onPOPageChange = null,
    onBillPageChange = null,
  } = $props();

  const closedJobStatuses = ['completed', 'cancelled'];
  const closedPOStatuses = ['received_in_full', 'cancelled'];
  const closedBillStatuses = ['paid_in_full', 'cancelled', 'refunded'];

  let visibleJobs = $derived(
    contact.jobs
      ? $viewMode === 'full'
        ? contact.jobs
        : contact.jobs.filter(j => !closedJobStatuses.includes(j.status))
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
      <dd>{contact.business.business_address}</dd>

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

<h3>Jobs</h3>
{#if visibleJobs.length > 0}
  <table border="1">
    <thead>
      <tr><th>Job #</th><th>Name</th><th>Status</th></tr>
    </thead>
    <tbody>
      {#each visibleJobs as job}
        <tr>
          <td>{job.job_number}</td>
          <td>{job.name}</td>
          <td>{job.status}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{:else}
  <p>No {$viewMode === 'lite' ? 'open ' : ''}jobs.</p>
{/if}

<h3>Purchase Orders</h3>
{#if visiblePOs.length > 0}
  <table border="1">
    <thead>
      <tr><th>PO #</th><th>Status</th></tr>
    </thead>
    <tbody>
      {#each visiblePOs as po}
        <tr>
          <td>{po.po_number}</td>
          <td>{po.status}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if purchaseOrders}
    <p>
      {pageRange(purchaseOrders)}
      {#if purchaseOrders.previous}
        | <a href="#" onclick={(e) => { e.preventDefault(); onPOPageChange(pageFromUrl(purchaseOrders.previous)); }}>Previous</a>
      {/if}
      {#if purchaseOrders.next}
        | <a href="#" onclick={(e) => { e.preventDefault(); onPOPageChange(pageFromUrl(purchaseOrders.next)); }}>Next</a>
      {/if}
    </p>
  {/if}
{:else}
  <p>No {$viewMode === 'lite' ? 'open ' : ''}purchase orders.</p>
{/if}

<h3>Bills</h3>
{#if visibleBills.length > 0}
  <table border="1">
    <thead>
      <tr><th>Bill #</th><th>Vendor Invoice</th><th>Status</th></tr>
    </thead>
    <tbody>
      {#each visibleBills as bill}
        <tr>
          <td>{bill.bill_number}</td>
          <td>{bill.vendor_invoice_number}</td>
          <td>{bill.status}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if bills}
    <p>
      {pageRange(bills)}
      {#if bills.previous}
        | <a href="#" onclick={(e) => { e.preventDefault(); onBillPageChange(pageFromUrl(bills.previous)); }}>Previous</a>
      {/if}
      {#if bills.next}
        | <a href="#" onclick={(e) => { e.preventDefault(); onBillPageChange(pageFromUrl(bills.next)); }}>Next</a>
      {/if}
    </p>
  {/if}
{:else}
  <p>No {$viewMode === 'lite' ? 'open ' : ''}bills.</p>
{/if}

<p>
  {#if onEdit}
    <button onclick={onEdit}>Edit</button>
  {/if}
  {#if onDelete}
    <button onclick={onDelete}>Delete</button>
  {/if}
</p>
