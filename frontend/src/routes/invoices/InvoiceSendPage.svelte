<script>
  import { api } from '../../lib/api.js';
  import { push } from 'svelte-spa-router';
  import DocumentSendForm from '../../components/email/DocumentSendForm.svelte';
  import { unappliedDepositCredits } from '../../lib/depositCredits.js';

  const { params = {} } = $props();

  let invoice = $state(null);
  let lineItems = $state([]);
  let sendDefaults = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let submitting = $state(false);
  let submitError = $state(null);
  // For the send-time unapplied-deposit-credit soft guard below — the
  // job's own invoices, fetched once alongside the invoice/send-defaults
  // load (same "fresh as of reaching the send screen" precision the rest
  // of this page already works with; no ?summary= param, so each entry is
  // the full InvoiceSerializer that lib/depositCredits.js expects).
  let jobInvoices = $state([]);

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
      try {
        const resp = await api.get(`/api/invoices/?job=${inv.job}`);
        jobInvoices = resp?.results || resp || [];
      } catch (_) {
        jobInvoices = [];
      }
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleSubmit(payload) {
    // Soft guard, not a hard block: deducting the credit on a LATER
    // invoice is legitimate, so this never prevents sending — it only
    // makes sure silence isn't the default when money is sitting unclaimed.
    // DocumentSendForm has already shown its own "Send this email to
    // …?" confirm by the time onSubmit (this function) runs; this is a
    // second, invoice-specific confirm layered on top of it.
    if (unappliedDepositCredits(jobInvoices).length > 0) {
      const proceed = confirm(
        "There's an unapplied deposit credit on this job — send anyway?"
      );
      if (!proceed) return; // abort — send dialog/state left untouched
    }
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

<div class="page-body">
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
    <h3>Invoice {invoice.display_number}</h3>
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
</div>

<style>
  .doc-ref { color: #555; }
  .doc-ref table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  .doc-ref th, .doc-ref td { padding: 4px 8px; }
</style>
