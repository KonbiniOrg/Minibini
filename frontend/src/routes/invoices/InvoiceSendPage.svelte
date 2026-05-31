<script>
  import { api } from '../../lib/api.js';
  import { push } from 'svelte-spa-router';
  import DocumentSendForm from '../../components/email/DocumentSendForm.svelte';

  const { params = {} } = $props();

  let invoice = $state(null);
  let lineItems = $state([]);
  let sendDefaults = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let submitting = $state(false);
  let submitError = $state(null);

  async function load() {
    loading = true;
    loadError = null;
    try {
      const [inv, defaults] = await Promise.all([
        api.get(`/api/invoices/${params.id}/`),
        api.get(`/api/invoices/${params.id}/send-defaults/`),
      ]);
      invoice = inv;
      lineItems = inv.line_items || [];
      sendDefaults = defaults;
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleSubmit(payload) {
    submitting = true;
    submitError = null;
    try {
      const fd = new FormData();
      fd.append('to', payload.to);
      fd.append('cc', payload.cc);
      fd.append('bcc', payload.bcc);
      fd.append('subject', payload.subject);
      fd.append('body', payload.body);
      for (const file of payload.extraFiles) {
        fd.append('attachments', file);
      }
      await api.postMultipart(`/api/invoices/${params.id}/send/`, fd);
      push(`/invoices/${params.id}`);
    } catch (e) {
      submitError = e.message;
      submitting = false;
    }
  }

  function total(items) {
    return items.reduce((acc, li) => acc + Number(li.qty || 0) * Number(li.price || 0), 0);
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

<p><a href="#/invoices/{params.id}">&larr; Cancel and return to Invoice</a></p>

<h2>Send Invoice</h2>

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p>Error: {loadError}</p>
{:else if invoice && sendDefaults}
  <DocumentSendForm
    {sendDefaults}
    submitLabel="Send Invoice"
    {submitting}
    {submitError}
    onSubmit={handleSubmit}
  />

  <hr>

  <section class="doc-ref">
    <h3>Invoice {invoice.invoice_number}</h3>
    <p><strong>Status:</strong> {invoice.status}</p>
    {#if invoice.qbo_id}
      <p><small>QBO ID: {invoice.qbo_id} (already pushed; send will skip QBO re-push)</small></p>
    {/if}

    <table border="1">
      <thead>
        <tr><th>#</th><th>Description</th><th>Qty</th><th>Price</th><th>Total</th></tr>
      </thead>
      <tbody>
        {#each lineItems as li}
          <tr>
            <td>{li.line_number}</td>
            <td>{li.description}</td>
            <td>{li.qty}</td>
            <td>${Number(li.price).toFixed(2)}</td>
            <td>${(Number(li.qty) * Number(li.price)).toFixed(2)}</td>
          </tr>
        {/each}
        <tr>
          <td colspan="4"><strong>Total</strong></td>
          <td><strong>${total(lineItems).toFixed(2)}</strong></td>
        </tr>
      </tbody>
    </table>
  </section>
{/if}

<style>
  .doc-ref { color: #555; }
  .doc-ref table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  .doc-ref th, .doc-ref td { padding: 4px 8px; }
</style>
