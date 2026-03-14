<script>
  import FullOnly from '../FullOnly.svelte';
  import { viewMode } from '../../stores/viewMode.js';
  const {
    business,
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
    business.jobs
      ? $viewMode === 'full'
        ? business.jobs
        : business.jobs.filter(j => !closedJobStatuses.includes(j.status))
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

  function pageFromUrl(url) {
    const match = url?.match(/page=(\d+)/);
    return match ? parseInt(match[1]) : 1;
  }

  const PAGE_SIZE = 25;

  function pageRange(paginatedData) {
    if (!paginatedData?.results?.length) return '';
    const page = paginatedData.next ? pageFromUrl(paginatedData.next) - 1
               : paginatedData.previous ? pageFromUrl(paginatedData.previous) + 1
               : 1;
    const min = (page - 1) * PAGE_SIZE + 1;
    const max = min + paginatedData.results.length - 1;
    return `${min}\u2013${max} of ${paginatedData.count}`;
  }
</script>

<dl>
  <dt>Reference Code</dt>
  <dd>{business.our_reference_code}</dd>

  <dt>Name</dt>
  <dd>{business.business_name}</dd>

  <dt>Phone</dt>
  <dd>{business.business_phone}</dd>

  <dt>Address</dt>
  <dd>{business.business_address}</dd>

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

<FullOnly>
  <h3>Contacts</h3>
  {#if business.contacts && business.contacts.length > 0}
    <table border="1">
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
