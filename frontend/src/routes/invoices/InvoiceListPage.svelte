<script>
  import { api } from '../../lib/api.js';
  import { pageRange, pageFromUrl } from '../../lib/pagination.js';
  import CustomerPicker from '../../components/CustomerPicker.svelte';

  let invoices = $state(null);
  let page = $state(1);
  let loading = $state(true);
  let error = $state(null);
  let statusFilter = $state('open');
  let ordering = $state('due_date');
  let dueFrom = $state('');
  let dueTo = $state('');
  let customer = $state(null);

  function customerParam() {
    if (!customer) return '';
    return customer.type === 'business'
      ? `&business=${customer.id}` : `&contact=${customer.id}`;
  }

  async function load() {
    loading = true;
    error = null;
    try {
      let url = `/api/invoices/?summary=true&page=${page}&status=${statusFilter}&ordering=${ordering}`;
      if (dueFrom) url += `&due_from=${dueFrom}`;
      if (dueTo) url += `&due_to=${dueTo}`;
      url += customerParam();
      invoices = await api.get(url);
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function money(v) { return v == null ? '' : `$${v}`; }

  $effect(() => {
    void page; void statusFilter; void ordering; void dueFrom; void dueTo; void customer;
    load();
  });
</script>

<div class="page-body">
<h2>Invoices {invoices ? `(${invoices.count})` : ''}</h2>

<p>
  <label>Status:
    <select bind:value={statusFilter} onchange={() => { page = 1; }}>
      <option value="open">Open</option>
      <option value="paid">Paid</option>
      <option value="draft">Draft</option>
      <option value="cancelled">Cancelled</option>
      <option value="all">All</option>
    </select>
  </label>
  &nbsp;
  <label>Sort:
    <select bind:value={ordering} onchange={() => { page = 1; }}>
      <option value="due_date">Due date ↑</option>
      <option value="-due_date">Due date ↓</option>
      <option value="-balance">Balance ↓</option>
      <option value="-total">Amount ↓</option>
      <option value="customer_name">Customer A–Z</option>
      <option value="-sent_date">Sent ↓</option>
    </select>
  </label>
  &nbsp;
  <label>Due from <input type="date" bind:value={dueFrom} onchange={() => { page = 1; }}></label>
  <label>to <input type="date" bind:value={dueTo} onchange={() => { page = 1; }}></label>
</p>
<p>
  <label>Customer:
    <CustomerPicker bind:value={customer} onSelect={() => { page = 1; }} />
  </label>
</p>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else if invoices}
  <table class="data-table">
    <thead>
      <tr>
        <th>Invoice #</th><th>Job</th><th>Customer</th><th>Status</th>
        <th>Sent</th><th>Due</th>
        <th class="text-right">Amount</th><th class="text-right">Paid</th>
        <th class="text-right">Balance</th>
      </tr>
    </thead>
    <tbody>
      {#each invoices.results as inv (inv.invoice_id)}
        <tr>
          <td><a href={`#/invoices/${inv.invoice_id}`}>{inv.display_number}</a></td>
          <td>
            {#if inv.job}<a href={`#/jobs/${inv.job}`}>{inv.job_number}</a>{/if}
          </td>
          <td>{inv.customer_name || ''}</td>
          <td>{inv.status}</td>
          <td>{inv.sent_date ? inv.sent_date.slice(0, 10) : ''}</td>
          <td>{inv.due_date || ''}{#if inv.is_late} ⚠️{/if}</td>
          <td class="text-right">{money(inv.total)}</td>
          <td class="text-right">{money(inv.amount_paid)}</td>
          <td class="text-right">{money(inv.balance)}</td>
        </tr>
      {/each}
    </tbody>
  </table>

  {#if invoices.count > 25}
    <p>
      {pageRange(invoices)}
      {#if invoices.previous}
        | <button onclick={() => { page = pageFromUrl(invoices.previous); }}>Previous</button>
      {/if}
      {#if invoices.next}
        | <button onclick={() => { page = pageFromUrl(invoices.next); }}>Next</button>
      {/if}
    </p>
  {/if}
{/if}
</div>
