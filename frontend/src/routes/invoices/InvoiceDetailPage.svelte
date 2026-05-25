<!-- frontend/src/routes/invoices/InvoiceDetailPage.svelte -->
<script>
  import { onMount } from 'svelte';
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user } from '../../stores/auth.js';
  import SendToQBODialog from '../../components/invoices/SendToQBODialog.svelte';
  import JobHeader from '../../components/jobs/JobHeader.svelte';
  import LineItemTable from '../../components/LineItemTable.svelte';

  const { params = {} } = $props();

  let invoice = $state(null);
  let job = $state(null);
  let contact = $state(null);
  let categories = $state([]);
  let loading = $state(true);
  let error = $state(null);
  let showSendDialog = $state(false);
  let success = $state(null);

  let canEditInvoice = $derived(
    ($user?.permissions?.includes('can_manage_jobs') ?? false) ||
    ($user?.permissions?.includes('can_manage_financials') ?? false)
  );

  async function loadInvoice() {
    loading = true;
    error = null;
    try {
      invoice = await api.get(`/api/invoices/${params.id}/`);
      if (invoice?.job) await loadJobContext(invoice.job);
    } catch (e) {
      error = e.message || 'Failed to load invoice';
    } finally {
      loading = false;
    }
  }

  async function loadJobContext(jobId) {
    try {
      job = await api.get(`/api/jobs/${jobId}/`);
      if (job.contact) {
        try { contact = await api.get(`/api/contacts/${job.contact}/`); }
        catch (e) { contact = null; }
      }
    } catch (e) { job = null; contact = null; }
  }

  async function loadCategories() {
    try {
      const resp = await api.get('/api/accounting-categories/?page_size=100');
      categories = resp.results || resp;
    } catch (_) { categories = []; }
  }

  function handleSendSuccess(result) {
    showSendDialog = false;
    success = `Sent to QuickBooks (QBO ID: ${result.qbo_id})`;
    loadInvoice();
  }

  function fmtDate(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleString();
  }

  onMount(() => {
    loadInvoice();
    loadCategories();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p class="error"><strong>Error:</strong> {error}</p>
{:else if invoice}
  {#if job}
    <JobHeader {job} {contact} onStatusChange={loadInvoice} />
  {/if}

  <div class="toolbar">
    <a href={`/jobs/${invoice.job}`} use:link class="back-link">&laquo; back to overview</a>
    <span class="page-title">Invoice: {invoice.invoice_number}</span>
    <span class="status-badge status-{invoice.status}">{invoice.status}</span>
    {#if invoice.status === 'draft' && canEditInvoice}
      <a href={`/invoices/${invoice.invoice_id}/wizard`} use:link>Continue in wizard</a>
    {/if}
    {#if !invoice.qbo_id && canEditInvoice}
      <button type="button" onclick={() => showSendDialog = true}>Send to QuickBooks</button>
    {/if}
  </div>

  {#if success}
    <p class="success-msg">{success}</p>
  {/if}

  <table class="metadata-table">
    <tbody>
      <tr><th>Field</th><th>Value</th></tr>
      <tr><td>Invoice Number</td><td>{invoice.invoice_number}</td></tr>
      <tr><td>Status</td><td>{invoice.status}</td></tr>
      <tr><td>Created Date</td><td>{fmtDate(invoice.created_date)}</td></tr>
      <tr><td>Sent Date</td><td>{invoice.sent_date ? fmtDate(invoice.sent_date) : 'Not sent yet'}</td></tr>
      <tr><td>Due Date</td><td>{invoice.due_date ? fmtDate(invoice.due_date) : '—'}{#if invoice.is_late} <span class="late-flag">(late)</span>{/if}</td></tr>
      <tr><td>Closed Date</td><td>{invoice.closed_date ? fmtDate(invoice.closed_date) : 'Not closed yet'}</td></tr>
      {#if invoice.qbo_id}
        <tr><td>QBO ID</td><td>{invoice.qbo_id}</td></tr>
        <tr><td>QBO Payment Status</td><td>{invoice.qbo_payment_status || 'Pending'}</td></tr>
        {#if invoice.qbo_amount_paid}
          <tr><td>Amount Paid</td><td>${Number(invoice.qbo_amount_paid).toFixed(2)}</td></tr>
        {/if}
      {/if}
    </tbody>
  </table>

  <h3>Line Items</h3>
  <LineItemTable lineItems={invoice.line_items || []} {categories} />

  {#if showSendDialog}
    <SendToQBODialog
      invoiceId={invoice.invoice_id}
      defaultEmail={invoice.default_send_to || ''}
      onSuccess={handleSendSuccess}
      onCancel={() => showSendDialog = false}
    />
  {/if}
{/if}

<style>
  .error { color: #a8071a; }
  .toolbar {
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
    padding: 8px 24px;
  }
  .back-link { font-size: 13px; }
  .page-title { font-size: 18px; font-weight: 600; }
  .status-badge {
    padding: 4px 12px; border-radius: 12px; font-size: 13px;
    font-weight: 600; text-transform: capitalize;
  }
  .status-draft { background: #f3f4f6; color: #374151; }
  .status-sent { background: #dbeafe; color: #1e40af; }
  .status-paid { background: #dcfce7; color: #166534; }
  .status-cancelled { background: #fef3c7; color: #92400e; }
  .late-flag { color: #b91c1c; font-weight: 600; }
  .success-msg { padding: 8px 24px; color: #166534; }
  .metadata-table { border-collapse: collapse; margin: 0 24px 16px; }
  .metadata-table th, .metadata-table td { padding: 6px 10px; }
  h3 { padding: 0 24px; }
</style>
