<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { pageRange, pageFromUrl } from '../../lib/pagination.js';
  import CustomerPicker from '../../components/CustomerPicker.svelte';
  import LoadState from '../../components/LoadState.svelte';
  import DataTable from '../../components/DataTable.svelte';

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
      error = errorMessage(e, 'Could not load invoices.');
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

<LoadState {loading} {error}>
{#if invoices}
  <DataTable
    rows={invoices.results}
    key={(inv) => inv.invoice_id}
    emptyText="No invoices found."
    columns={[
      { id: 'number',   label: 'Invoice #', cell: numberCell },
      { id: 'job',      label: 'Job',       cell: jobCell },
      { id: 'customer', label: 'Customer',  field: 'customer_name' },
      { id: 'status',   label: 'Status',    cell: statusCell },
      { id: 'sent',     label: 'Sent',      cell: sentCell },
      { id: 'due',      label: 'Due',       cell: dueCell },
      { id: 'amount',   label: 'Amount',    cell: amountCell,  align: 'right' },
      { id: 'paid',     label: 'Paid',      cell: paidCell,    align: 'right' },
      { id: 'balance',  label: 'Balance',   cell: balanceCell, align: 'right' },
    ]}
  />

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
</LoadState>
</div>


{#snippet numberCell(inv)}<a href={`#/invoices/${inv.invoice_id}`}>{inv.display_number}</a>{/snippet}
{#snippet jobCell(inv)}{#if inv.job}<a href={`#/jobs/${inv.job}`}>{inv.job_number}</a>{/if}{/snippet}
{#snippet statusCell(inv)}
  {inv.status}
  {#if inv.is_deposit}<span class="deposit-pill">DEPOSIT</span>{/if}
{/snippet}
{#snippet sentCell(inv)}{inv.sent_date ? inv.sent_date.slice(0, 10) : ''}{/snippet}
{#snippet dueCell(inv)}{inv.due_date || ''}{#if inv.is_late} ⚠️{/if}{/snippet}
{#snippet amountCell(inv)}{money(inv.total)}{/snippet}
{#snippet paidCell(inv)}{money(inv.amount_paid)}{/snippet}
{#snippet balanceCell(inv)}{money(inv.balance)}{/snippet}

<style>
  .deposit-pill {
    font-size: 9px; padding: 1px 6px; border-radius: 8px;
    font-weight: 600; background: #e0e7ff; color: #3730a3;
    margin-left: 6px;
  }
</style>
