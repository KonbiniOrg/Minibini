<!-- frontend/src/components/invoices/InvoiceDetail.svelte -->
<script>
  const {
    invoice,
    lineItems = [],
    onSendToQBO = null,
  } = $props();
</script>

<h2>Invoice {invoice.invoice_number}</h2>

<p><strong>Status:</strong> {invoice.status}</p>
<p><strong>Job:</strong> <a href="#/jobs/{invoice.job}">{invoice.job_number || `Job #${invoice.job}`}</a></p>
{#if invoice.created_date}
  <p><strong>Created:</strong> {new Date(invoice.created_date).toLocaleDateString()}</p>
{/if}

{#if invoice.qbo_id}
  <fieldset>
    <legend><strong>QuickBooks Status</strong></legend>
    <p><strong>QBO ID:</strong> {invoice.qbo_id}</p>
    <p><strong>Payment Status:</strong> {invoice.qbo_payment_status || 'Pending'}</p>
    {#if invoice.qbo_amount_paid}
      <p><strong>Amount Paid:</strong> ${Number(invoice.qbo_amount_paid).toFixed(2)}</p>
    {/if}
  </fieldset>
{:else if onSendToQBO}
  <p><button onclick={onSendToQBO}>Send to QuickBooks</button></p>
{/if}

<table border="1">
  <thead>
    <tr>
      <th>#</th>
      <th>Description</th>
      <th>Category</th>
      <th>Qty</th>
      <th>Unit</th>
      <th>Price</th>
      <th>Total</th>
    </tr>
  </thead>
  <tbody>
    {#each lineItems as item}
      <tr>
        <td>{item.line_number}</td>
        <td>{item.description}</td>
        <td>{item.accounting_category_name || '—'}</td>
        <td style="text-align: right">{item.qty}</td>
        <td>{item.units}</td>
        <td style="text-align: right">${Number(item.price).toFixed(2)}</td>
        <td style="text-align: right">${(item.qty * item.price).toFixed(2)}</td>
      </tr>
    {/each}
  </tbody>
</table>
