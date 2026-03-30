<!-- frontend/src/routes/invoices/InvoiceDetailPage.svelte -->
<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import InvoiceDetail from '../../components/invoices/InvoiceDetail.svelte';
  import SendToQBODialog from '../../components/invoices/SendToQBODialog.svelte';

  const { params = {} } = $props();

  let invoice = $state(null);
  let loading = $state(true);
  let error = $state(null);
  let showSendDialog = $state(false);
  let success = $state(null);

  async function loadInvoice() {
    loading = true;
    error = null;
    try {
      invoice = await api.get(`/api/invoices/${params.id}/`);
    } catch (e) {
      error = e.message || 'Failed to load invoice';
    } finally {
      loading = false;
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
  {#if success}
    <p><strong>{success}</strong></p>
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

<p><a href="#/jobs/{invoice?.job}">Back to Job</a></p>
