<script>
  import { querystring } from 'svelte-spa-router';
  import { api, errorMessage } from '../lib/api.js';
  import DataTable from '../components/DataTable.svelte';
  import LoadState from '../components/LoadState.svelte';

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
      .catch(e => { error = errorMessage(e, 'Search failed.'); })
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

<div class="page-body">
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
      <LoadState {loading} {error} loadingText="Searching...">
      {#if results}
        <p>{results.total} result{results.total !== 1 ? 's' : ''} for <strong>{results.query}</strong>{withinQuery ? `, narrowed by "${withinQuery}"` : ''}</p>

        {#if results.results.jobs?.length}
          <h3>Jobs</h3>
          <DataTable
            rows={results.results.jobs}
            key={(g) => g.job.job_id}
            columns={[
              { id: 'number',      label: 'Job #',          cell: jobNumberCell },
              { id: 'name',        label: 'Name',           cell: jobNameCell },
              { id: 'contact',     label: 'Contact',        cell: jobContactCell },
              { id: 'status',      label: 'Status',         cell: jobStatusCell },
              { id: 'created',     label: 'Created',        cell: jobCreatedCell },
              { id: 'started',     label: 'Started',        cell: jobStartedCell },
              { id: 'description', label: 'Description',    cell: jobDescCell },
              { id: 'po',          label: 'Customer PO',    cell: jobPoCell },
              { id: 'tasks',       label: 'Matching Tasks', cell: jobTasksCell },
            ]}
          />
        {/if}

        {#if results.results.contacts?.length}
          <h3>Contacts</h3>
          <DataTable
            rows={results.results.contacts}
            key={(c) => c.contact_id}
            columns={[
              { id: 'name',     label: 'Name',     cell: contactNameCell },
              { id: 'business', label: 'Business', cell: contactBusinessCell },
              { id: 'email',    label: 'Email',    cell: contactEmailCell },
              { id: 'mobile',   label: 'Mobile',   cell: contactMobileCell },
              { id: 'work',     label: 'Work',     cell: contactWorkCell },
              { id: 'home',     label: 'Home',     cell: contactHomeCell },
              { id: 'city',     label: 'City',     cell: contactCityCell },
            ]}
          />
        {/if}

        {#if results.results.businesses?.length}
          <h3>Businesses</h3>
          <DataTable
            rows={results.results.businesses}
            key={(b) => b.business_id}
            columns={[
              { id: 'name',    label: 'Name',    cell: bizNameCell },
              { id: 'code',    label: 'Code',    cell: bizCodeCell },
              { id: 'address', label: 'Address', cell: bizAddressCell },
              { id: 'phone',   label: 'Phone',   cell: bizPhoneCell },
            ]}
          />
        {/if}

        {#if results.results.invoices?.length}
          <h3>Invoices</h3>
          <DataTable
            rows={results.results.invoices}
            key={(inv) => inv.invoice_id}
            columns={[
              { id: 'number',  label: 'Invoice #',           cell: invNumberCell },
              { id: 'job',     label: 'Job #',               cell: invJobCell },
              { id: 'status',  label: 'Status',              cell: invStatusCell },
              { id: 'created', label: 'Created',             cell: invCreatedCell },
              { id: 'lines',   label: 'Matching line items', cell: invLinesCell },
            ]}
          />
        {/if}

        {#if results.results.estimates?.length}
          <h3>Estimates</h3>
          <DataTable
            rows={results.results.estimates}
            key={(est) => est.estimate_id}
            columns={[
              { id: 'number',  label: 'Estimate #',          cell: estNumberCell },
              { id: 'version', label: 'Version',             field: 'version' },
              { id: 'status',  label: 'Status',              field: 'status' },
              { id: 'created', label: 'Created',             cell: estCreatedCell },
              { id: 'lines',   label: 'Matching line items', cell: estLinesCell },
            ]}
          />
        {/if}

        {#if results.results.purchase_orders?.length}
          <h3>Purchase Orders</h3>
          <DataTable
            rows={results.results.purchase_orders}
            key={(po) => po.po_id}
            columns={[
              { id: 'number',  label: 'PO #',                cell: poNumberCell },
              { id: 'status',  label: 'Status',              field: 'status' },
              { id: 'created', label: 'Created',             cell: poCreatedCell },
              { id: 'lines',   label: 'Matching line items', cell: poLinesCell },
            ]}
          />
        {/if}

        {#if results.results.inventory_items?.length}
          <h3>Inventory Items</h3>
          <DataTable
            rows={results.results.inventory_items}
            key={(item) => item.inventory_item_id}
            columns={[
              { id: 'code',        label: 'Code',          cell: itemCodeCell },
              { id: 'description', label: 'Description',   cell: itemDescCell },
              { id: 'units',       label: 'Units',         cell: itemUnitsCell },
              { id: 'price',       label: 'Selling Price', field: 'selling_price' },
            ]}
          />
        {/if}

        {#if results.total === 0}
          <p>No results found.</p>
        {/if}
      {/if}
      </LoadState>
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
            <p><small>Applies to invoices, estimates, POs, and inventory items.</small></p>
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
</div>

{#snippet jobNumberCell(g)}<a href="#/jobs/{g.job.job_id}">{@html hl(g.job.job_number)}</a>{/snippet}
{#snippet jobNameCell(g)}{@html hl(g.job.name)}{/snippet}
{#snippet jobContactCell(g)}{@html hl(g.job.contact_name)}{/snippet}
{#snippet jobStatusCell(g)}{g.job.status}{/snippet}
{#snippet jobCreatedCell(g)}{formatDate(g.job.created_date)}{/snippet}
{#snippet jobStartedCell(g)}{formatDate(g.job.start_date)}{/snippet}
{#snippet jobDescCell(g)}{@html hlt(g.job.description)}{/snippet}
{#snippet jobPoCell(g)}{@html hl(g.job.customer_po_number)}{/snippet}
{#snippet jobTasksCell(g)}{@html hlt(g.tasks.map(t => t.name).join(', ') || null)}{/snippet}

{#snippet contactNameCell(c)}<a href="#/contacts/{c.contact_id}">{@html hl(c.name)}</a>{/snippet}
{#snippet contactBusinessCell(c)}{#if c.business_name}{@html hl(c.business_name)}{:else}—{/if}{/snippet}
{#snippet contactEmailCell(c)}{@html hl(c.email)}{/snippet}
{#snippet contactMobileCell(c)}{@html hl(c.mobile_number)}{/snippet}
{#snippet contactWorkCell(c)}{@html hl(c.work_number)}{/snippet}
{#snippet contactHomeCell(c)}{@html hl(c.home_number)}{/snippet}
{#snippet contactCityCell(c)}{@html hl(c.city)}{/snippet}

{#snippet bizNameCell(b)}<a href="#/businesses/{b.business_id}">{@html hl(b.business_name)}</a>{/snippet}
{#snippet bizCodeCell(b)}{@html hl(b.our_reference_code)}{/snippet}
{#snippet bizAddressCell(b)}{@html hl(b.business_address)}{/snippet}
{#snippet bizPhoneCell(b)}{@html hl(b.business_phone)}{/snippet}

{#snippet invNumberCell(inv)}<a href="#/invoices/{inv.invoice_id}">{@html hl(inv.display_number)}</a>{/snippet}
{#snippet invJobCell(inv)}{@html hl(inv.job_number)}{/snippet}
{#snippet invStatusCell(inv)}{inv.status}{/snippet}
{#snippet invCreatedCell(inv)}{formatDate(inv.created_date)}{/snippet}
{#snippet invLinesCell(inv)}{@html hlt(inv.matching_descriptions?.join(', ') || null)}{/snippet}

{#snippet estNumberCell(est)}<a href="#/estimates/{est.estimate_id}">{@html hl(est.estimate_number)}</a>{/snippet}
{#snippet estCreatedCell(est)}{formatDate(est.created_date)}{/snippet}
{#snippet estLinesCell(est)}{@html hlt(est.matching_descriptions?.join(', ') || null)}{/snippet}

{#snippet poNumberCell(po)}<a href="#/purchase-orders/{po.po_id}">{@html hl(po.po_number)}</a>{/snippet}
{#snippet poCreatedCell(po)}{formatDate(po.created_date)}{/snippet}
{#snippet poLinesCell(po)}{@html hlt(po.matching_descriptions?.join(', ') || null)}{/snippet}

{#snippet itemCodeCell(item)}{@html hl(item.code)}{/snippet}
{#snippet itemDescCell(item)}{@html hlt(item.description)}{/snippet}
{#snippet itemUnitsCell(item)}{@html hl(item.units)}{/snippet}

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
