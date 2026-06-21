<script>
  import { querystring } from 'svelte-spa-router';
  import { api } from '../lib/api.js';

  let results = $state(null);
  let loading = $state(false);
  let error = $state('');

  // Filters
  let categoryFilter = $state('');
  let withinQuery = $state('');

  // Sidebar section open/closed state
  let sectionType = $state(true);
  let sectionDateCreated = $state(false);
  let sectionJobStarted = $state(false);
  let sectionJobStatus = $state(false);
  let sectionPrice = $state(false);
  let dateFrom = $state('');
  let dateTo = $state('');
  let startDateFrom = $state('');
  let startDateTo = $state('');
  let jobStatuses = $state([]);
  let priceMin = $state('');
  let priceMax = $state('');

  let query = $derived.by(() => {
    return new URLSearchParams($querystring || '').get('q') || '';
  });

  const CATEGORIES = [
    { key: 'jobs', label: 'Jobs' },
    { key: 'contacts', label: 'Contacts' },
    { key: 'businesses', label: 'Businesses' },
    { key: 'invoices', label: 'Invoices' },
    { key: 'estimates', label: 'Estimates' },
    { key: 'est_worksheets', label: 'Worksheets' },
    { key: 'bills', label: 'Bills' },
    { key: 'purchase_orders', label: 'Purchase Orders' },
    { key: 'inventory_items', label: 'Inventory Items' },
  ];

  const JOB_STATUSES = [
    { value: 'draft', label: 'Draft' },
    { value: 'submitted', label: 'Submitted' },
    { value: 'approved', label: 'Approved' },
    { value: 'work_complete', label: 'Work Complete' },
    { value: 'rejected', label: 'Rejected' },
    { value: 'completed', label: 'Completed' },
    { value: 'cancelled', label: 'Cancelled' },
  ];

  function toggleJobStatus(value) {
    if (jobStatuses.includes(value)) {
      jobStatuses = jobStatuses.filter(s => s !== value);
    } else {
      jobStatuses = [...jobStatuses, value];
    }
  }

  function clearFilters() {
    categoryFilter = '';
    dateFrom = '';
    dateTo = '';
    startDateFrom = '';
    startDateTo = '';
    jobStatuses = [];
    priceMin = '';
    priceMax = '';
    withinQuery = '';
  }

  let hasActiveFilters = $derived(
    categoryFilter || dateFrom || dateTo || startDateFrom || startDateTo || jobStatuses.length > 0
    || (priceMin !== '' && priceMin !== null && !Number.isNaN(priceMin))
    || (priceMax !== '' && priceMax !== null && !Number.isNaN(priceMax))
    || withinQuery
  );

  $effect(() => {
    const q = query;
    if (!q) { results = null; return; }

    const cat = categoryFilter;
    const df = dateFrom;
    const dt = dateTo;
    const sdf = startDateFrom;
    const sdt = startDateTo;
    const statuses = jobStatuses.slice();
    const pmin = priceMin !== '' && priceMin !== null && !Number.isNaN(priceMin) ? priceMin : null;
    const pmax = priceMax !== '' && priceMax !== null && !Number.isNaN(priceMax) ? priceMax : null;
    const within = withinQuery.trim();

    loading = true;
    error = '';

    const params = new URLSearchParams({ q });
    if (cat) params.set('category', cat);
    if (df) params.set('date_from', df);
    if (dt) params.set('date_to', dt);
    if (sdf) params.set('start_date_from', sdf);
    if (sdt) params.set('start_date_to', sdt);
    for (const s of statuses) params.append('job_status', s);
    if (pmin !== null) params.set('price_min', pmin);
    if (pmax !== null) params.set('price_max', pmax);
    if (within) params.set('within', within);

    api.get(`/api/search/?${params}`)
      .then(data => { results = data; })
      .catch(e => { error = e.message || 'Search failed.'; })
      .finally(() => { loading = false; });
  });

  function formatDate(val) {
    return val ? val.slice(0, 10) : '—';
  }

  function escapeHtml(str) {
    return String(str ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function highlight(text, ...terms) {
    let result = escapeHtml(text);
    for (const term of terms.filter(Boolean)) {
      const safe = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      result = result.replace(new RegExp(safe, 'gi'), m => `<mark>${m}</mark>`);
    }
    return result;
  }

  function trunc(text, max = 200) {
    if (!text) return text;
    const s = String(text);
    return s.length > max ? s.slice(0, max) + '…' : s;
  }

  function hl(text) {
    return text ? highlight(text, query, withinQuery) : '—';
  }

  function hlt(text) {
    return hl(trunc(text));
  }
</script>

<h2>Search{query ? `: "${query}"` : ''}</h2>

{#if !query}
  <p>Enter a search term above.</p>
{:else}
  <p>
    <label for="within-query"><strong>Search within results:</strong></label>
    <input type="search" id="within-query" bind:value={withinQuery} placeholder="Narrow results...">
    {#if withinQuery}
      <button type="button" onclick={() => withinQuery = ''}>Clear</button>
    {/if}
  </p>

  <div class="search-layout">
    <div class="results">
      {#if loading}
        <p>Searching...</p>
      {:else if error}
        <p>{error}</p>
      {:else if results}
        <p>{results.total} result{results.total !== 1 ? 's' : ''} for <strong>{results.query}</strong>{withinQuery ? `, narrowed by "${withinQuery}"` : ''}</p>

        {#if results.results.jobs?.length}
          <h3>Jobs</h3>
          <table class="data-table">
            <thead>
              <tr><th>Job #</th><th>Name</th><th>Contact</th><th>Status</th><th>Created</th><th>Started</th><th>Description</th><th>Customer PO</th><th>Matching Tasks</th></tr>
            </thead>
            <tbody>
              {#each results.results.jobs as group}
                <tr>
                  <td><a href="#/jobs/{group.job.job_id}">{@html hl(group.job.job_number)}</a></td>
                  <td>{@html hl(group.job.name)}</td>
                  <td>{@html hl(group.job.contact_name)}</td>
                  <td>{group.job.status}</td>
                  <td>{formatDate(group.job.created_date)}</td>
                  <td>{formatDate(group.job.start_date)}</td>
                  <td>{@html hlt(group.job.description)}</td>
                  <td>{@html hl(group.job.customer_po_number)}</td>
                  <td>{@html hlt(group.tasks.map(t => t.name).join(', ') || null)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}

        {#if results.results.contacts?.length}
          <h3>Contacts</h3>
          <table class="data-table">
            <thead>
              <tr><th>Name</th><th>Email</th><th>Mobile</th><th>Work</th><th>Home</th><th>City</th></tr>
            </thead>
            <tbody>
              {#each results.results.contacts as c}
                <tr>
                  <td><a href="#/contacts/{c.contact_id}">{@html hl(c.name)}</a></td>
                  <td>{@html hl(c.email)}</td>
                  <td>{@html hl(c.mobile_number)}</td>
                  <td>{@html hl(c.work_number)}</td>
                  <td>{@html hl(c.home_number)}</td>
                  <td>{@html hl(c.city)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}

        {#if results.results.businesses?.length}
          <h3>Businesses</h3>
          <table class="data-table">
            <thead>
              <tr><th>Name</th><th>Code</th><th>Address</th><th>Phone</th></tr>
            </thead>
            <tbody>
              {#each results.results.businesses as b}
                <tr>
                  <td><a href="#/businesses/{b.business_id}">{@html hl(b.business_name)}</a></td>
                  <td>{@html hl(b.our_reference_code)}</td>
                  <td>{@html hl(b.business_address)}</td>
                  <td>{@html hl(b.business_phone)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}

        {#if results.results.invoices?.length}
          <h3>Invoices</h3>
          <table class="data-table">
            <thead>
              <tr><th>Invoice #</th><th>Job #</th><th>Status</th><th>Created</th><th>Matching line items</th></tr>
            </thead>
            <tbody>
              {#each results.results.invoices as inv}
                <tr>
                  <td><a href="#/invoices/{inv.invoice_id}">{@html hl(inv.invoice_number)}</a></td>
                  <td>{@html hl(inv.job_number)}</td>
                  <td>{inv.status}</td>
                  <td>{formatDate(inv.created_date)}</td>
                  <td>{@html hlt(inv.matching_descriptions?.join(', ') || null)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}

        {#if results.results.estimates?.length}
          <h3>Estimates</h3>
          <table class="data-table">
            <thead>
              <tr><th>Estimate #</th><th>Version</th><th>Status</th><th>Created</th><th>Matching line items</th></tr>
            </thead>
            <tbody>
              {#each results.results.estimates as est}
                <tr>
                  <td><a href="#/estimates/{est.estimate_id}">{@html hl(est.estimate_number)}</a></td>
                  <td>{est.version}</td>
                  <td>{est.status}</td>
                  <td>{formatDate(est.created_date)}</td>
                  <td>{@html hlt(est.matching_descriptions?.join(', ') || null)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}

        {#if results.results.est_worksheets?.length}
          <h3>Worksheets</h3>
          <table class="data-table">
            <thead>
              <tr><th>Job #</th><th>Estimate #</th></tr>
            </thead>
            <tbody>
              {#each results.results.est_worksheets as ws}
                <tr>
                  <td>{ws.job_number || '—'}</td>
                  <td>{ws.estimate_number || '—'}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}

        {#if results.results.bills?.length}
          <h3>Bills</h3>
          <table class="data-table">
            <thead>
              <tr><th>Vendor Invoice #</th><th>Contact</th><th>PO #</th><th>Status</th><th>Created</th><th>Matching line items</th></tr>
            </thead>
            <tbody>
              {#each results.results.bills as bill}
                <tr>
                  <td>{bill.bill_number}</td>
                  <td>{@html hl(bill.vendor_invoice_number)}</td>
                  <td>{@html hl(bill.contact_name)}</td>
                  <td>{@html hl(bill.po_number)}</td>
                  <td>{bill.status}</td>
                  <td>{formatDate(bill.created_date)}</td>
                  <td>{@html hlt(bill.matching_descriptions?.join(', ') || null)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}

        {#if results.results.purchase_orders?.length}
          <h3>Purchase Orders</h3>
          <table class="data-table">
            <thead>
              <tr><th>PO #</th><th>Status</th><th>Created</th><th>Matching line items</th></tr>
            </thead>
            <tbody>
              {#each results.results.purchase_orders as po}
                <tr>
                  <td><a href="#/purchase-orders/{po.po_id}">{@html hl(po.po_number)}</a></td>
                  <td>{po.status}</td>
                  <td>{formatDate(po.created_date)}</td>
                  <td>{@html hlt(po.matching_descriptions?.join(', ') || null)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}

        {#if results.results.inventory_items?.length}
          <h3>Inventory Items</h3>
          <table class="data-table">
            <thead>
              <tr><th>Code</th><th>Description</th><th>Units</th><th>Selling Price</th></tr>
            </thead>
            <tbody>
              {#each results.results.inventory_items as item}
                <tr>
                  <td>{@html hl(item.code)}</td>
                  <td>{@html hlt(item.description)}</td>
                  <td>{@html hl(item.units)}</td>
                  <td>{item.selling_price}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}

        {#if results.total === 0}
          <p>No results found.</p>
        {/if}
      {/if}
    </div>

    <aside class="filters">
      <fieldset>
        <legend><strong>Refine search</strong></legend>

        <fieldset>
          <legend>
            <button type="button" class="section-toggle" onclick={() => sectionType = !sectionType}>
              <strong>Type{categoryFilter ? ' *' : ''}</strong> {sectionType ? '▲' : '▼'}
            </button>
          </legend>
          {#if sectionType}
            <p>
              <select id="cat-filter" bind:value={categoryFilter}>
                <option value="">All types</option>
                {#each CATEGORIES as cat}
                  <option value={cat.key}>{cat.label}</option>
                {/each}
              </select>
            </p>
          {/if}
        </fieldset>

        <fieldset>
          <legend>
            <button type="button" class="section-toggle" onclick={() => sectionDateCreated = !sectionDateCreated}>
              <strong>Date created{dateFrom || dateTo ? ' *' : ''}</strong> {sectionDateCreated ? '▲' : '▼'}
            </button>
          </legend>
          {#if sectionDateCreated}
            <p>
              <label for="date-from"><strong>From</strong></label><br>
              <input type="date" id="date-from" bind:value={dateFrom}>
            </p>
            <p>
              <label for="date-to"><strong>To</strong></label><br>
              <input type="date" id="date-to" bind:value={dateTo}>
            </p>
          {/if}
        </fieldset>

        <fieldset>
          <legend>
            <button type="button" class="section-toggle" onclick={() => sectionJobStarted = !sectionJobStarted}>
              <strong>Job started{startDateFrom || startDateTo ? ' *' : ''}</strong> {sectionJobStarted ? '▲' : '▼'}
            </button>
          </legend>
          {#if sectionJobStarted}
            <p>
              <label for="start-date-from"><strong>From</strong></label><br>
              <input type="date" id="start-date-from" bind:value={startDateFrom}>
            </p>
            <p>
              <label for="start-date-to"><strong>To</strong></label><br>
              <input type="date" id="start-date-to" bind:value={startDateTo}>
            </p>
          {/if}
        </fieldset>

        <fieldset>
          <legend>
            <button type="button" class="section-toggle" onclick={() => sectionJobStatus = !sectionJobStatus}>
              <strong>Job status{jobStatuses.length ? ' *' : ''}</strong> {sectionJobStatus ? '▲' : '▼'}
            </button>
          </legend>
          {#if sectionJobStatus}
            {#each JOB_STATUSES as s}
              <p>
                <label>
                  <input
                    type="checkbox"
                    checked={jobStatuses.includes(s.value)}
                    onchange={() => toggleJobStatus(s.value)}
                  >
                  {s.label}
                </label>
              </p>
            {/each}
          {/if}
        </fieldset>

        <fieldset>
          <legend>
            <button type="button" class="section-toggle" onclick={() => sectionPrice = !sectionPrice}>
              <strong>Price{(priceMin !== '' && !Number.isNaN(priceMin)) || (priceMax !== '' && !Number.isNaN(priceMax)) ? ' *' : ''}</strong> {sectionPrice ? '▲' : '▼'}
            </button>
          </legend>
          {#if sectionPrice}
            <p><small>Applies to invoices, estimates, bills, POs, and inventory items.</small></p>
            <p>
              <label for="price-min"><strong>Min ($)</strong></label><br>
              <input type="number" id="price-min" min="0" step="0.01" bind:value={priceMin}>
            </p>
            <p>
              <label for="price-max"><strong>Max ($)</strong></label><br>
              <input type="number" id="price-max" min="0" step="0.01" bind:value={priceMax}>
            </p>
          {/if}
        </fieldset>

        {#if hasActiveFilters}
          <p><button type="button" onclick={clearFilters}>Clear all filters</button></p>
        {/if}
      </fieldset>
    </aside>
  </div>
{/if}

<style>
  .search-layout {
    display: flex;
    gap: 1.5rem;
    align-items: flex-start;
  }

  .results {
    flex: 1;
    min-width: 0;
  }

  .filters {
    width: 220px;
    flex-shrink: 0;
    position: sticky;
    top: 1rem;
  }

  .section-toggle {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    text-align: left;
  }

  :global(mark) {
    background-color: #ffe066;
    padding: 0 1px;
    border-radius: 2px;
  }
</style>
