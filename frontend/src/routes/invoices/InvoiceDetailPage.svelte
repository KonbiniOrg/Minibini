<!-- frontend/src/routes/invoices/InvoiceDetailPage.svelte -->
<script>
  import { onMount } from 'svelte';
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import InvoiceDetail from '../../components/invoices/InvoiceDetail.svelte';
  import SendToQBODialog from '../../components/invoices/SendToQBODialog.svelte';
  import JobHeader from '../../components/jobs/JobHeader.svelte';

  const { params = {} } = $props();

  let invoice = $state(null);
  let job = $state(null);
  let contact = $state(null);
  let loading = $state(true);
  let error = $state(null);
  let showSendDialog = $state(false);
  let success = $state(null);

  async function loadInvoice() {
    loading = true;
    error = null;
    try {
      invoice = await api.get(`/api/invoices/${params.id}/`);
      if (invoice?.job) {
        await loadJobContext(invoice.job);
      }
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
        try {
          contact = await api.get(`/api/contacts/${job.contact}/`);
        } catch (e) {
          contact = null;
        }
      }
    } catch (e) {
      job = null;
      contact = null;
    }
  }

  function handleSendSuccess(result) {
    showSendDialog = false;
    success = `Sent to QuickBooks (QBO ID: ${result.qbo_id})`;
    loadInvoice();
  }

  onMount(() => {
    loadInvoice();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p><strong>Error:</strong> {error}</p>
{:else if invoice}
  {#if job}
    <JobHeader {job} {contact} onStatusChange={loadInvoice} />
  {/if}

  <div class="toolbar">
    <a href={`/jobs/${invoice.job}`} use:link class="back-link">&laquo; back to overview</a>
    <h2 class="page-title">Invoice: {invoice.invoice_number}</h2>
  </div>

  {#if success}
    <p class="success-msg">{success}</p>
  {/if}

  <InvoiceDetail
    {invoice}
    lineItems={invoice.line_items || []}
    onSendToQBO={() => showSendDialog = true}
  />

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
  .toolbar {
    display: flex; flex-wrap: wrap; align-items: baseline; gap: 12px;
    padding: 8px 24px;
  }
  .back-link { font-size: 13px; }
  .page-title { font-size: 18px; margin: 0; margin-left: auto; }
  .success-msg { padding: 8px 24px; color: #166534; }
</style>
