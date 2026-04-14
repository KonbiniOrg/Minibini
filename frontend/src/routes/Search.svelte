<script>
  import { push, querystring } from 'svelte-spa-router';
  import { api } from '../lib/api.js';

  let results = $state(null);
  let loading = $state(false);
  let error = $state('');
  let categoryFilter = $state('');

  let query = $derived.by(() => {
    return new URLSearchParams($querystring || '').get('q') || '';
  });

  $effect(() => {
    const q = query;
    const cat = categoryFilter;
    if (!q) { results = null; return; }
    loading = true;
    error = '';
    const params = new URLSearchParams({ q });
    if (cat) params.set('category', cat);
    api.get(`/api/search/?${params}`)
      .then(data => { results = data; })
      .catch(e => { error = e.message || 'Search failed.'; })
      .finally(() => { loading = false; });
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
    { key: 'price_list_items', label: 'Price List Items' },
  ];
</script>

<h2>Search{query ? `: "${query}"` : ''}</h2>

{#if query}
  <p>
    <label for="cat-filter"><strong>Filter by type:</strong></label>
    <select id="cat-filter" bind:value={categoryFilter}>
      <option value="">All</option>
      {#each CATEGORIES as cat}
        <option value={cat.key}>{cat.label}</option>
      {/each}
    </select>
  </p>
{/if}

{#if !query}
  <p>Enter a search term above.</p>
{:else if loading}
  <p>Searching...</p>
{:else if error}
  <p>{error}</p>
{:else if results}
  <p>{results.total} result{results.total !== 1 ? 's' : ''} for <strong>{results.query}</strong></p>

  {#if results.results.jobs?.length}
    <h3>Jobs</h3>
    <table border="1">
      <thead>
        <tr><th>Job #</th><th>Name</th><th>Status</th><th>Matching Tasks</th></tr>
      </thead>
      <tbody>
        {#each results.results.jobs as group}
          <tr>
            <td><a href="#/jobs/{group.job.job_id}">{group.job.job_number}</a></td>
            <td>{group.job.name || '—'}</td>
            <td>{group.job.status}</td>
            <td>{group.tasks.map(t => t.name).join(', ') || '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  {#if results.results.contacts?.length}
    <h3>Contacts</h3>
    <table border="1">
      <thead>
        <tr><th>Name</th><th>Email</th><th>Phone</th></tr>
      </thead>
      <tbody>
        {#each results.results.contacts as c}
          <tr>
            <td><a href="#/contacts/{c.contact_id}">{c.name}</a></td>
            <td>{c.email || '—'}</td>
            <td>{c.mobile_number || '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  {#if results.results.businesses?.length}
    <h3>Businesses</h3>
    <table border="1">
      <thead>
        <tr><th>Name</th><th>Code</th></tr>
      </thead>
      <tbody>
        {#each results.results.businesses as b}
          <tr>
            <td><a href="#/businesses/{b.business_id}">{b.business_name}</a></td>
            <td>{b.our_reference_code || '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  {#if results.results.invoices?.length}
    <h3>Invoices</h3>
    <table border="1">
      <thead>
        <tr><th>Invoice #</th><th>Job #</th><th>Status</th><th>Created</th></tr>
      </thead>
      <tbody>
        {#each results.results.invoices as inv}
          <tr>
            <td><a href="/invoicing/{inv.invoice_id}/">{inv.invoice_number}</a></td>
            <td>{inv.job_number || '—'}</td>
            <td>{inv.status}</td>
            <td>{inv.created_date ? inv.created_date.slice(0, 10) : '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  {#if results.results.estimates?.length}
    <h3>Estimates</h3>
    <table border="1">
      <thead>
        <tr><th>Estimate #</th><th>Version</th><th>Status</th><th>Created</th></tr>
      </thead>
      <tbody>
        {#each results.results.estimates as est}
          <tr>
            <td><a href="/estimates/{est.estimate_id}/">{est.estimate_number}</a></td>
            <td>{est.version}</td>
            <td>{est.status}</td>
            <td>{est.created_date ? est.created_date.slice(0, 10) : '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  {#if results.results.est_worksheets?.length}
    <h3>Worksheets</h3>
    <table border="1">
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
    <table border="1">
      <thead>
        <tr><th>Bill #</th><th>Vendor Invoice #</th><th>Status</th><th>Created</th></tr>
      </thead>
      <tbody>
        {#each results.results.bills as bill}
          <tr>
            <td><a href="/purchasing/bills/{bill.bill_id}/">{bill.bill_number}</a></td>
            <td>{bill.vendor_invoice_number || '—'}</td>
            <td>{bill.status}</td>
            <td>{bill.created_date ? bill.created_date.slice(0, 10) : '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  {#if results.results.purchase_orders?.length}
    <h3>Purchase Orders</h3>
    <table border="1">
      <thead>
        <tr><th>PO #</th><th>Status</th><th>Created</th></tr>
      </thead>
      <tbody>
        {#each results.results.purchase_orders as po}
          <tr>
            <td><a href="/purchasing/{po.po_id}/">{po.po_number}</a></td>
            <td>{po.status}</td>
            <td>{po.created_date ? po.created_date.slice(0, 10) : '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  {#if results.results.price_list_items?.length}
    <h3>Price List Items</h3>
    <table border="1">
      <thead>
        <tr><th>Code</th><th>Description</th><th>Units</th><th>Selling Price</th></tr>
      </thead>
      <tbody>
        {#each results.results.price_list_items as item}
          <tr>
            <td>{item.code}</td>
            <td>{item.description}</td>
            <td>{item.units || '—'}</td>
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
