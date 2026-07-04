<script>
  import { api } from '../../lib/api.js';
  import { pageRange, pageFromUrl } from '../../lib/pagination.js';
  import CustomerPicker from '../../components/CustomerPicker.svelte';
  import { canManageFinancials } from '../../stores/permissions.js';

  let bills = $state(null);
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
      let url = `/api/bills/?summary=true&page=${page}&status=${statusFilter}&ordering=${ordering}`;
      if (dueFrom) url += `&due_from=${dueFrom}`;
      if (dueTo) url += `&due_to=${dueTo}`;
      url += customerParam();
      bills = await api.get(url);
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

<h2>Bills {bills ? `(${bills.count})` : ''}</h2>

<p>
  {#if $canManageFinancials}
    <a href="#/bills/new">New Bill</a> |
  {/if}
  <label>Status:
    <select bind:value={statusFilter} onchange={() => { page = 1; }}>
      <option value="open">Open</option>
      <option value="paid">Paid</option>
      <option value="draft">Draft</option>
      <option value="cancelled">Cancelled</option>
      <option value="refunded">Refunded</option>
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
      <option value="vendor_name">Vendor A–Z</option>
      <option value="-received_date">Received ↓</option>
    </select>
  </label>
  &nbsp;
  <label>Due from <input type="date" bind:value={dueFrom} onchange={() => { page = 1; }}></label>
  <label>to <input type="date" bind:value={dueTo} onchange={() => { page = 1; }}></label>
</p>
<p>
  <label>Vendor:
    <CustomerPicker bind:value={customer} onSelect={() => { page = 1; }} />
  </label>
</p>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else if bills}
  <table class="data-table">
    <thead>
      <tr>
        <th>Vendor Inv #</th><th>Vendor</th><th>PO #</th><th>Status</th>
        <th>Received</th><th>Due</th>
        <th class="text-right">Amount</th><th class="text-right">Balance</th>
      </tr>
    </thead>
    <tbody>
      {#each bills.results as bill (bill.bill_id)}
        <tr>
          <td><a href={`#/bills/${bill.bill_id}`}>{bill.vendor_invoice_number || '(no #)'}</a></td>
          <td>{bill.vendor_name || ''}</td>
          <td>
            {#if bill.po_number}<a href={`#/purchase-orders/${bill.purchase_order}`}>{bill.po_number}</a>{/if}
          </td>
          <td>{bill.status}</td>
          <td>{bill.received_date ? bill.received_date.slice(0, 10) : ''}</td>
          <td>{bill.due_date ? bill.due_date.slice(0, 10) : ''}</td>
          <td class="text-right">{money(bill.total)}</td>
          <td class="text-right">{money(bill.balance)}</td>
        </tr>
      {/each}
    </tbody>
  </table>

  {#if bills.count > 25}
    <p>
      {pageRange(bills)}
      {#if bills.previous}
        | <button onclick={() => { page = pageFromUrl(bills.previous); }}>Previous</button>
      {/if}
      {#if bills.next}
        | <button onclick={() => { page = pageFromUrl(bills.next); }}>Next</button>
      {/if}
    </p>
  {/if}
{/if}
